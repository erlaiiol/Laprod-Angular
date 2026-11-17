package net.laprod.app

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioTimestamp
import android.media.AudioTrack
import java.io.File
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Mode Clip, Android : lecture du son du tournage (WAV 16 bits) avec ancre
 * d'horloge matérielle.
 *
 * Un <audio> WebView n'expose aucun timestamp exploitable (docs § 4.1.3) : le
 * son est joué ici, par AudioTrack, et getTimestamp() donne l'instant de
 * PRÉSENTATION de chaque frame en CLOCK_MONOTONIC — la latence de sortie
 * (y compris Bluetooth quand l'appareil la rapporte) est donc déjà incluse.
 */
class ClipAudioPlayer(private val file: File, private val delayMs: Long) {

    private var track: AudioTrack? = null
    private var thread: Thread? = null
    @Volatile private var running = false
    // Mesures d'ancre : les premières datent le DÉBUT de la lecture (ce qui cale le
    // clip), les dernières permettent de mesurer la dérive sur la durée (§ 4.3).
    private val firstAnchors = mutableListOf<Long>()
    private val lastAnchors = ArrayDeque<Long>()
    @Volatile private var playCalledNs = 0L
    private var sampleRate = 48_000

    /** Latence de sortie rapportée par l'appareil (hors démarrage de la piste), si lisible. */
    @Volatile private var reportedLatencyMs: Double? = null

    /**
     * AudioTrack.getLatency() (API cachée, stable depuis Android 4) = latence de sortie
     * rapportée + tampon de la piste. On retire le tampon : reste ce que l'appareil
     * annonce pour la route (Bluetooth compris s'il le rapporte). null si inaccessible —
     * on retombe alors sur (ancre − appel à play()), qui inclut aussi le démarrage.
     */
    private fun deviceLatencyMs(t: AudioTrack): Double? = runCatching {
        val total = (AudioTrack::class.java.getMethod("getLatency").invoke(t) as Int).toDouble()
        val bufferMs = t.bufferSizeInFrames * 1000.0 / sampleRate
        maxOf(0.0, total - bufferMs)
    }.getOrNull()

    data class Result(val anchorSec: Double, val reportedLatencyMs: Double, val driftMs: Double?)

    fun start() {
        val wav = WavInfo.read(file)
        sampleRate = wav.sampleRate
        val channelMask = if (wav.channels == 2) AudioFormat.CHANNEL_OUT_STEREO else AudioFormat.CHANNEL_OUT_MONO
        val minBuf = AudioTrack.getMinBufferSize(wav.sampleRate, channelMask, AudioFormat.ENCODING_PCM_16BIT)
        val t = AudioTrack.Builder()
            .setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_MEDIA)
                    .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC)
                    .build()
            )
            .setAudioFormat(
                AudioFormat.Builder()
                    .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                    .setSampleRate(wav.sampleRate)
                    .setChannelMask(channelMask)
                    .build()
            )
            .setBufferSizeInBytes(maxOf(minBuf * 4, 16_384))
            .setTransferMode(AudioTrack.MODE_STREAM)
            .build()
        track = t
        running = true
        val startAt = System.nanoTime() + delayMs * 1_000_000L

        thread = Thread({
            RandomAccessFile(file, "r").use { raf ->
                raf.seek(wav.dataOffset)
                val frameBytes = 2 * wav.channels
                val buf = ByteArray(frameBytes * 2048)
                // Pré-remplissage avant play() : le 1er échantillon part sans trou.
                var remaining = wav.dataLength
                val pre = raf.read(buf, 0, minOf(buf.size.toLong(), remaining).toInt())
                if (pre > 0) { t.write(buf, 0, pre); remaining -= pre }

                val wait = startAt - System.nanoTime()
                if (wait > 0) Thread.sleep(wait / 1_000_000L, (wait % 1_000_000L).toInt())
                if (!running) return@Thread
                playCalledNs = System.nanoTime()
                t.play()
                reportedLatencyMs = deviceLatencyMs(t)

                val ts = AudioTimestamp()
                var lastPoll = 0L
                while (running && remaining > 0) {
                    val n = raf.read(buf, 0, minOf(buf.size.toLong(), remaining).toInt())
                    if (n <= 0) break
                    t.write(buf, 0, n)
                    remaining -= n
                    val now = System.nanoTime()
                    if (now - lastPoll > 100_000_000L) {
                        lastPoll = now
                        if (t.getTimestamp(ts) && ts.framePosition > sampleRate / 10) {
                            val a = ClipSync.anchorNs(ts.framePosition, ts.nanoTime, sampleRate)
                            synchronized(lastAnchors) {
                                if (firstAnchors.size < ANCHOR_SAMPLES) firstAnchors.add(a)
                                lastAnchors.addLast(a)
                                if (lastAnchors.size > ANCHOR_SAMPLES) lastAnchors.removeFirst()
                            }
                        }
                    }
                }
            }
        }, "clip-audio").also { it.priority = Thread.MAX_PRIORITY; it.start() }
    }

    /**
     * Arrête la lecture. Ancre (s, monotonic) de la position 0 du fichier mesurée en
     * début de lecture, latence de sortie rapportée (ancre − appel à play()) et dérive
     * entre début et fin de lecture (ms), ou null si aucune mesure.
     */
    fun stop(): Result? {
        running = false
        thread?.join(500)
        track?.let { runCatching { it.pause(); it.flush(); it.stop() }; it.release() }
        track = null
        val (first, last) = synchronized(lastAnchors) {
            ClipSync.medianNs(firstAnchors.toList()) to ClipSync.medianNs(lastAnchors.toList())
        }
        first ?: return null
        val drift = if (last != null && lastAnchors.size >= ANCHOR_SAMPLES) (last - first) / 1e6 else null
        val reported = reportedLatencyMs ?: if (playCalledNs > 0) maxOf(0.0, (first - playCalledNs) / 1e6) else 0.0
        return Result(first / 1e9, reported, drift)
    }

    private companion object { const val ANCHOR_SAMPLES = 10 }
}

/** En-tête WAV PCM 16 bits (celui écrit par wav.utils.ts). */
data class WavInfo(val sampleRate: Int, val channels: Int, val dataOffset: Long, val dataLength: Long) {
    companion object {
        fun read(file: File): WavInfo {
            RandomAccessFile(file, "r").use { raf ->
                val head = ByteArray(12)
                raf.readFully(head)
                require(String(head, 0, 4) == "RIFF" && String(head, 8, 4) == "WAVE") { "WAV invalide" }
                var sr = 48_000
                var ch = 2
                while (raf.filePointer < raf.length()) {
                    val idBytes = ByteArray(4); raf.readFully(idBytes)
                    val sizeBytes = ByteArray(4); raf.readFully(sizeBytes)
                    val size = ByteBuffer.wrap(sizeBytes).order(ByteOrder.LITTLE_ENDIAN).int.toLong() and 0xffffffffL
                    when (String(idBytes)) {
                        "fmt " -> {
                            val fmt = ByteArray(size.toInt()); raf.readFully(fmt)
                            val bb = ByteBuffer.wrap(fmt).order(ByteOrder.LITTLE_ENDIAN)
                            ch = bb.getShort(2).toInt()
                            sr = bb.getInt(4)
                        }
                        "data" -> return WavInfo(sr, ch, raf.filePointer, minOf(size, raf.length() - raf.filePointer))
                        else -> raf.seek(raf.filePointer + size)
                    }
                }
                error("WAV sans données")
            }
        }
    }
}
