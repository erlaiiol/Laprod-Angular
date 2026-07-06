package net.laprod.app

import org.junit.Assert.*
import org.junit.Test
import kotlin.math.abs

// ── ScaleBuilderTest ──────────────────────────────────────────────────────────
//
// Exécutable avec : ./gradlew :app:test  (aucun émulateur requis)
// Pure JVM — pas de dépendance Android SDK.

class ScaleBuilderTest {

    // ── Parsing de la clé ─────────────────────────────────────────────────────

    @Test
    fun `C major parsed correctly`() {
        val result = ScaleBuilder.parse("C major")
        assertNotNull(result)
        assertEquals(0, result!!.first)                      // C = index 0
        assertArrayEquals(intArrayOf(0,2,4,5,7,9,11), result.second)
    }

    @Test
    fun `F# minor parsed correctly`() {
        val result = ScaleBuilder.parse("F# minor")
        assertNotNull(result)
        assertEquals(6, result!!.first)                      // F# = index 6
        assertArrayEquals(intArrayOf(0,2,3,5,7,8,10), result.second)
    }

    @Test
    fun `Bb major parsed correctly`() {
        val result = ScaleBuilder.parse("Bb major")
        assertNotNull(result)
        assertEquals(10, result!!.first)                     // Bb = A# = index 10
    }

    @Test
    fun `Cb enharmonic equals B natural`() {
        val cb = ScaleBuilder.parse("Cb major")
        val b  = ScaleBuilder.parse("B major")
        assertNotNull(cb); assertNotNull(b)
        assertEquals(cb!!.first, b!!.first)                  // Cb = B = index 11
    }

    @Test
    fun `B# enharmonic equals C`() {
        val bs = ScaleBuilder.parse("B# major")
        val c  = ScaleBuilder.parse("C major")
        assertNotNull(bs); assertNotNull(c)
        assertEquals(bs!!.first, c!!.first)                  // B# = C = index 0
    }

    @Test
    fun `empty key returns null`() {
        assertNull(ScaleBuilder.parse(""))
    }

    @Test
    fun `unknown note returns null`() {
        assertNull(ScaleBuilder.parse("Z major"))
    }

    @Test
    fun `missing mode defaults to major`() {
        val result = ScaleBuilder.parse("A")
        assertNotNull(result)
        assertArrayEquals(intArrayOf(0,2,4,5,7,9,11), result!!.second)
    }

    @Test
    fun `minor keyword is case-insensitive`() {
        val lower = ScaleBuilder.parse("D minor")
        val upper = ScaleBuilder.parse("D MINOR")
        assertNotNull(lower); assertNotNull(upper)
        assertArrayEquals(lower!!.second, upper!!.second)
    }

    // ── Contenu de la gamme ───────────────────────────────────────────────────

    @Test
    fun `all frequencies are within vocal range`() {
        val keys = listOf("C major", "F# minor", "Bb major", "G# minor", "Db major")
        for (key in keys) {
            val freqs = ScaleBuilder.buildScaleHz(key)
            for (f in freqs) {
                assertTrue("$key: $f Hz < 80 Hz",   f >= 80f)
                assertTrue("$key: $f Hz > 1200 Hz", f <= 1_200f)
            }
        }
    }

    @Test
    fun `frequencies are sorted ascending`() {
        val freqs = ScaleBuilder.buildScaleHz("E minor")
        val sorted = freqs.clone().also { it.sort() }
        assertArrayEquals(sorted, freqs, 0.001f)
    }

    @Test
    fun `A4 is 440 Hz in A major`() {
        val freqs = ScaleBuilder.buildScaleHz("A major")
        val a4 = freqs.minByOrNull { abs(it - 440f) }
        assertNotNull(a4)
        assertEquals(440f, a4!!, 0.1f)
    }

    @Test
    fun `empty key returns empty array`() {
        assertEquals(0, ScaleBuilder.buildScaleHz("").size)
    }

    @Test
    fun `C major and C minor are different`() {
        val major = ScaleBuilder.buildScaleHz("C major")
        val minor = ScaleBuilder.buildScaleHz("C minor")
        assertFalse("C major et C minor ne doivent pas être identiques",
            major.contentEquals(minor))
    }

    @Test
    fun `enharmonic equivalents produce identical frequencies`() {
        // F# major et Gb major sont enharmoniques
        val fSharp = ScaleBuilder.buildScaleHz("F# major")
        val gFlat  = ScaleBuilder.buildScaleHz("Gb major")
        assertEquals(fSharp.size, gFlat.size)
        for (i in fSharp.indices) {
            assertEquals("Note $i", fSharp[i], gFlat[i], 0.001f)
        }
    }

    @Test
    fun `C major does not contain F sharp`() {
        val freqs   = ScaleBuilder.buildScaleHz("C major")
        val fSharp4 = 369.99f
        val nearest = freqs.minByOrNull { abs(it - fSharp4) }!!
        // La note la plus proche en C major est soit F4 (349.23) soit G4 (392)
        assertTrue("F# semble être dans C major (distance ${abs(nearest - fSharp4)} Hz)",
            abs(nearest - fSharp4) > 10f)
    }

    @Test
    fun `C major contains C4 at 261 Hz`() {
        val freqs = ScaleBuilder.buildScaleHz("C major")
        val c4    = freqs.minByOrNull { abs(it - 261.63f) }
        assertNotNull(c4)
        assertEquals(261.63f, c4!!, 0.1f)
    }

    @Test
    fun `C major has reasonable number of notes`() {
        val freqs = ScaleBuilder.buildScaleHz("C major")
        // 7 notes × 4 octaves = 28 max, mais les limites Hz excluent certaines
        assertTrue("Trop peu de notes: ${freqs.size}", freqs.size >= 20)
        assertTrue("Trop de notes: ${freqs.size}",    freqs.size <= 28)
    }
}

// ── Extension pour assertArrayEquals Float ─────────────────────────────────────

private fun assertArrayEquals(expected: FloatArray, actual: FloatArray, delta: Float) {
    assertEquals("Taille différente", expected.size, actual.size)
    for (i in expected.indices) {
        assertEquals("Index $i", expected[i], actual[i], delta)
    }
}
