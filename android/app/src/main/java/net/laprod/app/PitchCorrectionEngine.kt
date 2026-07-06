package net.laprod.app

import kotlin.math.abs
import kotlin.math.log2
import kotlin.math.max
import kotlin.math.min

/**
 * Calculs de correction de hauteur pure — sans dépendance Android.
 *
 * Exposé comme `object` (singleton sans état) pour que chaque méthode
 * soit testable en isolation sans mocking.
 */
object PitchCorrectionEngine {

    /** Correction maximale appliquée (semitones). Au-delà = erreur de détection. */
    const val MAX_SEMITONE_SHIFT = 3.0f

    /**
     * Note cible la plus proche de `detectedHz` dans `scale`.
     * Distance mesurée en semitones (log₂), pas en Hz.
     *
     * @return fréquence cible en Hz, ou `null` si `scale` est vide.
     */
    fun findNearestNote(detectedHz: Float, scale: FloatArray): Float? {
        if (scale.isEmpty() || detectedHz <= 0f) return null
        return scale.minByOrNull { abs(log2(it / detectedHz)) }
    }

    /**
     * Correction en semitones pour amener `detectedHz` vers `targetHz`.
     * Clampée à ±[MAX_SEMITONE_SHIFT].
     *
     * Convention : positif = détecté trop bas (il faut monter), négatif = trop haut.
     */
    fun correctionSemitones(detectedHz: Float, targetHz: Float): Float {
        val raw = (12 * log2(targetHz / detectedHz)).toFloat()
        return max(-MAX_SEMITONE_SHIFT, min(MAX_SEMITONE_SHIFT, raw))
    }

    /**
     * Ratio de transposition WSOLA correspondant à `semitones`.
     * Utilisé pour configurer le pitch-shifter Android.
     */
    fun semitonesToRatio(semitones: Float): Double =
        2.0.pow(semitones.toDouble() / 12.0)

    // ─────────────────────────────────────────────────────────────────────────

    private fun Double.pow(exp: Double) = Math.pow(this, exp)
}
