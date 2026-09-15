package net.laprod.app

// ── PsolaAudioEngine ──────────────────────────────────────────────────────────
//
// Façade Kotlin vers le moteur audio bas niveau AAudio (aaudio_engine.c/aaudio_jni.c) — voir
// docs/roadmap.md, chantier latence. Chemin RAPIDE : capture, détection YIN et
// correction PSOLA tournent entièrement dans des callbacks natifs AAudio, sans traversée JNI
// par bloc. Kotlin ne fait que démarrer/arrêter le moteur et le sonder périodiquement
// (voir [pollStatus]) — jamais depuis le thread audio, qui n'existe pas côté Kotlin pour ce
// chemin (contrairement à `AudioCaptureLoop`, qui tourne dans une coroutine bloquante).
//
// [create] retourne `null` si AAudio est indisponible (API<26, MMAP refusé par l'appareil,
// etc.) — c'est un cas ATTENDU, pas une erreur : l'appelant ([AudioRecordingSession]) doit se
// rabattre sur `AudioCaptureLoop` (le chemin Phase 1, déjà éprouvé), jamais réessayer en
// boucle ni logguer comme une anomalie.
class PsolaAudioEngine private constructor(private val handle: Long) : AutoCloseable {

    /** Rempli par [pollStatus] : `level` (RMS), `pitchHz` (NaN si rien de neuf),
     *  `interrupted` (déconnexion du flux depuis le dernier appel — casque débranché, etc.). */
    data class Status(val level: Float, val pitchHz: Float, val interrupted: Boolean)

    private val statusBuf = FloatArray(2)

    /** À appeler périodiquement (ex. toutes les ~20ms) depuis une coroutine normale — jamais
     *  depuis un contexte temps réel, qui n'existe pas côté Kotlin pour ce moteur. */
    fun pollStatus(): Status {
        val interrupted = nativePollStatus(handle, statusBuf) != 0
        return Status(level = statusBuf[0], pitchHz = statusBuf[1], interrupted = interrupted)
    }

    /** Thread-safe côté natif (atomic) — safe à appeler depuis la coroutine de polling. */
    fun setPitchCents(cents: Float) = nativeSetPitchCents(handle, cents)

    fun setMonitorOptions(useMonitor: Boolean, monitorAutotune: Boolean, voiceGain: Float) =
        nativeSetMonitorOptions(handle, useMonitor, monitorAutotune, voiceGain)

    /** Draine le PCM brut capturé depuis la dernière fois (pour l'enregistrement) dans
     *  [out] ; retourne le nombre d'échantillons réellement drainés (<= out.size). À appeler
     *  régulièrement (même cadence que [pollStatus]) pour ne pas perdre d'audio — le buffer
     *  circulaire natif ne garde qu'~1.5s de marge (voir aaudio_engine.c). */
    fun drainRecorded(out: FloatArray): Int = nativeDrainRecorded(handle, out)

    override fun close() = nativeDestroy(handle)

    private external fun nativeSetPitchCents(handle: Long, cents: Float)
    private external fun nativePollStatus(handle: Long, outLevelPitch: FloatArray): Int
    private external fun nativeDrainRecorded(handle: Long, out: FloatArray): Int
    private external fun nativeSetMonitorOptions(
        handle: Long, useMonitor: Boolean, monitorAutotune: Boolean, voiceGain: Float,
    )
    private external fun nativeDestroy(handle: Long)

    companion object {
        init { System.loadLibrary("psola_processor") }

        @JvmStatic
        private external fun nativeCreate(
            sampleRate: Int, useMonitor: Boolean, monitorAutotune: Boolean, voiceGain: Float,
            formantPreservation: Boolean,
        ): Long

        /** Retourne `null` si le moteur AAudio n'a pas pu être créé (voir la doc de classe) —
         *  l'appelant doit alors utiliser `AudioCaptureLoop` à la place. */
        fun create(
            sampleRate: Int, useMonitor: Boolean, monitorAutotune: Boolean, voiceGain: Float,
            formantPreservation: Boolean = true,
        ): PsolaAudioEngine? {
            val handle = nativeCreate(sampleRate, useMonitor, monitorAutotune, voiceGain, formantPreservation)
            return if (handle == 0L) null else PsolaAudioEngine(handle)
        }
    }
}
