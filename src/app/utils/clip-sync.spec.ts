import {
  androidHeardMs, CLIP_MAX_SECONDS, CLIP_MIN_SECONDS, clampSegment, clipLatencies, computeAlignment,
  positionHeardAt, segmentLength, syncMirePositions, validateSegment, voiceTapToPosition,
} from './clip-sync';

// Vecteurs partagés avec android/app/src/test/java/net/laprod/app/ClipSyncTest.kt :
// toute modification ici doit être reportée là-bas (et inversement).
const SHARED_VECTORS = [
  { hostSec: 1000.5,  anchor: { filePosSec: 0, hostSec: 1000.0 }, heardMs: 0,   expected: 0.5 },
  { hostSec: 1000.5,  anchor: { filePosSec: 0, hostSec: 1000.0 }, heardMs: 180, expected: 0.32 },
  { hostSec: 998.0,   anchor: { filePosSec: 0, hostSec: 1000.0 }, heardMs: 20,  expected: -2.02 },
  { hostSec: 5012.25, anchor: { filePosSec: 3, hostSec: 5000.0 }, heardMs: 12,  expected: 15.238 },
];

describe('clip-sync — segment', () => {
  it('borne la longueur à 45 s (décision produit) et au minimum', () => {
    expect(segmentLength(clampSegment(0, 60, 200))).toBe(CLIP_MAX_SECONDS);
    expect(segmentLength(clampSegment(0, 1, 200))).toBe(CLIP_MIN_SECONDS);
  });

  it('ramène le segment dans la maquette (fin de maquette)', () => {
    const s = clampSegment(190, 30, 200);
    expect(s).toEqual({ startSec: 170, endSec: 200 });
  });

  it('segment en début de maquette', () => {
    expect(clampSegment(-5, 30, 200)).toEqual({ startSec: 0, endSec: 30 });
  });

  it('maquette plus courte que le segment demandé', () => {
    expect(clampSegment(0, 45, 20)).toEqual({ startSec: 0, endSec: 20 });
  });

  it('refuse un segment de plus de 45 s', () => {
    expect(validateSegment({ startSec: 0, endSec: 45.5 }, 200)).toBe('TOO_LONG');
    expect(validateSegment({ startSec: 0, endSec: 45 }, 200)).toBeNull();
  });

  it('refuse un segment trop court ou hors maquette', () => {
    expect(validateSegment({ startSec: 0, endSec: 3 }, 200)).toBe('TOO_SHORT');
    expect(validateSegment({ startSec: 190, endSec: 210 }, 200)).toBe('OUT_OF_RANGE');
  });
});

describe('clip-sync — latences', () => {
  it('filaire : la prise retire sortie + entrée, la vidéo la sortie seule', () => {
    expect(clipLatencies({ bluetooth: false, calibratedMs: null, outputMs: 8, inputMs: 4 }))
      .toEqual({ takeCropMs: 12, heardMs: 8, recVideoMs: 8 });
  });

  it('Bluetooth calibré, route muette : la mesure (clic entendu) est la latence entendue', () => {
    expect(clipLatencies({ bluetooth: true, calibratedMs: 210, outputMs: 0, inputMs: 5 }))
      .toEqual({ takeCropMs: 210, heardMs: 210, recVideoMs: 205 });
  });

  it('Bluetooth calibré mais latence rapportée plausible : le système l\'emporte', () => {
    expect(clipLatencies({ bluetooth: true, calibratedMs: 320, outputMs: 150, inputMs: 5 }))
      .toEqual({ takeCropMs: 155, heardMs: 150, recVideoMs: 150 });
  });

  it('Android : on n\'ajoute que la part de latence Bluetooth non rapportée', () => {
    expect(androidHeardMs(false, 220, 40)).toBe(0);
    expect(androidHeardMs(true, null, 40)).toBe(0);
    expect(androidHeardMs(true, 220, 40)).toBe(180);
    expect(androidHeardMs(true, 220, 260)).toBe(0);
  });

  it('Bluetooth non calibré : latence rapportée par le système', () => {
    expect(clipLatencies({ bluetooth: true, calibratedMs: null, outputMs: 170, inputMs: 5 }))
      .toEqual({ takeCropMs: 175, heardMs: 170, recVideoMs: 170 });
  });

  it('takeCropMs − recVideoMs = latence d\'entrée, dans tous les cas', () => {
    for (const i of [
      { bluetooth: false, calibratedMs: null, outputMs: 3, inputMs: 2 },
      { bluetooth: true, calibratedMs: 240, outputMs: 0, inputMs: 6 },
      { bluetooth: true, calibratedMs: null, outputMs: 190, inputMs: 9 },
    ]) {
      const l = clipLatencies(i);
      expect(l.takeCropMs - l.recVideoMs).toBeCloseTo(i.inputMs, 9);
    }
  });
});

