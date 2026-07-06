package net.laprod.app

import org.junit.Assert.*
import org.junit.Test
import kotlin.math.abs
import kotlin.math.log2

// ── PitchCorrectionEngineTest ──────────────────────────────────────────────────
//
// Exécutable avec : ./gradlew :app:test  (aucun émulateur requis)
// Pure JVM — pas de dépendance Android SDK.

class PitchCorrectionEngineTest {

    private val A4 = 440.0f
    private val E4 = 329.63f
    private val C4 = 261.63f

    // ── findNearestNote ────────────────────────────────────────────────────────

    @Test
    fun `findNearestNote returns exact match when in scale`() {
        val scale = floatArrayOf(C4, 329.63f, A4)
        val nearest = PitchCorrectionEngine.findNearestNote(A4, scale)
        assertNotNull(nearest)
        assertEquals(A4, nearest!!, 0.1f)
    }

    @Test
    fun `findNearestNote returns closest by semitones not by Hz`() {
        // G4 = 392 Hz, A4 = 440 Hz. Note détectée = 410 Hz
        // 410→392 = ~0.79 semitones, 410→440 = ~1.17 semitones → G4 est plus proche
        val scale   = floatArrayOf(392.0f, A4)
        val nearest = PitchCorrectionEngine.findNearestNote(410.0f, scale)
        assertNotNull(nearest)
        assertEquals(392.0f, nearest!!, 0.1f)
    }

    @Test
    fun `findNearestNote returns null on empty scale`() {
        assertNull(PitchCorrectionEngine.findNearestNote(A4, floatArrayOf()))
    }

    @Test
    fun `findNearestNote returns null on non-positive frequency`() {
        val scale = floatArrayOf(A4)
        assertNull(PitchCorrectionEngine.findNearestNote(0f, scale))
        assertNull(PitchCorrectionEngine.findNearestNote(-10f, scale))
    }

    @Test
    fun `findNearestNote with single element scale`() {
        val scale = floatArrayOf(A4)
        assertEquals(A4, PitchCorrectionEngine.findNearestNote(430.0f, scale)!!, 0.1f)
    }

    @Test
    fun `findNearestNote uses log2 distance not linear Hz`() {
        // A3 = 220 Hz, A4 = 440 Hz, A5 = 880 Hz
        // Note détectée = 460 Hz : plus proche de A4 (440) que de A5 (880) en semitones
        val scale   = floatArrayOf(220.0f, A4, 880.0f)
        val nearest = PitchCorrectionEngine.findNearestNote(460.0f, scale)
        assertEquals(A4, nearest!!, 0.1f)
    }

    // ── correctionSemitones ────────────────────────────────────────────────────

    @Test
    fun `correction is zero when on target`() {
        val correction = PitchCorrectionEngine.correctionSemitones(A4, A4)
        assertEquals(0.0f, correction, 0.001f)
    }

    @Test
    fun `correction is positive when detected is too low`() {
        // Voix détectée à 420 Hz, cible 440 Hz → voix trop basse → correction positive
        val correction = PitchCorrectionEngine.correctionSemitones(420.0f, A4)
        assertTrue("Correction attendue positive, got $correction", correction > 0)
    }

    @Test
    fun `correction is negative when detected is too high`() {
        // Voix détectée à 460 Hz, cible 440 Hz → voix trop haute → correction négative
        val correction = PitchCorrectionEngine.correctionSemitones(460.0f, A4)
        assertTrue("Correction attendue négative, got $correction", correction < 0)
    }

    @Test
    fun `correction is clamped to MAX_SEMITONE_SHIFT`() {
        // 300 Hz → 440 Hz = ~6.6 semitones → dépasse la limite → clampé à 3
        val correction = PitchCorrectionEngine.correctionSemitones(300.0f, A4)
        assertEquals(PitchCorrectionEngine.MAX_SEMITONE_SHIFT, correction, 0.001f)
    }

    @Test
    fun `correction is clamped negatively to -MAX_SEMITONE_SHIFT`() {
        // 600 Hz → 440 Hz = ~-5.4 semitones → clampé à -3
        val correction = PitchCorrectionEngine.correctionSemitones(600.0f, A4)
        assertEquals(-PitchCorrectionEngine.MAX_SEMITONE_SHIFT, correction, 0.001f)
    }

    @Test
    fun `correction value is accurate for small shift`() {
        // A4 = 440 Hz, A4+1semitone ≈ 466.16 Hz
        val oneUp   = (A4 * 2f.pow(1f / 12f))
        val expected = -1.0f                                  // détecté trop haut d'1 semitone
        val actual   = PitchCorrectionEngine.correctionSemitones(oneUp, A4)
        assertEquals(expected, actual, 0.05f)
    }

    @Test
    fun `MAX_SEMITONE_SHIFT is 3`() {
        assertEquals(3.0f, PitchCorrectionEngine.MAX_SEMITONE_SHIFT, 0.001f)
    }

    // ── semitonesToRatio ───────────────────────────────────────────────────────

    @Test
    fun `zero semitones gives ratio 1`() {
        assertEquals(1.0, PitchCorrectionEngine.semitonesToRatio(0f), 0.0001)
    }

    @Test
    fun `12 semitones gives ratio 2`() {
        assertEquals(2.0, PitchCorrectionEngine.semitonesToRatio(12f), 0.001)
    }

    @Test
    fun `minus 12 semitones gives ratio 0_5`() {
        assertEquals(0.5, PitchCorrectionEngine.semitonesToRatio(-12f), 0.001)
    }

    @Test
    fun `1 semitone ratio is correct`() {
        // 2^(1/12) ≈ 1.05946
        assertEquals(1.05946, PitchCorrectionEngine.semitonesToRatio(1f), 0.0001)
    }

    @Test
    fun `semitonesToRatio is monotonically increasing`() {
        val ratios = listOf(-6f, -3f, 0f, 3f, 6f)
            .map { PitchCorrectionEngine.semitonesToRatio(it) }
        for (i in 0 until ratios.size - 1) {
            assertTrue("Ratio non monotone à index $i", ratios[i] < ratios[i + 1])
        }
    }

    // ── Intégration ScaleBuilder + PitchCorrectionEngine ─────────────────────

    @Test
    fun `correction from scale rounds A4 to nearest scale note`() {
        val scale   = ScaleBuilder.buildScaleHz("A major")
        val nearest = PitchCorrectionEngine.findNearestNote(A4, scale)
        assertNotNull(nearest)
        // A4 est dans A major → la note la plus proche doit être 440 Hz
        assertEquals(A4, nearest!!, 0.1f)
        // La correction doit être ~0
        val correction = PitchCorrectionEngine.correctionSemitones(A4, nearest)
        assertEquals(0.0f, correction, 0.05f)
    }

    @Test
    fun `correction from scale for note slightly off`() {
        val scale     = ScaleBuilder.buildScaleHz("C major")
        val detected  = 263.0f                               // légèrement au-dessus de C4 (261.63 Hz)
        val nearest   = PitchCorrectionEngine.findNearestNote(detected, scale)
        assertNotNull(nearest)
        // La note la plus proche doit être C4
        assertEquals(C4, nearest!!, 1.0f)
        val correction = PitchCorrectionEngine.correctionSemitones(detected, nearest!!)
        // Correction doit être légèrement négative (voix trop haute)
        assertTrue("Correction doit être négative, got $correction", correction < 0)
        assertTrue("Correction doit être petite (< 0.5 semitone)", abs(correction) < 0.5f)
    }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

private fun Float.pow(exp: Float): Float = Math.pow(this.toDouble(), exp.toDouble()).toFloat()
