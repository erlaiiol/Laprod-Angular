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
import android.media.audiofx.PresetReverb
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

@CapacitorPlugin(name = "PitchMonitor")
class PitchMonitorPlugin : Plugin() {

    private var activeSession: AudioRecordingSession? = null

    @PluginMethod
    fun startSession(call: PluginCall) {
        if (activeSession != null) {
            call.reject("Session already active. Call stopSession first.")
            return
        }

        val speedStr = call.getString("retuneSpeed") ?: "natural"
        val smoothK  = when (speedStr) {
            "robot"   -> 0.00f
            "precise" -> 0.55f
            else      -> 0.82f
        }

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

    @PluginMethod
    fun checkHeadphones(call: PluginCall) {
        val am = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        var hpType = "none"

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            for (device in am.getDevices(AudioManager.GET_DEVICES_OUTPUTS)) {
                when (device.type) {
                    AudioDeviceInfo.TYPE_WIRED_HEADSET,
                    AudioDeviceInfo.TYPE_WIRED_HEADPHONES -> hpType = "wired"
                    AudioDeviceInfo.TYPE_BLUETOOTH_SCO    -> if (hpType != "wired") hpType = "bluetooth"
                    AudioDeviceInfo.TYPE_BLUETOOTH_A2DP   -> if (hpType != "wired" && hpType != "bluetooth") hpType = "bluetooth-a2dp"
                    else -> {}
                }
            }
        } else {
            @Suppress("DEPRECATION")
            when {
                am.isWiredHeadsetOn  -> hpType = "wired"
                am.isBluetoothScoOn  -> hpType = "bluetooth"
                am.isBluetoothA2dpOn -> hpType = "bluetooth-a2dp"
            }
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
// Monitoring autotune :
//   monitorAutotune=false → volume direct (AudioTrack write sans pitch shift)
//   monitorAutotune=true  → RubberBandProcessor (formant preservé, ~10 ms latence)
//
// Architecture monitoring avec Rubber Band :
//
//   [TarsosDSP AudioDispatcher]
//       └── AudioProcessor.process(event):
//               event.floatBuffer → RubberBandProcessor.process()
//               retrieve() → convertir float→Int16 → AudioTrack
//       └── PitchProcessor (YIN):
//               détecte la hauteur → rubberBand.setPitchCents(correction)
//
// La correction s'applique AU BLOC SUIVANT (1 frame de délai = 23 ms @ 44.1 kHz).

class AudioRecordingSession(private val opts: RecordingOptions, private val context: Context) {

    var onLevel:       ((Float) -> Unit)? = null
    var onPitch:       ((Float, Float) -> Unit)? = null
    var onInterrupted: (() -> Unit)? = null

    private val SAMPLE_RATE = 44_100

    // 1024 samples @ 44.1 kHz : half=512, min détectable ≈ 86 Hz → voix masculines OK
    private val MONITOR_FRAME  = 1024
    private val STANDARD_FRAME = android.media.AudioRecord.getMinBufferSize(
        SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT
    )

    private val scale: FloatArray = ScaleBuilder.buildScaleHz(opts.trackKey)
    private val pcmBuffer         = ByteArrayOutputStream()
    private var dispatcher: AudioDispatcher? = null
    private var outputTrack: AudioTrack?     = null
    private var rubberBand: RubberBandProcessor? = null
    private var reverb: PresetReverb?        = null
    private var job: Job?                    = null

    private var smoothedSemitones = 0f
    private val MONITOR_CAP       = 2.5f

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

        // ── Enregistrement PCM + monitoring ───────────────────────────────────
        dispatcher!!.addAudioProcessor(object : AudioProcessor {
            override fun process(event: AudioEvent): Boolean {
                // Toujours enregistrer les octets bruts (audio non traité → serveur)
                pcmBuffer.write(event.byteBuffer, 0, event.byteBuffer.size)
                onLevel?.invoke(event.getRMS().toFloat())

                if (!opts.useMonitor) return true

                if (opts.monitorAutotune) {
                    // Passer par Rubber Band pour le monitoring avec autotune
                    rubberBand?.process(event.floatBuffer)
                    val available = rubberBand?.available() ?: 0
                    if (available > 0) {
                        val out = FloatArray(available)
                        rubberBand?.retrieve(out)
                        outputTrack?.write(floatsToInt16(out, opts.voiceGain), 0, available * 2)
                    }
                } else {
                    // Monitoring simple : volume direct, pas de pitch shift
                    outputTrack?.write(applyGain(event.byteBuffer, opts.voiceGain),
                                       0, event.byteBuffer.size)
                }
                return true
            }
            override fun processingFinished() {}
        })

        // ── Détection de hauteur YIN ──────────────────────────────────────────
        val pdh = PitchDetectionHandler { result: PitchDetectionResult, _: AudioEvent ->
            val hz = result.pitch
            if (!result.isPitched || hz < 80f || hz > 1_200f) return@PitchDetectionHandler

            val nearest      = PitchCorrectionEngine.findNearestNote(hz, scale)
                               ?: return@PitchDetectionHandler
            val rawSemitones = PitchCorrectionEngine.correctionSemitones(hz, nearest)

            if (opts.monitorAutotune && opts.useMonitor) {
                smoothedSemitones = opts.smoothK * smoothedSemitones +
                                    (1 - opts.smoothK) * rawSemitones
                val clamped = smoothedSemitones.coerceIn(-MONITOR_CAP, MONITOR_CAP)

                // Communiquer la correction au processeur Rubber Band (thread-safe).
                // Elle sera appliquée au prochain bloc process() (délai 1 frame ≈ 23 ms).
                rubberBand?.setPitchCents(clamped * 100f)
                onPitch?.invoke(hz, clamped)
            } else {
                onPitch?.invoke(hz, rawSemitones)
            }
        }
        dispatcher!!.addAudioProcessor(PitchProcessor(YIN, SAMPLE_RATE.toFloat(), bufferSize, pdh))

        // ── AudioTrack ────────────────────────────────────────────────────────
        if (opts.useMonitor) {
            val minBuf     = AudioTrack.getMinBufferSize(SAMPLE_RATE,
                                AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT)
            val targetBuf  = SAMPLE_RATE / 100 * 2   // 10 ms en Int16
            val outBufSize = maxOf(minBuf, targetBuf)

            outputTrack = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                AudioTrack.Builder()
                    .setAudioAttributes(
                        AudioAttributes.Builder()
                            .setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION)
                            .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                            .build()
                    )
                    .setAudioFormat(
                        AudioFormat.Builder()
                            .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                            .setSampleRate(SAMPLE_RATE)
                            .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                            .build()
                    )
                    .setBufferSizeInBytes(outBufSize)
                    .setTransferMode(AudioTrack.MODE_STREAM)
                    .setPerformanceMode(AudioTrack.PERFORMANCE_MODE_LOW_LATENCY)
                    .build()
                    .also { it.play() }
            } else {
                @Suppress("DEPRECATION")
                AudioTrack(
                    AudioManager.STREAM_MUSIC, SAMPLE_RATE,
                    AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT,
                    outBufSize, AudioTrack.MODE_STREAM
                ).also { it.play() }
            }

            // Créer Rubber Band uniquement pour le monitoring autotune
            if (opts.monitorAutotune) {
                rubberBand = RubberBandProcessor(SAMPLE_RATE)
            }

            // Reverb plate sur le retour monitoring (miroir du chemin iOS).
            // runCatching : AudioEffect peut échouer sur certains appareils / émulateurs.
            if (opts.reverbWet > 0f) {
                runCatching {
                    reverb = PresetReverb(0, outputTrack!!.audioSessionId).apply {
                        preset  = PresetReverb.PRESET_PLATE
                        enabled = true
                    }
                }
            }
        }

        // ── AudioFocus ────────────────────────────────────────────────────────
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

        noisyReceiver = object : BroadcastReceiver() {
            override fun onReceive(ctx: Context, intent: Intent) {
                if (intent.action == AudioManager.ACTION_AUDIO_BECOMING_NOISY) {
                    onInterrupted?.invoke()
                }
            }
        }
        context.registerReceiver(noisyReceiver,
                                  IntentFilter(AudioManager.ACTION_AUDIO_BECOMING_NOISY))

        job = CoroutineScope(Dispatchers.IO).launch { dispatcher!!.run() }
    }

    fun stop(): SessionResult {
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
        rubberBand?.close()
        rubberBand = null
        reverb?.release()
        reverb = null
        outputTrack?.stop()
        outputTrack?.release()
        outputTrack = null
        dispatcher  = null
        return SessionResult(pcmBuffer.toByteArray(), SAMPLE_RATE)
    }

    // ── PCM conversions ───────────────────────────────────────────────────────

    // Float32 [-1,1] → Int16 little-endian bytes, with gain
    private fun floatsToInt16(samples: FloatArray, gain: Float): ByteArray {
        val out = ByteArray(samples.size * 2)
        for (i in samples.indices) {
            val s  = (samples[i] * gain * 32767f).toInt().coerceIn(-32_768, 32_767).toShort()
            out[i * 2]     = (s.toInt() and 0xFF).toByte()
            out[i * 2 + 1] = ((s.toInt() shr 8) and 0xFF).toByte()
        }
        return out
    }

    // Int16 little-endian bytes → gain applied in-place
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

private typealias Void = Unit