describe('clip-sync — horloge', () => {
  it.each(SHARED_VECTORS)('positionHeardAt($hostSec, heard $heardMs ms) = $expected', v => {
    expect(positionHeardAt(v.hostSec, v.anchor, v.heardMs)).toBeCloseTo(v.expected, 9);
  });

  it('même instant physique ⇒ même position pour la vidéo et pour la prise voix', () => {
    // Un claquement de mains à l'instant T : filmé à T, capté par le tap micro à
    // T + entrée. La vidéo et la voix doivent tomber au même endroit du clip.
    const anchor = { filePosSec: 0, hostSec: 2000 };
    for (const lat of [
      { bluetooth: false, calibratedMs: null, outputMs: 7, inputMs: 3 },
      { bluetooth: true, calibratedMs: 220, outputMs: 0, inputMs: 4 },
    ]) {
      const { takeCropMs, recVideoMs } = clipLatencies(lat);
      const T = 2012.345;
      const video = positionHeardAt(T, anchor, recVideoMs);
      const voice = voiceTapToPosition(T + lat.inputMs / 1000, anchor, takeCropMs);
      expect(voice).toBeCloseTo(video, 9);
    }
  });
});

describe('clip-sync — alignement', () => {
  const anchor = { filePosSec: 0, hostSec: 100 };

  it('caméra partie pendant le décompte : on rogne la vidéo, pas le son', () => {
    // 1re frame à 97,2 s, son entendu à partir de 100,15 s (sortie 150 ms).
    const a = computeAlignment({ firstFrameHostSec: 97.2, videoDurationSec: 40, anchor, heardMs: 150, segmentSec: 30 });
    expect(a).not.toBe('NO_OVERLAP');
    if (a === 'NO_OVERLAP') return;
    expect(a.videoTrimStartSec).toBeCloseTo(2.95, 9);
    expect(a.audioSkipSec).toBe(0);
    expect(a.durationSec).toBeCloseTo(30, 9);
  });

  it('caméra partie en retard : on saute le début du son (offset positif)', () => {
    const a = computeAlignment({ firstFrameHostSec: 100.5, videoDurationSec: 40, anchor, heardMs: 0, segmentSec: 30 });
    if (a === 'NO_OVERLAP') throw new Error('attendu');
    expect(a.videoTrimStartSec).toBe(0);
    expect(a.audioSkipSec).toBeCloseTo(0.5, 9);
    expect(a.durationSec).toBeCloseTo(29.5, 9);
  });

  it('arrêt anticipé : durée = vidéo disponible après rognage', () => {
    const a = computeAlignment({ firstFrameHostSec: 97, videoDurationSec: 13, anchor, heardMs: 0, segmentSec: 45 });
    if (a === 'NO_OVERLAP') throw new Error('attendu');
    expect(a.durationSec).toBeCloseTo(10, 9);
  });

  it('pas assez de recouvrement ⇒ NO_OVERLAP', () => {
    expect(computeAlignment({ firstFrameHostSec: 97, videoDurationSec: 5, anchor, heardMs: 0, segmentSec: 30 }))
      .toBe('NO_OVERLAP');
  });

  it('jamais plus de 45 s', () => {
    const a = computeAlignment({ firstFrameHostSec: 90, videoDurationSec: 200, anchor, heardMs: 0, segmentSec: 60 });
    if (a === 'NO_OVERLAP') throw new Error('attendu');
    expect(a.durationSec).toBe(CLIP_MAX_SECONDS);
  });
});

describe('clip-sync — mire', () => {
  it('clics toutes les 2 s, à l\'intérieur du segment', () => {
    expect(syncMirePositions(7)).toEqual([2, 4, 6]);
  });
});

describe('clip-sync — aucune horloge WebView', () => {
  it('le module n\'utilise ni Date.now ni performance.now', async () => {
    const dateSpy = vi.spyOn(Date, 'now');
    const perfSpy = vi.spyOn(performance, 'now');
    computeAlignment({ firstFrameHostSec: 1, videoDurationSec: 30, anchor: { filePosSec: 0, hostSec: 2 }, heardMs: 10, segmentSec: 20 });
    positionHeardAt(3, { filePosSec: 0, hostSec: 2 }, 5);
    expect(dateSpy).not.toHaveBeenCalled();
    expect(perfSpy).not.toHaveBeenCalled();
  });
});
