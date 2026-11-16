package net.laprod.app

import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.pow
import kotlin.math.sin
import kotlin.math.sqrt

// ── VoiceFx ───────────────────────────────────────────────────────────────────
//
// Chaîne voix du retour casque, miroir simplifié de la chaîne d'export
// (mobile-audio-processor.service.ts, _applyVocalChain) :
//   • "boue"     : 2 passe-haut Butterworth cascadés (24 dB/oct, Q 0.5412 / 1.3066)
//   • présence   : bosse en cloche 2,5 kHz, Q 1
//   • clarté     : plateau d'aigus 12 kHz
//   • volume     : gain linéaire de la piste
// La réverb n'est pas ici (PresetReverb côté repli, aucune sur le chemin AAudio).
//
// Les coefficients (formules RBJ "Audio EQ Cookbook") sont calculés UNE fois par
// changement de réglage, hors thread audio, puis :
//   • chemin AAudio : poussés au moteur C (aaudio_engine_set_voice_fx), qui les
//     applique dans son callback ;
//   • chemin de repli : appliqués par [process] dans la boucle de capture Kotlin.
//
// Disposition du tableau [coefficients] : 4 biquads × (b0, b1, b2, a1, a2) normalisés
// par a0, puis le volume — 21 floats (VOICE_FX_COEFS côté C).

class VoiceFx(private val sampleRate: Int) {

    data class Params(
        val lowCutHz:   Float = 150f,
        val presenceDb: Float = 3.5f,
        val clarityDb:  Float = 3.0f,
        val reverbWet:  Float = 0.12f,
        val volume:     Float = 1.0f,
    )

    @Volatile var params: Params = Params()
        private set

    /** Remplacé en bloc (référence volatile) : le thread audio ne voit jamais un tableau à moitié écrit. */
    @Volatile var coefficients: FloatArray = computeCoefficients(Params(), sampleRate)
        private set

    // État des 4 biquads (z1, z2) — chemin de repli uniquement, thread de capture seul.
    private val state = FloatArray(BIQUADS * 2)

    fun update(p: Params) {
        params       = p
        coefficients = computeCoefficients(p, sampleRate)
    }

    /** Applique la chaîne en place sur `buf[0 until count]` (forme directe II transposée). */
    fun process(buf: FloatArray, count: Int) {
        val c = coefficients
        for (b in 0 until BIQUADS) {
            val o = b * 5
            val b0 = c[o]; val b1 = c[o + 1]; val b2 = c[o + 2]; val a1 = c[o + 3]; val a2 = c[o + 4]
            var z1 = state[b * 2]; var z2 = state[b * 2 + 1]
            for (i in 0 until count) {
                val x = buf[i]
                val y = b0 * x + z1
                z1 = b1 * x - a1 * y + z2
                z2 = b2 * x - a2 * y
                buf[i] = y
            }
            state[b * 2] = z1; state[b * 2 + 1] = z2
        }
        val vol = c[BIQUADS * 5]
        if (vol != 1f) for (i in 0 until count) buf[i] *= vol
    }

    companion object {
        const val BIQUADS = 4
        const val COEF_COUNT = BIQUADS * 5 + 1

        private const val HPF_Q1        = 0.5412
        private const val HPF_Q2        = 1.3066
        private const val PRESENCE_FREQ = 2_500.0
        private const val PRESENCE_Q    = 1.0
        private const val AIR_FREQ      = 12_000.0

        fun computeCoefficients(p: Params, sampleRate: Int): FloatArray {
            val out    = FloatArray(COEF_COUNT)
            val lowCut = p.lowCutHz.toDouble().coerceIn(20.0, 400.0)
            highPass(lowCut, HPF_Q1, sampleRate, out, 0)
            highPass(lowCut, HPF_Q2, sampleRate, out, 5)
            peaking(PRESENCE_FREQ, PRESENCE_Q, p.presenceDb.toDouble().coerceIn(-12.0, 12.0), sampleRate, out, 10)
            highShelf(minOf(AIR_FREQ, sampleRate * 0.45), p.clarityDb.toDouble().coerceIn(-12.0, 12.0), sampleRate, out, 15)
            out[BIQUADS * 5] = p.volume.coerceIn(0f, 2f)
            return out
        }

        private fun store(out: FloatArray, o: Int, b0: Double, b1: Double, b2: Double,
                          a0: Double, a1: Double, a2: Double) {
            out[o]     = (b0 / a0).toFloat()
            out[o + 1] = (b1 / a0).toFloat()
            out[o + 2] = (b2 / a0).toFloat()
            out[o + 3] = (a1 / a0).toFloat()
            out[o + 4] = (a2 / a0).toFloat()
        }

        private fun highPass(f: Double, q: Double, sr: Int, out: FloatArray, o: Int) {
            val w = 2 * PI * f / sr
            val cw = cos(w); val alpha = sin(w) / (2 * q)
            store(out, o, (1 + cw) / 2, -(1 + cw), (1 + cw) / 2, 1 + alpha, -2 * cw, 1 - alpha)
        }

        private fun peaking(f: Double, q: Double, db: Double, sr: Int, out: FloatArray, o: Int) {
            val a = 10.0.pow(db / 40)
            val w = 2 * PI * f / sr
            val cw = cos(w); val alpha = sin(w) / (2 * q)
            store(out, o, 1 + alpha * a, -2 * cw, 1 - alpha * a, 1 + alpha / a, -2 * cw, 1 - alpha / a)
        }

        /** Plateau d'aigus, pente S = 1 (équivalent du BiquadFilter 'highshelf' WebAudio). */
        private fun highShelf(f: Double, db: Double, sr: Int, out: FloatArray, o: Int) {
            val a = 10.0.pow(db / 40)
            val w = 2 * PI * f / sr
            val cw = cos(w); val alpha = sin(w) / 2 * sqrt(2.0)
            val sa = 2 * sqrt(a) * alpha
            store(out, o,
                a * ((a + 1) + (a - 1) * cw + sa),
                -2 * a * ((a - 1) + (a + 1) * cw),
                a * ((a + 1) + (a - 1) * cw - sa),
                (a + 1) - (a - 1) * cw + sa,
                2 * ((a - 1) - (a + 1) * cw),
                (a + 1) - (a - 1) * cw - sa)
        }
    }
}
