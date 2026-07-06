package net.laprod.app

import kotlin.math.abs
import kotlin.math.log2
import kotlin.math.pow

/**
 * Construit les fréquences cibles d'une gamme musicale.
 *
 * Entrée : `"<note> <mode>"` ex. `"F# minor"`, `"Bb major"`, `"C major"`.
 * Sortie  : tableau de fréquences en Hz (80–1200 Hz, octaves 2–5), trié par ordre croissant.
 *
 * Toutes les méthodes sont pures → testabilité maximale sans Android SDK.
 */
object ScaleBuilder {

    // ── Chromatique ────────────────────────────────────────────────────────────

    private val CHROMATIC_INDEX: Map<String, Int> = mapOf(
        "C"  to  0, "B#" to  0,
        "C#" to  1, "Db" to  1,
        "D"  to  2,
        "D#" to  3, "Eb" to  3,
        "E"  to  4, "Fb" to  4,
        "F"  to  5, "E#" to  5,
        "F#" to  6, "Gb" to  6,
        "G"  to  7,
        "G#" to  8, "Ab" to  8,
        "A"  to  9,
        "A#" to 10, "Bb" to 10,
        "B"  to 11, "Cb" to 11,
    )

    private val MAJOR_INTERVALS = intArrayOf(0, 2, 4, 5, 7, 9, 11)
    private val MINOR_INTERVALS = intArrayOf(0, 2, 3, 5, 7, 8, 10)

    private const val FREQ_MIN = 80f
    private const val FREQ_MAX = 1_200f

    // ── API publique ───────────────────────────────────────────────────────────

    /**
     * Retourne les fréquences cibles pour une clé donnée.
     * @param key ex. "F# minor", "C major", "" → tableau vide.
     */
    fun buildScaleHz(key: String): FloatArray {
        val (rootIndex, intervals) = parse(key) ?: return FloatArray(0)

        val result = mutableListOf<Float>()
        for (octave in 2..5) {
            for (interval in intervals) {
                val midi = (octave + 1) * 12 + rootIndex + interval
                val hz   = (440.0 * 2.0.pow((midi - 69).toDouble() / 12.0)).toFloat()
                if (hz in FREQ_MIN..FREQ_MAX) result.add(hz)
            }
        }
        return result.toFloatArray().also { it.sort() }
    }

    // ── Parsing ────────────────────────────────────────────────────────────────

    /**
     * Parse la clé et retourne (rootIndex, intervalles), ou null si invalide.
     * Exposé interne pour les tests.
     */
    internal fun parse(key: String): Pair<Int, IntArray>? {
        val parts = key.trim().split(Regex("\\s+")).filter { it.isNotEmpty() }
        val noteName  = parts.firstOrNull() ?: return null
        val rootIndex = CHROMATIC_INDEX[noteName]  ?: return null
        val mode      = parts.drop(1).joinToString(" ").lowercase()
        val intervals = if ("min" in mode) MINOR_INTERVALS else MAJOR_INTERVALS
        return Pair(rootIndex, intervals)
    }
}
