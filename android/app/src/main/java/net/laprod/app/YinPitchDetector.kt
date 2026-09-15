package net.laprod.app

import kotlin.math.abs
import kotlin.math.ceil
import kotlin.math.floor

/**
 * Détecteur de hauteur YIN — port Kotlin fidèle de `ios/App/App/YINDetector.swift`.
 *
 * Référence : de Cheveigné & Kawahara, "YIN, a fundamental frequency estimator for speech and
 * music", J. Acoust. Soc. Am. 111(4), 2002.
 *
 * Remplace `be.tarsos.dsp.pitch.PitchProcessor(YIN, ...)` (TarsosDSP, GPL-3.0) — voir
 * docs/roadmap.md. Contrairement à la version Swift (qui porte aussi `correctionSemitones`),
 * ce port n'expose que [detect] : la logique de correction musicale vit déjà côté Android
 * dans [PitchCorrectionEngine] (pure, déjà testée), pas dupliquée ici.
 *
 * Buffers pré-alloués à la construction — zéro allocation dans [detect], cohérent avec le
 * reste du pipeline temps réel (voir `AudioCaptureLoop`).
 */
class YinPitchDetector(
    private val frameSize: Int = 2048,
    private val threshold: Float = 0.14f,
    private val minFrequency: Float = 80.0f,
    private val maxFrequency: Float = 1_200.0f,
) {
    private val half = frameSize / 2
    private val diff = FloatArray(half)
    private val cmnd = FloatArray(half)

    /**
     * Détecte la fréquence fondamentale dans `frame` (exactement [frameSize] échantillons
     * PCM Float32 mono). Retourne `null` si non détectée.
     */
    fun detect(frame: FloatArray, sampleRate: Float): Float? {
        require(frame.size == frameSize) {
            "YinPitchDetector: frame.size (${frame.size}) != frameSize ($frameSize)"
        }

        // ── Étape 1 : Fonction de différence ────────────────────────────────────
        // d(τ) = Σ_{j=0}^{W-1} (x[j] - x[j+τ])²
        diff[0] = 0f
        for (tau in 1 until half) {
            var sum = 0f
            val w = frameSize - tau
            for (j in 0 until w) {
                val delta = frame[j + tau] - frame[j]
                sum += delta * delta
            }
            diff[tau] = sum
        }

        // ── Étape 2 : CMND (Cumulative Mean Normalised Difference) ─────────────
        cmnd[0] = 1.0f
        var runningSum = 0f
        for (tau in 1 until half) {
            runningSum += diff[tau]
            cmnd[tau] = if (runningSum > 0f) diff[tau] * tau / runningSum else 1.0f
        }

        // ── Étape 3 : Premier minimum local sous le seuil ───────────────────────
        val tauMin = ceil(sampleRate / maxFrequency).toInt()
        val tauMax = floor(sampleRate / minFrequency).toInt()
        if (tauMax >= half) return null

        var tau = maxOf(2, tauMin)
        val upper = minOf(half - 1, tauMax + 1)
        while (tau < upper) {
            if (cmnd[tau] < threshold && cmnd[tau] < cmnd[tau - 1] && cmnd[tau] <= cmnd[tau + 1]) {
                // ── Étape 4 : Interpolation parabolique (précision sub-échantillon) ──
                val s0 = cmnd[tau - 1]
                val s1 = cmnd[tau]
                val s2 = cmnd[tau + 1]
                val denom = 2 * (2 * s1 - s0 - s2)
                val tauRefined = if (abs(denom) > 1e-6f) tau + (s0 - s2) / denom else tau.toFloat()

                val hz = sampleRate / tauRefined
                if (hz in minFrequency..maxFrequency) return hz
            }
            tau++
        }
        return null
    }
}
