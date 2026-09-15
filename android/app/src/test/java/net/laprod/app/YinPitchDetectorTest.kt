package net.laprod.app

import org.junit.Assert.*
import org.junit.Test
import kotlin.math.PI
import kotlin.math.sin
import kotlin.random.Random

// ── YinPitchDetectorTest ─────────────────────────────────────────────────────────
//
// Miroir de ios/App/AppTests/YINDetectorTests.swift (uniquement detect() — la correction en
// demi-tons est couverte séparément par PitchCorrectionEngineTest, pas dupliquée ici).
// Exécutable avec : ./gradlew :app:test — aucun émulateur requis.

class YinPitchDetectorTest {

    private val sampleRate = 48_000.0f
    private val frameSize = 2048

    private fun sineWave(frequency: Float, amplitude: Float = 0.5f): FloatArray =
        FloatArray(frameSize) { i -> amplitude * sin(2.0 * PI * frequency * i / sampleRate).toFloat() }

    private fun silence(): FloatArray = FloatArray(frameSize) { 1e-7f }

    private fun whiteNoise(amplitude: Float = 0.5f, random: Random = Random(42)): FloatArray =
        FloatArray(frameSize) { random.nextFloat() * 2 * amplitude - amplitude }

    // ── Détection de sinus purs ────────────────────────────────────────────────

    @Test
    fun `detects A4 440Hz`() {
        val detector = YinPitchDetector(frameSize = frameSize)
        val hz = detector.detect(sineWave(440f), sampleRate)
        assertNotNull("YIN n'a pas détecté 440 Hz", hz)
        assertEquals(440f, hz!!, 5.0f)
    }

    @Test
    fun `detects E4 329Hz`() {
        val detector = YinPitchDetector(frameSize = frameSize)
        val hz = detector.detect(sineWave(329.63f), sampleRate)
        assertNotNull(hz)
        assertEquals(329.63f, hz!!, 5.0f)
    }

    @Test
    fun `detects low note G2 98Hz`() {
        val detector = YinPitchDetector(frameSize = frameSize)
        val hz = detector.detect(sineWave(98.0f), sampleRate)
        assertNotNull(hz)
        assertEquals(98.0f, hz!!, 3.0f)
    }

    @Test
    fun `detects high note E5 659Hz`() {
        val detector = YinPitchDetector(frameSize = frameSize)
        val hz = detector.detect(sineWave(659.25f), sampleRate)
        assertNotNull(hz)
        assertEquals(659.25f, hz!!, 8.0f)
    }

    // ── Signaux non-périodiques ────────────────────────────────────────────────

    @Test
    fun `returns null on silence`() {
        val detector = YinPitchDetector(frameSize = frameSize)
        val hz = detector.detect(silence(), sampleRate)
        assertNull("YIN ne doit pas détecter de hauteur dans le silence", hz)
    }

    @Test
    fun `returns null on white noise`() {
        val detector = YinPitchDetector(frameSize = frameSize, threshold = 0.10f)
        var foundCount = 0
        val random = Random(1234)
        repeat(10) {
            if (detector.detect(whiteNoise(random = random), sampleRate) != null) foundCount++
        }
        assertTrue(
            "YIN détecte de la hauteur dans le bruit blanc trop souvent ($foundCount/10)",
            foundCount <= 2,
        )
    }

    // ── Limites de fréquence ────────────────────────────────────────────────────

    @Test
    fun `frequency below min is rejected`() {
        val detector = YinPitchDetector(frameSize = frameSize, minFrequency = 80f, maxFrequency = 1_200f)
        val hz = detector.detect(sineWave(50.0f), sampleRate)
        assertNull("50 Hz est sous la limite minFrequency=80 Hz", hz)
    }

    @Test
    fun `pure tone far above max may alias to a sub-harmonic but never escapes the declared range`() {
        // Piège découvert en écrivant ce test, documenté ici pour ne pas le redécouvrir par
        // surprise plus tard : un sinus pur à F Hz est mathématiquement TOUJOURS aussi
        // périodique à 2×/3×/4×... sa propre période. Un YIN cherchant dans une plage qui
        // exclut la vraie période (ici [80,1200] pour F=1800) peut donc légitimement
        // accrocher un sous-multiple entier tombant dans la plage (1800/2=900Hz) — "l'erreur
        // d'octave", une propriété connue de TOUT détecteur par autocorrélation, pas un bug
        // de ce port. Vérifié empiriquement : ni changer la fréquence de test (1800→1837Hz)
        // ni ajouter du bruit de fond (3%) n'en changent l'issue pour cette configuration
        // (frameSize=2048, threshold=0.14) — l'alias est robuste, pas un artefact fragile
        // d'un choix de paramètres malheureux. Sans objet en pratique : la voix humaine ne
        // produit jamais de fondamentale proche de 1800 Hz (la plage réelle de l'app est
        // 70-1200 Hz, cf. `PitchMonitorPlugin.kt`) — ce que ce test vérifie donc est
        // l'invariant réellement garanti par construction : la valeur retournée, si elle
        // existe, reste TOUJOURS dans les bornes déclarées, jamais une extrapolation hors
        // plage. C'est le garde-fou qui protège l'app d'une correction de pitch absurde.
        val detector = YinPitchDetector(frameSize = frameSize, minFrequency = 80f, maxFrequency = 1_200f)
        val hz = detector.detect(sineWave(1_800.0f), sampleRate)
        if (hz != null) {
            assertTrue("valeur détectée $hz hors des bornes déclarées [80,1200]", hz in 80f..1_200f)
        }
    }

    // ── Voix masculines (frameSize=2048 nécessaire, cf. YINDetectorTests.swift) ──

    @Test
    fun `detects male voice E2 82Hz`() {
        val detector = YinPitchDetector(frameSize = frameSize, minFrequency = 70f, maxFrequency = 1_200f)
        val hz = detector.detect(sineWave(82.4f), sampleRate)
        assertNotNull("YIN doit détecter E2 (82 Hz) avec frameSize=2048", hz)
        assertEquals(82.4f, hz!!, 4.0f)
    }

    @Test
    fun `detects male voice A2 110Hz`() {
        val detector = YinPitchDetector(frameSize = frameSize)
        val hz = detector.detect(sineWave(110.0f), sampleRate)
        assertNotNull(hz)
        assertEquals(110.0f, hz!!, 4.0f)
    }

    @Test
    fun `detects male voice B2 123Hz`() {
        val detector = YinPitchDetector(frameSize = frameSize)
        val hz = detector.detect(sineWave(123.47f), sampleRate)
        assertNotNull(hz)
        assertEquals(123.47f, hz!!, 5.0f)
    }

    @Test
    fun `detects male voice D3 147Hz`() {
        val detector = YinPitchDetector(frameSize = frameSize)
        val hz = detector.detect(sineWave(146.83f), sampleRate)
        assertNotNull(hz)
        assertEquals(146.83f, hz!!, 5.0f)
    }

    // ── Précondition ────────────────────────────────────────────────────────────

    @Test(expected = IllegalArgumentException::class)
    fun `wrong frame size throws`() {
        val detector = YinPitchDetector(frameSize = 2048)
        detector.detect(FloatArray(512), sampleRate)
    }
}
