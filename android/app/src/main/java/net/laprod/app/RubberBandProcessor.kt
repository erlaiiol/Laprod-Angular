package net.laprod.app

// ── RubberBandProcessor ───────────────────────────────────────────────────────
//
// Kotlin façade around the native (JNI) Rubber Band pitch shifter.
//
// Thread model:
//   setPitchCents  — safe from any thread (atomic store in native)
//   process / available / retrieve / reset — call from the TarsosDSP IO thread
//
// SETUP: Requires the Rubber Band Library v3.x source at
//   android/app/src/main/cpp/rubberband/rubberband/RubberBandStretcher.h
//   Download from https://breakfastquay.com/rubberband/ (GPL or commercial).
//   The CMakeLists.txt at android/app/src/main/cpp/CMakeLists.txt compiles it.

class RubberBandProcessor(sampleRate: Int) : AutoCloseable {

    private val handle: Long = nativeCreate(sampleRate)

    // ── Public API ────────────────────────────────────────────────────────────

    /** Thread-safe: may be called from the pitch-detection handler. */
    fun setPitchCents(cents: Float) = nativeSetPitchCents(handle, cents)

    /**
     * Feed a block of mono float32 PCM samples (range [-1, 1]) to the shifter.
     * Call from the TarsosDSP audio IO thread only.
     */
    fun process(input: FloatArray) = nativeProcess(handle, input)

    /** Number of samples ready for retrieval. */
    fun available(): Int = nativeAvailable(handle)

    /**
     * Copy available output into [output].  [output.size] must equal [available()].
     * Call from the TarsosDSP audio IO thread only.
     */
    fun retrieve(output: FloatArray) = nativeRetrieve(handle, output)

    /** RubberBand's startup latency in samples (informational / tests). */
    val latencySamples: Int get() = nativeGetLatency(handle)

    /** Reset internal state and pitch to 0. */
    fun reset() = nativeReset(handle)

    override fun close() = nativeDestroy(handle)

    // ── JNI declarations ──────────────────────────────────────────────────────

    private external fun nativeCreate(sampleRate: Int): Long
    private external fun nativeDestroy(handle: Long)
    private external fun nativeSetPitchCents(handle: Long, cents: Float)
    private external fun nativeProcess(handle: Long, input: FloatArray)
    private external fun nativeAvailable(handle: Long): Int
    private external fun nativeRetrieve(handle: Long, output: FloatArray)
    private external fun nativeGetLatency(handle: Long): Int
    private external fun nativeReset(handle: Long)

    companion object {
        init { System.loadLibrary("rubberband_processor") }
    }
}
