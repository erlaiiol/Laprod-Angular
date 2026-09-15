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
import com.getcapacitor.JSObject
import com.getcapacitor.Plugin
import com.getcapacitor.PluginCall
import com.getcapacitor.PluginMethod
import com.getcapacitor.annotation.CapacitorPlugin
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.io.ByteArrayOutputStream

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
//   monitorAutotune=true  → PsolaProcessor (formants préservés, moteur PSOLA+LPC maison —
//                            voir docs/roadmap.md, remplace Rubber Band GPL-3.0 et TarsosDSP)
//
// Architecture monitoring — DEUX chemins, choisis à chaque [start] :
//
//   1. Chemin RAPIDE (PsolaAudioEngine, voir ce fichier) : API 26+, MMAP exclusif accepté par
//      l'appareil. Capture, YIN et PSOLA tournent entièrement dans des callbacks natifs AAudio
//      (aaudio_engine.c) — cette classe ne fait que sonder le statut (~20ms) et drainer le PCM
//      enregistré. Latence structurelle la plus basse (voir docs/roadmap.md).
//   2. Chemin de REPLI [AudioCaptureLoop] (AudioRecord maison, remplace TarsosDSP) — utilisé si
//      `PsolaAudioEngine.create` retourne `null` (API<26, MMAP refusé, etc.) :
//       └── onBlock(floats, bytes):
//               bytes  → enregistrement PCM brut (toujours)
//               floats → PsolaProcessor.process() → retrieve() → Int16 → AudioTrack
//               floats → fenêtre glissante YinPitchDetector (2048 échantillons,
//                         DÉCOUPLÉE de la taille de bloc de capture — voir plus bas)
//      La correction s'applique AU BLOC SUIVANT (1 frame de délai = 23 ms @ 44.1 kHz).
//
// Le chemin rapide n'a PAS de reverb câblée (limitation assumée, voir docs/roadmap.md) — le
// chemin de repli conserve la reverb PresetReverb existante.

class AudioRecordingSession(private val opts: RecordingOptions, private val context: Context) {

    var onLevel:       ((Float) -> Unit)? = null
    var onPitch:       ((Float, Float) -> Unit)? = null
    var onInterrupted: (() -> Unit)? = null

    private val SAMPLE_RATE = 44_100

    // 1024 samples @ 44.1 kHz — taille de bloc de capture quand le monitoring tourne (faible
    // latence). Sans monitoring, on utilise le minimum AudioRecord (throughput, pas latence).
    private val MONITOR_FRAME  = 1024
    private val STANDARD_FRAME = AudioCaptureLoop.minBufferSizeSamples(SAMPLE_RATE)

    // Fenêtre de détection YIN — DÉCOUPLÉE de la taille de bloc de capture (contrairement à
    // l'ancien code TarsosDSP, qui appelait PitchProcessor directement sur le bloc de capture
    // : avec MONITOR_FRAME=1024, half=512 → plancher réel ~86Hz, pas 80Hz). 2048 échantillons
    // (comme iOS, YINDetector.swift) retrouve le vrai plancher 80Hz — voix graves incluses.
    // Maintenue comme buffer circulaire, alimenté à chaque bloc quelle que soit sa taille.
    private val PITCH_FRAME_SIZE = 2048
    private val pitchRing = FloatArray(PITCH_FRAME_SIZE)
    private var pitchRingWritePos = 0L

    private val yinDetector = YinPitchDetector(
        frameSize = PITCH_FRAME_SIZE, minFrequency = 80f, maxFrequency = 1_200f,
    )

    private val scale: FloatArray = ScaleBuilder.buildScaleHz(opts.trackKey)
    private val pcmBuffer          = ByteArrayOutputStream()
    private var captureLoop: AudioCaptureLoop? = null
    private var outputTrack: AudioTrack?       = null
    private var psola: PsolaProcessor?         = null
    private var reverb: PresetReverb?          = null
    private var job: Job?                      = null

    // Chemin rapide (voir PsolaAudioEngine.kt) — non-null seulement si `PsolaAudioEngine.create`
    // a réussi ; dans ce cas captureLoop/outputTrack/psola/reverb restent tous null, le moteur
    // natif gère capture+monitoring+correction en interne.
    private var aaudioEngine: PsolaAudioEngine? = null
    private val drainBuf = FloatArray(4096)
    private val AAUDIO_POLL_INTERVAL_MS = 20L

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
        smoothedSemitones  = 0f
        pitchRingWritePos  = 0L

