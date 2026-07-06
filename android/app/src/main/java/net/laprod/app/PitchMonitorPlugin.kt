package net.laprod.app

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.media.AudioAttributes
import android.media.AudioDeviceInfo
import android.media.AudioFocusRequest
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioTrack
import android.media.PlaybackParams
import android.os.Build
import android.util.Base64
import be.tarsos.dsp.AudioDispatcher
import be.tarsos.dsp.AudioEvent
import be.tarsos.dsp.AudioProcessor
import be.tarsos.dsp.io.android.AudioDispatcherFactory
import be.tarsos.dsp.pitch.PitchDetectionHandler
import be.tarsos.dsp.pitch.PitchDetectionResult
import be.tarsos.dsp.pitch.PitchProcessor
import be.tarsos.dsp.pitch.PitchProcessor.PitchEstimationAlgorithm.YIN
import com.getcapacitor.JSObject
import com.getcapacitor.Plugin
import com.getcapacitor.PluginCall
import com.getcapacitor.PluginMethod
import com.getcapacitor.annotation.CapacitorPlugin
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import java.io.ByteArrayOutputStream
import kotlin.math.pow

// ── Plugin ────────────────────────────────────────────────────────────────────
//
// Responsabilité unique : gestion du cycle de vie Capacitor (startSession /
// stopSession / checkHeadphones) et pont vers les composants DSP.
//
// La logique audio de bas niveau est isolée dans AudioRecordingSession.

@CapacitorPlugin(name = "PitchMonitor")
class PitchMonitorPlugin : Plugin() {

    private var activeSession: AudioRecordingSession? = null

    // ── startSession ──────────────────────────────────────────────────────────

    @PluginMethod
    fun startSession(call: PluginCall) {
        if (activeSession != null) {
            call.reject("Session already active. Call stopSession first.")
            return
        }

        val speedStr = call.getString("retuneSpeed") ?: "natural"
        val smoothK  = if (speedStr == "precise") 0.5f else 0.85f

        val opts = RecordingOptions(
            useMonitor      = call.getBoolean("useMonitor")      ?: false,
            voiceGain       = call.getFloat("voiceGain")         ?: 1.0f,
            reverbWet       = call.getFloat("reverbWet")         ?: 0.15f,
            trackKey        = call.getString("trackKey")         ?: "",
            monitorAutotune = call.getBoolean("monitorAutotune") ?: false,
            smoothK         = smoothK,
        )

        val session = AudioRecordingSession(opts, context)
        session.onLevel = { rms -> notifyListeners("level", JSObject().apply { put("rms", rms) }) }
        session.onPitch = { hz, correction ->
            notifyListeners("pitch", JSObject().apply {
                put("hz", hz)
                put("correction", correction)
            })
        }
        session.onInterrupted = {
            // Exécuter sur le thread principal pour respecter les garanties Capacitor
            activity?.runOnUiThread {
                val active = activeSession ?: return@runOnUiThread
                val result = active.stop()
                activeSession = null
                notifyListeners("sessionInterrupted", JSObject().apply {
                    put("pcmBase64",  Base64.encodeToString(result.pcmBytes, Base64.NO_WRAP))
                    put("sampleRate", result.sampleRate)
                    put("channels",   1)
                    put("format",     "int16")
                    put("partial",    true)
                })
            }
        }
        session.start()
        activeSession = session
        call.resolve()
    }

    // ── stopSession ───────────────────────────────────────────────────────────

    @PluginMethod
    fun stopSession(call: PluginCall) {
        val session = activeSession ?: run {
            call.reject("No active session.")
            return
        }
        val result = session.stop()
        activeSession = null

        call.resolve(JSObject().apply {
            put("pcmBase64",  Base64.encodeToString(result.pcmBytes, Base64.NO_WRAP))
            put("sampleRate", result.sampleRate)
            put("channels",   1)
            put("format",     "int16")
        })
    }

    // ── checkHeadphones ───────────────────────────────────────────────────────

