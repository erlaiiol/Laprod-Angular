package net.laprod.app

/**
 * Mode Clip — calculs purs de synchro côté Android (docs/roadmap.md § 4.3).
 *
 * Miroir de src/app/utils/clip-sync.ts pour ce qui doit être calculé en natif
 * (conversion d'horloges, ancre AudioTrack). Testé en JVM avec les MÊMES
 * vecteurs que clip-sync.spec.ts (ClipSyncTest.kt).
 *
 * Base de temps commune : CLOCK_MONOTONIC (System.nanoTime), en nanosecondes,
 * exposée au JS en secondes. AudioTrack.getTimestamp() est déjà dans cette base.
 */
object ClipSync {

    const val MAX_SECONDS = 45.0

    /**
     * Ancre de lecture : instant (monotonic, ns) où l'échantillon 0 du fichier
     * est PRÉSENTÉ, d'après un AudioTimestamp (framePosition, nanoTime).
     */
    fun anchorNs(framePosition: Long, presentedNs: Long, sampleRate: Int): Long =
        presentedNs - framePosition * 1_000_000_000L / sampleRate

    /**
     * Ancre robuste : médiane de plusieurs mesures (le premier getTimestamp
     * après play() est souvent imprécis de quelques ms).
     */
    fun medianNs(values: List<Long>): Long? {
        if (values.isEmpty()) return null
        val s = values.sorted()
        return s[s.size / 2]
    }

    /**
     * PTS encodeur (= timestamp capteur transmis par la surface Camera2) → MONOTONIC.
     *
     * La base réelle n'est PAS celle annoncée par SENSOR_INFO_TIMESTAMP_SOURCE :
     * pour un consommateur encodeur vidéo, le service caméra AOSP rebase déjà les
     * timestamps REALTIME en MONOTONIC (Camera3OutputStream, mUseMonoTimestamp).
     * Convertir une seconde fois décalerait la vidéo du temps total de veille.
     * On déduit donc la base des données : au moment où l'encodeur rend la frame
     * (`drainMonoNs` / `drainBootNs`, lus au même instant), elle a été capturée
     * il y a quelques dizaines de ms — la base la plus proche est la bonne.
     * Ni l'une ni l'autre à moins d'1 s : base inconnue, écart estimé (moins précis).
     */
    fun encoderPtsToMonoNs(ptsNs: Long, drainMonoNs: Long, drainBootNs: Long): Long {
        val dMono = drainMonoNs - ptsNs
        val dBoot = drainBootNs - ptsNs
        val oneSec = 1_000_000_000L
        return when {
            kotlin.math.abs(dMono) < oneSec && kotlin.math.abs(dMono) <= kotlin.math.abs(dBoot) -> ptsNs
            kotlin.math.abs(dBoot) < oneSec -> ptsNs - (drainBootNs - drainMonoNs)
            else -> drainMonoNs - ENCODER_PIPELINE_NS
        }
    }

    /** Délai typique capture → sortie encodeur, pour l'estimation de dernier recours. */
    const val ENCODER_PIPELINE_NS = 50_000_000L

    /** Position fichier entendue à `hostSec` — identique à positionHeardAt (clip-sync.ts). */
    fun positionHeardAt(hostSec: Double, anchorFilePosSec: Double, anchorHostSec: Double, heardMs: Double): Double =
        anchorFilePosSec + (hostSec - anchorHostSec) - heardMs / 1000.0
}