        val engine = PsolaAudioEngine.create(
            sampleRate      = SAMPLE_RATE,
            useMonitor      = opts.useMonitor,
            monitorAutotune = opts.monitorAutotune,
            voiceGain       = opts.voiceGain,
        )
        if (engine != null) {
            aaudioEngine = engine
            startFastPath(engine)
        } else {
            startFallbackPath()
        }

        // ── AudioFocus / casque (communs aux deux chemins) ─────────────────────
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
    }

    // ── Chemin rapide : moteur AAudio natif ───────────────────────────────────
    //
    // Capture, détection YIN et correction PSOLA tournent entièrement côté natif
    // (aaudio_engine.c) — cette coroutine ne fait que sonder le statut (~20ms, hors du chemin
    // chaud), appliquer la correction musicale existante (PitchCorrectionEngine + smoothing,
    // inchangée) et drainer le PCM brut capturé pour l'enregistrement. Aucune reverb sur ce
    // chemin (voir docs/roadmap.md — limitation assumée, n'affecte que l'esthétique du
    // monitoring, jamais la latence ni la justesse).
    private fun startFastPath(engine: PsolaAudioEngine) {
        job = CoroutineScope(Dispatchers.IO).launch {
            while (isActive) {
                val status = engine.pollStatus()
                onLevel?.invoke(status.level)

                if (!status.pitchHz.isNaN()) {
                    val hz = status.pitchHz
                    val nearest = PitchCorrectionEngine.findNearestNote(hz, scale)
                    if (nearest != null) {
                        val rawSemitones = PitchCorrectionEngine.correctionSemitones(hz, nearest)

                        if (opts.monitorAutotune && opts.useMonitor) {
                            smoothedSemitones = opts.smoothK * smoothedSemitones +
                                                (1 - opts.smoothK) * rawSemitones
                            val clamped = smoothedSemitones.coerceIn(-MONITOR_CAP, MONITOR_CAP)

                            // Communiquer la correction au moteur natif (atomic côté Rust) —
                            // appliquée au prochain callback d'entrée.
                            engine.setPitchCents(clamped * 100f)
                            onPitch?.invoke(hz, clamped)
                        } else {
                            onPitch?.invoke(hz, rawSemitones)
                        }
                    }
                }

                drainInto(engine)

                if (status.interrupted) {
                    onInterrupted?.invoke()
                }

                delay(AAUDIO_POLL_INTERVAL_MS)
            }
        }
    }

    /** Vide le ring natif de PCM enregistré dans [pcmBuffer], en boucle tant que le ring rendait
     *  un buffer plein (il pourrait en rester plus qu'un [drainBuf] si le polling a du retard). */
    private fun drainInto(engine: PsolaAudioEngine) {
        var drained: Int
        do {
            drained = engine.drainRecorded(drainBuf)
            if (drained > 0) pcmBuffer.write(floatsToInt16(drainBuf, drained, 1.0f))
        } while (drained == drainBuf.size)
    }

    // ── Chemin de repli : AudioCaptureLoop (AudioRecord/AudioTrack maison) ────────────────────
    private fun startFallbackPath() {
        val bufferSize = if (opts.monitorAutotune) MONITOR_FRAME else STANDARD_FRAME

        // ── AudioTrack + PsolaProcessor (avant la boucle de capture : onBlock en a besoin) ─
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

            // Créer le moteur PSOLA uniquement pour le monitoring avec autotune
            if (opts.monitorAutotune) {
                psola = PsolaProcessor(SAMPLE_RATE)
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

        // ── Boucle de capture ──────────────────────────────────────────────────
        val loop = AudioCaptureLoop(SAMPLE_RATE, bufferSize) { floats, bytes, byteCount ->
            // Toujours enregistrer les octets bruts (audio non traité → serveur)
            pcmBuffer.write(bytes, 0, byteCount)
            onLevel?.invoke(computeRms(floats))

            if (opts.useMonitor) {
                if (opts.monitorAutotune) {
                    // Passer par le moteur PSOLA pour le monitoring avec autotune
                    psola?.process(floats)
                    val available = psola?.available() ?: 0
                    if (available > 0) {
                        val out = FloatArray(available)
                        psola?.retrieve(out)
                        outputTrack?.write(floatsToInt16(out, available, opts.voiceGain), 0, available * 2)
                    }
                } else {
                    // Monitoring simple : volume direct, pas de pitch shift
                    outputTrack?.write(applyGain(bytes, byteCount, opts.voiceGain), 0, byteCount)
                }
            }

            // ── Détection de hauteur YIN (fenêtre glissante, découplée du bloc) ────
            appendToPitchRing(floats)
            if (pitchRingWritePos >= PITCH_FRAME_SIZE) {
                val hz = yinDetector.detect(extractPitchFrame(), SAMPLE_RATE.toFloat())
                if (hz != null) {
                    val nearest = PitchCorrectionEngine.findNearestNote(hz, scale)
                    if (nearest != null) {
                        val rawSemitones = PitchCorrectionEngine.correctionSemitones(hz, nearest)

                        if (opts.monitorAutotune && opts.useMonitor) {
                            smoothedSemitones = opts.smoothK * smoothedSemitones +
                                                (1 - opts.smoothK) * rawSemitones
                            val clamped = smoothedSemitones.coerceIn(-MONITOR_CAP, MONITOR_CAP)

                            // Communiquer la correction au moteur PSOLA (thread-safe).
                            // Elle sera appliquée au prochain bloc process() (délai 1 frame).
                            psola?.setPitchCents(clamped * 100f)
                            onPitch?.invoke(hz, clamped)
                        } else {
                            onPitch?.invoke(hz, rawSemitones)
                        }
                    }
                }
            }
        }
        captureLoop = loop
        loop.start()

        job = CoroutineScope(Dispatchers.IO).launch { loop.run() }
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

        job?.cancel()
        captureLoop?.stop()
        psola?.close()
        psola = null
        reverb?.release()
        reverb = null
        outputTrack?.stop()
        outputTrack?.release()
        outputTrack = null
        captureLoop = null

        // Chemin rapide : la coroutine de polling vient d'être annulée (job?.cancel() ci-dessus)
        // mais n'a pas forcément eu le temps de vider le ring natif avant sa dernière itération
        // — un dernier drain synchrone évite de perdre la fin de l'enregistrement.
        aaudioEngine?.let { engine ->
            drainInto(engine)
            engine.close()
        }
        aaudioEngine = null

        return SessionResult(pcmBuffer.toByteArray(), SAMPLE_RATE)
    }

    // ── Fenêtre glissante YIN (buffer circulaire) ─────────────────────────────

    private fun appendToPitchRing(floats: FloatArray) {
        for (s in floats) {
            pitchRing[(pitchRingWritePos % PITCH_FRAME_SIZE).toInt()] = s
            pitchRingWritePos++
        }
    }

    /** Linéarise le buffer circulaire en une trame contiguë (plus ancien → plus récent),
     *  pour l'API de [YinPitchDetector.detect]. À appeler seulement une fois
     *  `pitchRingWritePos >= PITCH_FRAME_SIZE`. */
    private fun extractPitchFrame(): FloatArray {
        val frame = FloatArray(PITCH_FRAME_SIZE)
        val oldest = (pitchRingWritePos % PITCH_FRAME_SIZE).toInt()
        for (i in 0 until PITCH_FRAME_SIZE) {
            frame[i] = pitchRing[(oldest + i) % PITCH_FRAME_SIZE]
        }
        return frame
    }

    // ── PCM conversions ───────────────────────────────────────────────────────

    // Float32 [-1,1] → Int16 little-endian bytes, with gain. `count` <= samples.size — permet
    // d'appeler avec un buffer réutilisé (drainBuf) partiellement rempli, sans réallocation.
    private fun floatsToInt16(samples: FloatArray, count: Int, gain: Float): ByteArray {
        val out = ByteArray(count * 2)
        for (i in 0 until count) {
            val s  = (samples[i] * gain * 32767f).toInt().coerceIn(-32_768, 32_767).toShort()
            out[i * 2]     = (s.toInt() and 0xFF).toByte()
            out[i * 2 + 1] = ((s.toInt() shr 8) and 0xFF).toByte()
        }
        return out
    }

    // Int16 little-endian bytes → gain applied in-place
    private fun applyGain(bytes: ByteArray, byteCount: Int, gain: Float): ByteArray {
        val out = ByteArray(byteCount)
        var i = 0
        while (i < byteCount - 1) {
            val sample = ((bytes[i + 1].toInt() shl 8) or (bytes[i].toInt() and 0xFF)).toShort()
            val scaled = (sample * gain).toInt().coerceIn(-32_768, 32_767).toShort()
            out[i]     = (scaled.toInt() and 0xFF).toByte()
            out[i + 1] = ((scaled.toInt() shr 8) and 0xFF).toByte()
            i += 2
        }
        return out
    }
}