    @PluginMethod
    fun checkHeadphones(call: PluginCall) {
        val am = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        var hpType = "none"

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            val devices = am.getDevices(AudioManager.GET_DEVICES_OUTPUTS)
            for (device in devices) {
                when (device.type) {
                    AudioDeviceInfo.TYPE_WIRED_HEADSET,
                    AudioDeviceInfo.TYPE_WIRED_HEADPHONES -> hpType = "wired"
                    // SCO (HFP) supporte le monitoring audio bidirectionnel
                    AudioDeviceInfo.TYPE_BLUETOOTH_SCO    -> if (hpType != "wired") hpType = "bluetooth"
                    // A2DP = lecture seule, monitoring micro impossible
                    AudioDeviceInfo.TYPE_BLUETOOTH_A2DP   -> if (hpType != "wired" && hpType != "bluetooth") hpType = "bluetooth-a2dp"
                    else -> {}
                }
            }
        } else {
            @Suppress("DEPRECATION")
            if (am.isWiredHeadsetOn) hpType = "wired"
            @Suppress("DEPRECATION")
            else if (am.isBluetoothScoOn) hpType = "bluetooth"
            @Suppress("DEPRECATION")
            else if (am.isBluetoothA2dpOn) hpType = "bluetooth-a2dp"
        }

        call.resolve(JSObject().apply { put("type", hpType) })
    }
}

// ── RecordingOptions ──────────────────────────────────────────────────────────

data class RecordingOptions(
    val useMonitor:      Boolean,
    val voiceGain:       Float,
    val reverbWet:       Float,
    val trackKey:        String,
    val monitorAutotune: Boolean,
    val smoothK:         Float,
)

// ── SessionResult ─────────────────────────────────────────────────────────────

data class SessionResult(val pcmBytes: ByteArray, val sampleRate: Int)

// ── AudioRecordingSession ─────────────────────────────────────────────────────
//
// Encapsule TarsosDSP AudioDispatcher + AudioTrack de monitoring.
// Monitoring autotune : correction de hauteur via PlaybackParams.pitch sur AudioTrack.

class AudioRecordingSession(private val opts: RecordingOptions, private val context: Context) {

    var onLevel:       ((Float) -> Unit)? = null
    var onPitch:       ((Float, Float) -> Unit)? = null
    var onInterrupted: (() -> Unit)? = null

    private val SAMPLE_RATE = 44_100

    // Monitoring autotune : frame 512 (10 ms) ; standard : frame calculé par TarsosDSP
    private val MONITOR_FRAME  = 512
    private val STANDARD_FRAME = android.media.AudioRecord.getMinBufferSize(
        SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT
    )

    private val scale: FloatArray = ScaleBuilder.buildScaleHz(opts.trackKey)
    private val pcmBuffer         = ByteArrayOutputStream()
    private var dispatcher: AudioDispatcher? = null
    private var outputTrack: AudioTrack?     = null
    private var job: Job?                    = null

    // Lissage exponentiel pour le monitoring autotune (accès mono-thread : coroutine IO)
    private var smoothedSemitones = 0f
    private val MONITOR_CAP      = 1.5f   // semitones

    // Gestion des interruptions audio (appel entrant, autre app)
    private var focusRequest:  AudioFocusRequest? = null
    private var noisyReceiver: BroadcastReceiver? = null

    private val focusListener = AudioManager.OnAudioFocusChangeListener { change ->
        if (change == AudioManager.AUDIOFOCUS_LOSS ||
            change == AudioManager.AUDIOFOCUS_LOSS_TRANSIENT) {
            onInterrupted?.invoke()
        }
    }

