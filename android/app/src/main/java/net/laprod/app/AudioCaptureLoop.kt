package net.laprod.app

import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import kotlin.math.sqrt

// ── Conversions PCM — fonctions pures top-level ─────────────────────────────────
//
// Séparées de la classe AudioCaptureLoop pour rester testables en JVM pur, sans dépendance
// Android SDK (voir docs/roadmap.md, pattern déjà utilisé par PitchCorrectionEngine/
// ScaleBuilder). Remplacent l'équivalent implicite que fournissait TarsosDSP's AudioEvent.

/**
 * Convertit `len` octets PCM 16-bit little-endian en float32 `[-1, 1]`.
 * `len` doit être pair (un échantillon = 2 octets) ; le dernier octet impair est ignoré.
 */
fun pcm16BytesToFloats(bytes: ByteArray, len: Int): FloatArray {
    val sampleCount = len / 2
    val out = FloatArray(sampleCount)
    for (i in 0 until sampleCount) {
        val lo = bytes[i * 2].toInt() and 0xFF
        val hi = bytes[i * 2 + 1].toInt()
        val sample = (hi shl 8) or lo
        out[i] = sample / 32768.0f
    }
    return out
}

/** RMS (Root Mean Square) d'un buffer float — mesure de niveau, comme `AudioEvent.getRMS()`. */
fun computeRms(samples: FloatArray, count: Int = samples.size): Float {
    if (count == 0) return 0f
    var sumSquares = 0.0
    for (i in 0 until count) sumSquares += samples[i].toDouble() * samples[i].toDouble()
    return sqrt(sumSquares / count).toFloat()
}

// ── AudioCaptureLoop ─────────────────────────────────────────────────────────────
//
// Remplace `be.tarsos.dsp.AudioDispatcher`/`AudioDispatcherFactory` (TarsosDSP, GPL-3.0) —
// voir docs/roadmap.md. Boucle de capture `AudioRecord` maison : lit des blocs de
// [bufferSizeSamples] échantillons en continu et invoque [onBlock] pour chacun, avec à la
// fois la représentation brute (octets PCM16, pour l'enregistrement tel quel) et convertie
// (float32, pour le traitement DSP) — miroir de ce que fournissait `AudioEvent` côté
// TarsosDSP (`byteBuffer`/`floatBuffer`).
//
// Thread model : [start] configure `AudioRecord` (thread appelant, ex. le thread principal du
// plugin Capacitor) ; [run] est une boucle BLOQUANTE à appeler depuis un thread/coroutine dédié
// (miroir exact de l'ancien `dispatcher!!.run()`) ; [stop] est thread-safe (appelable depuis un
// autre thread pour interrompre [run]).
class AudioCaptureLoop(
    private val sampleRate: Int,
    private val bufferSizeSamples: Int,
    private val onBlock: (floatBuffer: FloatArray, byteBuffer: ByteArray, byteCount: Int) -> Unit,
) {
    private var audioRecord: AudioRecord? = null

    @Volatile
    private var running = false

    /** Taille de buffer minimale requise par `AudioRecord` pour cette config — utilitaire
     *  exposé pour reproduire `AudioRecord.getMinBufferSize(...)` côté appelant (ancien
     *  `STANDARD_FRAME`), sans dupliquer la config `CHANNEL_IN_MONO`/`ENCODING_PCM_16BIT`. */
    companion object {
        fun minBufferSizeSamples(sampleRate: Int): Int {
            val bytes = AudioRecord.getMinBufferSize(
                sampleRate, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT,
            )
            return maxOf(bytes / 2, 1)
        }
    }

    /** Configure et démarre la capture. Ne bloque pas — la lecture se fait dans [run]. */
    fun start() {
        val bufferSizeBytes = bufferSizeSamples * 2 // 16-bit
        val minBufferBytes = AudioRecord.getMinBufferSize(
            sampleRate, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT,
        )
        val record = AudioRecord(
            MediaRecorder.AudioSource.VOICE_RECOGNITION,
            sampleRate,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
            maxOf(bufferSizeBytes, minBufferBytes),
        )
        audioRecord = record
        running = true
        record.startRecording()
    }

    /**
     * Boucle de lecture bloquante — à appeler depuis un thread/coroutine dédié
     * (`Dispatchers.IO`), jamais depuis le thread principal. Retourne quand [stop] est
     * appelé.
     */
    fun run() {
        val byteBuf = ByteArray(bufferSizeSamples * 2)
        val floatBuf = FloatArray(bufferSizeSamples)
        val record = audioRecord ?: return

        while (running) {
            val bytesRead = record.read(byteBuf, 0, byteBuf.size)
            if (bytesRead <= 0) continue

            val samplesRead = bytesRead / 2
            val floats = if (samplesRead == bufferSizeSamples) {
                pcm16BytesToFloatsInto(byteBuf, bytesRead, floatBuf)
                floatBuf
            } else {
                // Bloc partiel (rare, ex. dernier read avant stop) : buffer dédié pour ne
                // pas exposer un floatBuf partiellement obsolète sur sa fin.
                pcm16BytesToFloats(byteBuf, bytesRead)
            }
            onBlock(floats, byteBuf, bytesRead)
        }
    }

    /** Arrête la boucle [run] et libère `AudioRecord`. Thread-safe. */
    fun stop() {
        running = false
        audioRecord?.let {
            try { it.stop() } catch (_: IllegalStateException) {}
            it.release()
        }
        audioRecord = null
    }
}

/** Variante de [pcm16BytesToFloats] écrivant dans un buffer pré-alloué — zéro allocation
 *  dans le chemin chaud de [AudioCaptureLoop.run] pour le cas courant (bloc plein). */
private fun pcm16BytesToFloatsInto(bytes: ByteArray, len: Int, out: FloatArray) {
    val sampleCount = len / 2
    for (i in 0 until sampleCount) {
        val lo = bytes[i * 2].toInt() and 0xFF
        val hi = bytes[i * 2 + 1].toInt()
        val sample = (hi shl 8) or lo
        out[i] = sample / 32768.0f
    }
}
