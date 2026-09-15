package net.laprod.app

// ── PsolaProcessor ────────────────────────────────────────────────────────────
//
// Façade Kotlin autour du moteur PSOLA+LPC maison (JNI → native/psola-ffi, Rust), qui
// remplace Rubber Band (GPL-3.0) — voir docs/roadmap.md. Interface strictement identique à
// l'ancien `RubberBandProcessor.kt` : renommage de bibliothèque uniquement, aucun changement
// de contrat pour `AudioCaptureLoop`.
//
// Thread model (inchangé) :
//   setPitchCents  — safe depuis n'importe quel thread (atomic côté Rust)
//   process / available / retrieve / reset — appeler depuis le thread IO audio uniquement

class PsolaProcessor(sampleRate: Int) : AutoCloseable {

    private val handle: Long = nativeCreate(sampleRate)

    // ── API publique ───────────────────────────────────────────────────────────

    /** Thread-safe : peut être appelée depuis le handler de détection de hauteur. */
    fun setPitchCents(cents: Float) = nativeSetPitchCents(handle, cents)

    /**
     * Consomme un bloc d'échantillons mono float32 (plage [-1, 1]).
     * Appeler uniquement depuis le thread IO audio.
     */
    fun process(input: FloatArray) = nativeProcess(handle, input)

    /** Nombre d'échantillons prêts à être récupérés. */
    fun available(): Int = nativeAvailable(handle)

    /**
     * Copie les échantillons disponibles dans [output] ([output.size] doit égaler
     * [available]). Appeler uniquement depuis le thread IO audio.
     */
    fun retrieve(output: FloatArray) = nativeRetrieve(handle, output)

    /** Latence structurelle du moteur, en échantillons (informatif). */
    val latencySamples: Int get() = nativeGetLatency(handle)

    /** Réinitialise l'état interne et remet le pitch à l'unisson. */
    fun reset() = nativeReset(handle)

    override fun close() = nativeDestroy(handle)

    // ── Déclarations JNI ───────────────────────────────────────────────────────

    private external fun nativeCreate(sampleRate: Int): Long
    private external fun nativeDestroy(handle: Long)
    private external fun nativeSetPitchCents(handle: Long, cents: Float)
    private external fun nativeProcess(handle: Long, input: FloatArray)
    private external fun nativeAvailable(handle: Long): Int
    private external fun nativeRetrieve(handle: Long, output: FloatArray)
    private external fun nativeGetLatency(handle: Long): Int
    private external fun nativeReset(handle: Long)

    companion object {
        init { System.loadLibrary("psola_processor") }
    }
}
