package net.laprod.app

import org.junit.Assert.*
import org.junit.Test
import kotlin.math.sqrt

// ── AudioCaptureLoopTest ─────────────────────────────────────────────────────────
//
// Teste uniquement les fonctions pures de conversion PCM (pas AudioRecord, qui exige un
// device/émulateur). Exécutable avec : ./gradlew :app:test

class AudioCaptureLoopTest {

    private fun int16LeBytes(vararg samples: Int): ByteArray {
        val out = ByteArray(samples.size * 2)
        for ((i, s) in samples.withIndex()) {
            out[i * 2] = (s and 0xFF).toByte()
            out[i * 2 + 1] = ((s shr 8) and 0xFF).toByte()
        }
        return out
    }

    @Test
    fun `pcm16BytesToFloats decodes zero as zero`() {
        val bytes = int16LeBytes(0)
        val floats = pcm16BytesToFloats(bytes, bytes.size)
        assertEquals(1, floats.size)
        assertEquals(0f, floats[0], 1e-6f)
    }

    @Test
    fun `pcm16BytesToFloats decodes max positive`() {
        val bytes = int16LeBytes(32_767)
        val floats = pcm16BytesToFloats(bytes, bytes.size)
        assertEquals(32_767f / 32_768f, floats[0], 1e-6f)
    }

    @Test
    fun `pcm16BytesToFloats decodes max negative`() {
        val bytes = int16LeBytes(-32_768)
        val floats = pcm16BytesToFloats(bytes, bytes.size)
        assertEquals(-1.0f, floats[0], 1e-6f)
    }

    @Test
    fun `pcm16BytesToFloats decodes negative one correctly (sign extension)`() {
        // Piège classique : l'octet de poids fort doit être signé (sign-extend), l'octet de
        // poids faible non-signé — sinon -1 (0xFFFF) se décode en tout sauf -1/32768.
        val bytes = int16LeBytes(-1)
        val floats = pcm16BytesToFloats(bytes, bytes.size)
        assertEquals(-1f / 32_768f, floats[0], 1e-6f)
    }

    @Test
    fun `pcm16BytesToFloats decodes multiple samples in order`() {
        val bytes = int16LeBytes(100, -100, 0, 16_384)
        val floats = pcm16BytesToFloats(bytes, bytes.size)
        assertEquals(4, floats.size)
        assertEquals(100f / 32_768f, floats[0], 1e-6f)
        assertEquals(-100f / 32_768f, floats[1], 1e-6f)
        assertEquals(0f, floats[2], 1e-6f)
        assertEquals(16_384f / 32_768f, floats[3], 1e-6f)
    }

    @Test
    fun `pcm16BytesToFloats ignores trailing odd byte`() {
        val bytes = int16LeBytes(1_000) + byteArrayOf(0x42)
        val floats = pcm16BytesToFloats(bytes, bytes.size)
        assertEquals(1, floats.size) // le dernier octet impair ne forme pas un échantillon complet
    }

    @Test
    fun `computeRms of silence is zero`() {
        val samples = FloatArray(100)
        assertEquals(0f, computeRms(samples), 1e-6f)
    }

    @Test
    fun `computeRms of constant amplitude matches that amplitude`() {
        val samples = FloatArray(100) { 0.5f }
        assertEquals(0.5f, computeRms(samples), 1e-5f)
    }

    @Test
    fun `computeRms of alternating plus-minus one is one`() {
        val samples = FloatArray(100) { if (it % 2 == 0) 1f else -1f }
        assertEquals(1f, computeRms(samples), 1e-5f)
    }

    @Test
    fun `computeRms respects explicit count over full buffer size`() {
        val samples = floatArrayOf(1f, 1f, 1f, 0f, 0f) // seuls les 3 premiers comptent
        assertEquals(1f, computeRms(samples, count = 3), 1e-5f)
    }

    @Test
    fun `computeRms matches manual sqrt-mean-square for mixed values`() {
        val samples = floatArrayOf(0.1f, 0.2f, 0.3f, 0.4f)
        val expected = sqrt(samples.map { it * it }.average()).toFloat()
        assertEquals(expected, computeRms(samples), 1e-5f)
    }
}