    fun start() {
        pcmBuffer.reset()
        smoothedSemitones = 0f

        val bufferSize = if (opts.monitorAutotune) MONITOR_FRAME else STANDARD_FRAME
        dispatcher = AudioDispatcherFactory.fromDefaultMicrophone(SAMPLE_RATE, bufferSize, 0)

        // ── Enregistrement PCM brut ────────────────────────────────────────────
        dispatcher!!.addAudioProcessor(object : AudioProcessor {
            override fun process(event: AudioEvent): Boolean {
                pcmBuffer.write(event.byteBuffer, 0, event.byteBuffer.size)
                onLevel?.invoke(event.rMS)
                if (opts.useMonitor) {
                    outputTrack?.write(applyGain(event.byteBuffer, opts.voiceGain), 0, event.byteBuffer.size)
                }
                return true
            }
            override fun processingFinished() {}
        })

        // ── Détection de hauteur YIN (TarsosDSP) ──────────────────────────────
        val pdh = PitchDetectionHandler { result: PitchDetectionResult, _: AudioEvent ->
            val hz = result.pitch
            if (!result.isPitched || hz < 80f || hz > 1_200f) return@PitchDetectionHandler

            val nearest    = PitchCorrectionEngine.findNearestNote(hz, scale) ?: return@PitchDetectionHandler
            val rawSemitones = PitchCorrectionEngine.correctionSemitones(hz, nearest)

            if (opts.monitorAutotune && opts.useMonitor) {
                // Lissage exponentiel
                smoothedSemitones = opts.smoothK * smoothedSemitones + (1 - opts.smoothK) * rawSemitones
                val clamped = smoothedSemitones.coerceIn(-MONITOR_CAP, MONITOR_CAP)

                // Pitch shift via PlaybackParams (API 23+, préserve la durée)
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                    val pitchRatio = 2f.pow(clamped / 12f)
                    outputTrack?.playbackParams = PlaybackParams().apply {
                        pitch = pitchRatio
                        speed = 1f
                    }
                }
                onPitch?.invoke(hz, clamped)
            } else {
                onPitch?.invoke(hz, rawSemitones)
            }
        }
        dispatcher!!.addAudioProcessor(PitchProcessor(YIN, SAMPLE_RATE.toFloat(), bufferSize, pdh))

        // ── Monitoring AudioTrack ──────────────────────────────────────────────
        if (opts.useMonitor) {
            val outBufSize = AudioTrack.getMinBufferSize(
                SAMPLE_RATE, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT
            )
            outputTrack = AudioTrack(
                AudioManager.STREAM_MUSIC, SAMPLE_RATE,
                AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT,
                outBufSize, AudioTrack.MODE_STREAM
            ).also { it.play() }
        }

        // ── AudioFocus — interrompt si un appel ou une app prioritaire prend l'audio ──
        val am = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            focusRequest = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_EXCLUSIVE)
                .setAudioAttributes(
                    AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_MEDIA)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                        .build()
                )
                .setOnAudioFocusChangeListener(focusListener)
                .build()
            am.requestAudioFocus(focusRequest!!)
        } else {
            @Suppress("DEPRECATION")
            am.requestAudioFocus(focusListener, AudioManager.STREAM_MUSIC,
                AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_EXCLUSIVE)
        }

        // ── AUDIO_BECOMING_NOISY — débrancher le casque pendant l'enregistrement ──
        noisyReceiver = object : BroadcastReceiver() {
            override fun onReceive(ctx: Context, intent: Intent) {
                if (intent.action == AudioManager.ACTION_AUDIO_BECOMING_NOISY) {
                    onInterrupted?.invoke()
                }
            }
        }
        context.registerReceiver(noisyReceiver, IntentFilter(AudioManager.ACTION_AUDIO_BECOMING_NOISY))

        job = CoroutineScope(Dispatchers.IO).launch { dispatcher!!.run() }
    }

    fun stop(): SessionResult {
        // Libérer les ressources audio système avant d'arrêter le dispatcher
        try { context.unregisterReceiver(noisyReceiver) } catch (_: Exception) {}
        noisyReceiver = null
        val am = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            focusRequest?.let { am.abandonAudioFocusRequest(it) }
        } else {
            @Suppress("DEPRECATION")
            am.abandonAudioFocus(focusListener)
        }
        focusRequest = null

        dispatcher?.stop()
        job?.cancel()
        outputTrack?.stop()
        outputTrack?.release()
        outputTrack = null
        dispatcher  = null
        return SessionResult(pcmBuffer.toByteArray(), SAMPLE_RATE)
    }

    // ── Gain PCM Int16 ────────────────────────────────────────────────────────

    private fun applyGain(bytes: ByteArray, gain: Float): ByteArray {
        val out = ByteArray(bytes.size)
        var i = 0
        while (i < bytes.size - 1) {
            val sample = ((bytes[i + 1].toInt() shl 8) or (bytes[i].toInt() and 0xFF)).toShort()
            val scaled = (sample * gain).toInt().coerceIn(-32_768, 32_767).toShort()
            out[i]     = (scaled.toInt() and 0xFF).toByte()
            out[i + 1] = ((scaled.toInt() shr 8) and 0xFF).toByte()
            i += 2
        }
        return out
    }
}

// ── Alias de type (lisibilité des lambdas) ────────────────────────────────────

private typealias Void = Unit
