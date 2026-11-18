package net.laprod.app

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.ByteArrayOutputStream
import java.io.File
import java.nio.ByteBuffer

// Mode Clip : moov déplacé avant mdat, offsets de blocs décalés (docs § 4.1.4).
class Mp4FastStartTest {

    private fun atom(type: String, payload: ByteArray): ByteArray =
        ByteBuffer.allocate(8 + payload.size).putInt(8 + payload.size).put(type.toByteArray()).put(payload).array()

    private fun stco(vararg offsets: Int): ByteArray {
        val b = ByteBuffer.allocate(8 + offsets.size * 4).putInt(0).putInt(offsets.size)
        offsets.forEach { b.putInt(it) }
        return atom("stco", b.array())
    }

    private fun moov(chunkOffsets: IntArray): ByteArray =
        atom("moov", atom("trak", atom("mdia", atom("minf", atom("stbl", stco(*chunkOffsets))))))

    @Test
    fun movesMoovFirstAndShiftsChunkOffsets() {
        val ftyp = atom("ftyp", "isom".toByteArray())
        val mdat = atom("mdat", byteArrayOf(1, 2, 3, 4, 5, 6))
        val firstChunk = ftyp.size + 8              // données de mdat
        val moovAtEnd = moov(intArrayOf(firstChunk, firstChunk + 3))
        val src = File.createTempFile("clip", ".mp4")
        val dst = File.createTempFile("clip-fs", ".mp4")
        src.writeBytes(ByteArrayOutputStream().apply { write(ftyp); write(mdat); write(moovAtEnd) }.toByteArray())

        assertTrue(Mp4FastStart.apply(src, dst))
        val out = dst.readBytes()
        assertEquals("moov", String(out, ftyp.size + 4, 4))
        // stco : 2 entrées décalées de la taille de moov.
        val stcoData = ByteBuffer.wrap(out, ftyp.size + moovAtEnd.size - 8, 8)
        assertEquals(firstChunk + moovAtEnd.size, stcoData.getInt())
        assertEquals(firstChunk + 3 + moovAtEnd.size, stcoData.getInt())
        // Les données référencées sont bien à l'offset décalé.
        assertArrayEquals(byteArrayOf(1, 2, 3), out.copyOfRange(firstChunk + moovAtEnd.size, firstChunk + moovAtEnd.size + 3))
        assertEquals(src.length(), dst.length())
    }

    @Test
    fun alreadyFaststart_isLeftUntouched() {
        val ftyp = atom("ftyp", "isom".toByteArray())
        val src = File.createTempFile("clip", ".mp4")
        src.writeBytes(ftyp + moov(intArrayOf(100)) + atom("mdat", byteArrayOf(9)))
        assertFalse(Mp4FastStart.apply(src, File.createTempFile("clip-out", ".mp4")))
    }
}
