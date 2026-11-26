package net.laprod.app

import java.io.File
import java.io.RandomAccessFile
import java.nio.ByteBuffer

/**
 * « Faststart » MP4 : place l'atome `moov` avant `mdat` (docs/roadmap.md § 4.1.4).
 *
 * Les réseaux acceptent un MP4 avec `moov` en fin de fichier, mais le lecteur doit
 * alors tout télécharger avant de démarrer, et certains imports (SMS, WhatsApp)
 * l'aperçoivent mal. Media3 (InAppMp4Muxer) TENTE déjà d'écrire `moov` en tête ;
 * cette passe le garantit — sans effet si c'est déjà le cas.
 *
 * Algorithme de qt-faststart : `moov` est déplacé juste après `ftyp` et tous les
 * offsets de blocs (`stco` 32 bits, `co64` 64 bits) sont décalés de la taille de
 * `moov`. Atomes top-level de taille 64 bits (size == 1) gérés ; size == 0 (« jusqu'à
 * la fin ») accepté pour le dernier atome seulement.
 */
object Mp4FastStart {

    private data class Atom(val type: String, val offset: Long, val size: Long)

    /** true si le fichier a été réécrit, false s'il était déjà faststart (ou illisible). */
    fun apply(src: File, dst: File): Boolean {
        val atoms = topLevelAtoms(src) ?: return false
        val moov = atoms.firstOrNull { it.type == "moov" } ?: return false
        val mdatIndex = atoms.indexOfFirst { it.type == "mdat" }
        if (mdatIndex < 0 || atoms.indexOf(moov) < mdatIndex) return false
        if (moov.size > Int.MAX_VALUE) return false

        val moovBytes = ByteArray(moov.size.toInt())
        RandomAccessFile(src, "r").use { it.seek(moov.offset); it.readFully(moovBytes) }
        shiftChunkOffsets(ByteBuffer.wrap(moovBytes), 8, moovBytes.size, moov.size)

        RandomAccessFile(src, "r").use { input ->
            dst.outputStream().buffered().use { out ->
                val ftypEnd = atoms.takeWhile { it.type == "ftyp" }.lastOrNull()?.let { it.offset + it.size } ?: 0L
                copy(input, out, 0, ftypEnd)
                out.write(moovBytes)
                for (a in atoms) {
                    if (a.type == "ftyp" || a === moov) continue
                    copy(input, out, a.offset, a.size)
                }
            }
        }
        return true
    }

    private fun topLevelAtoms(f: File): List<Atom>? = runCatching {
        val out = mutableListOf<Atom>()
        RandomAccessFile(f, "r").use { r ->
            val len = r.length()
            var pos = 0L
            val head = ByteArray(16)
            while (pos + 8 <= len) {
                r.seek(pos)
                r.readFully(head, 0, 8)
                val bb = ByteBuffer.wrap(head)
                var size = bb.getInt(0).toLong() and 0xffffffffL
                val type = String(head, 4, 4, Charsets.US_ASCII)
                if (size == 1L) { r.readFully(head, 8, 8); size = ByteBuffer.wrap(head).getLong(8) }
                else if (size == 0L) size = len - pos
                if (size < 8 || pos + size > len) return@runCatching null
                out.add(Atom(type, pos, size))
                pos += size
            }
        }
        out
    }.getOrNull()

    private val CONTAINERS = setOf("moov", "trak", "mdia", "minf", "stbl", "edts", "dinf", "udta")

    /** Parcourt récursivement les conteneurs de `moov` et décale stco/co64. */
    internal fun shiftChunkOffsets(b: ByteBuffer, start: Int, end: Int, delta: Long) {
        var pos = start
        while (pos + 8 <= end) {
            val size = b.getInt(pos).toLong() and 0xffffffffL
            if (size < 8 || pos + size > end) return
            val type = String(ByteArray(4).also { for (i in 0 until 4) it[i] = b.get(pos + 4 + i) }, Charsets.US_ASCII)
            when (type) {
                in CONTAINERS -> shiftChunkOffsets(b, pos + 8, (pos + size).toInt(), delta)
                "stco" -> {
                    val count = b.getInt(pos + 12)
                    for (i in 0 until count) {
                        val at = pos + 16 + i * 4
                        val v = (b.getInt(at).toLong() and 0xffffffffL) + delta
                        require(v <= 0xffffffffL) { "stco overflow" }
                        b.putInt(at, v.toInt())
                    }
                }
                "co64" -> {
                    val count = b.getInt(pos + 12)
                    for (i in 0 until count) {
                        val at = pos + 16 + i * 8
                        b.putLong(at, b.getLong(at) + delta)
                    }
                }
            }
            pos += size.toInt()
        }
    }

    private fun copy(input: RandomAccessFile, out: java.io.OutputStream, from: Long, length: Long) {
        input.seek(from)
        val buf = ByteArray(1 shl 16)
        var left = length
        while (left > 0) {
            val n = input.read(buf, 0, minOf(buf.size.toLong(), left).toInt())
            if (n <= 0) break
            out.write(buf, 0, n)
            left -= n
        }
    }
}
