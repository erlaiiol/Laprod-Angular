package net.laprod.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

// ── ClipSyncTest ────────────────────────────────────────────────────────────────
//
// Mêmes vecteurs que src/app/utils/clip-sync.spec.ts (SHARED_VECTORS) : la
// position entendue doit être calculée à l'identique côté natif et côté front.
// Exécutable avec : ./gradlew :app:test

class ClipSyncTest {

    private data class V(val hostSec: Double, val filePos: Double, val anchorHost: Double, val heardMs: Double, val expected: Double)

    private val shared = listOf(
        V(1000.5, 0.0, 1000.0, 0.0, 0.5),
        V(1000.5, 0.0, 1000.0, 180.0, 0.32),
        V(998.0, 0.0, 1000.0, 20.0, -2.02),
        V(5012.25, 3.0, 5000.0, 12.0, 15.238),
    )

    @Test
    fun positionHeardAt_matchesFrontVectors() {
        for (v in shared) {
            assertEquals(v.expected, ClipSync.positionHeardAt(v.hostSec, v.filePos, v.anchorHost, v.heardMs), 1e-9)
        }
    }

    @Test
    fun anchor_isPresentationTimeOfFrameZero() {
        // 48 000 frames présentées à t = 10 s ⇒ frame 0 présentée à t = 9 s.
        assertEquals(9_000_000_000L, ClipSync.anchorNs(48_000, 10_000_000_000L, 48_000))
    }

    @Test
    fun encoderPts_alreadyMonotonic_isNotConvertedTwice() {
        // Appareil ayant dormi 1 h : BOOTTIME = MONOTONIC + 1 h. Le service caméra a
        // déjà rebasé en MONOTONIC → la frame est 40 ms avant le drain monotonic.
        val mono = 100_000_000_000L
        val boot = mono + 3_600_000_000_000L
        assertEquals(mono - 40_000_000L, ClipSync.encoderPtsToMonoNs(mono - 40_000_000L, mono, boot))
    }

    @Test
    fun encoderPts_inBoottime_isConverted() {
        val mono = 100_000_000_000L
        val boot = mono + 3_600_000_000_000L
        assertEquals(mono - 40_000_000L, ClipSync.encoderPtsToMonoNs(boot - 40_000_000L, mono, boot))
    }

    @Test
    fun encoderPts_unknownBase_isEstimated() {
        assertEquals(100_000_000_000L - ClipSync.ENCODER_PIPELINE_NS,
            ClipSync.encoderPtsToMonoNs(7L, 100_000_000_000L, 200_000_000_000L))
    }

    @Test
    fun median_isRobustToFirstNoisyMeasure() {
        assertEquals(100L, ClipSync.medianNs(listOf(160L, 100L, 101L, 99L, 100L)))
        assertNull(ClipSync.medianNs(emptyList()))
    }
}
