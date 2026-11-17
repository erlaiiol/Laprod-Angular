#!/usr/bin/env python3
"""
Mesure objective de la synchro audio/vidéo d'un clip du Mode Clip
(docs/roadmap.md § 4.3 — mire de synchro).

Principe : la vidéo filme un éclair blanc ET son audio contient un clic au même
instant physique (mire externe scripts/clip_sync_mire.html filmée en mode Rec,
ou clap test en Playback). Le script détecte les éclairs (luminance moyenne
de chaque frame, PTS réels) et les attaques audio, les apparie, puis vérifie
les seuils de la roadmap.

Usage :
    python3 scripts/clip_sync_check.py clip1.mp4 [clip2.mp4 ...] [--json]

Écart affiché = instant du clic − instant de l'éclair (ms).
  > 0 : le son est en retard sur l'image ; < 0 : le son est en avance.

Code de sortie 0 si tous les seuils sont respectés, 1 sinon, 2 si mesure impossible.
Dépendances : ffmpeg / ffprobe dans le PATH, rien d'autre (pas de numpy).
"""
from __future__ import annotations

import argparse
import array
import json
import statistics
import subprocess
import sys

# Seuils § 4.3 — miroir de SYNC_THRESHOLDS (src/app/utils/clip-sync.ts).
MEAN_ABS_MS = 40
AUDIO_LEAD_MS = 30
DRIFT_MS = 10
REPEAT_SPREAD_MS = 15

SR = 48_000
PAIR_WINDOW_S = 0.3          # un clic et un éclair à plus de 300 ms ne sont pas le même événement
MIN_GAP_S = 0.8              # deux événements de la mire sont espacés de 2 s


def _run(cmd: list[str]) -> bytes:
    return subprocess.run(cmd, check=True, capture_output=True).stdout


def frame_luma(path: str) -> list[tuple[float, float]]:
    """(pts_s, luminance moyenne 0–255) pour chaque frame, PTS réels (VFR possible)."""
    pts_raw = _run([
        'ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'frame=pts_time',
        '-of', 'csv=p=0', path,
    ]).decode().split()
    pts = [float(p.strip(',')) for p in pts_raw if p.strip(',')]
    w, h = 32, 56
    raw = _run([
        'ffmpeg', '-v', 'error', '-i', path, '-vf', f'scale={w}:{h},format=gray',
        '-fps_mode', 'passthrough', '-f', 'rawvideo', '-',
    ])
    n = w * h
    frames = len(raw) // n
    lum = [sum(raw[i * n:(i + 1) * n]) / n for i in range(frames)]
    return list(zip(pts[:frames], lum))


def audio_env(path: str) -> list[float]:
    """Enveloppe d'amplitude par fenêtres de 1 ms (mono, 48 kHz)."""
    raw = _run(['ffmpeg', '-v', 'error', '-i', path, '-ac', '1', '-ar', str(SR), '-f', 's16le', '-'])
    pcm = array.array('h')
    pcm.frombytes(raw)
    win = SR // 1000
    return [max(abs(v) for v in pcm[i:i + win]) for i in range(0, len(pcm) - win, win)]


def detect_flashes(frames: list[tuple[float, float]]) -> list[float]:
    """Front montant de luminance au-dessus du milieu entre fond et éclair."""
    if not frames:
        return []
    lums = sorted(l for _, l in frames)
    # Éclairs d'1 à 3 frames toutes les 2 s : rares → le max, pas un quantile.
    low, high = lums[len(lums) // 10], lums[-1]
    if high - low < 40:
        return []
    thr = (low + high) / 2
    out, prev = [], False
    for t, l in frames:
        on = l > thr
        if on and not prev and (not out or t - out[-1] > MIN_GAP_S):
            out.append(t)
        prev = on
    return out


def detect_clicks(env: list[float]) -> list[float]:
    """Attaques : enveloppe qui passe au-dessus de 6× le bruit de fond médian."""
    if not env:
        return []
    floor = statistics.median(env) or 1.0
    thr = max(floor * 6, max(env) * 0.25)
    out, prev = [], False
    for i, v in enumerate(env):
        on = v > thr
        t = i / 1000
        if on and not prev and (not out or t - out[-1] > MIN_GAP_S):
            out.append(t)
        prev = on
    return out


def pair(flashes: list[float], clicks: list[float]) -> list[float]:
    """Écarts (ms) clic − éclair pour chaque éclair ayant un clic proche."""
    offsets = []
    for f in flashes:
        near = min(clicks, key=lambda c: abs(c - f), default=None)
        if near is not None and abs(near - f) <= PAIR_WINDOW_S:
            offsets.append((near - f) * 1000)
    return offsets


def analyse(path: str) -> dict:
    offsets = pair(detect_flashes(frame_luma(path)), detect_clicks(audio_env(path)))
    if len(offsets) < 2:
        return {'file': path, 'error': 'moins de 2 événements appariés (mire visible et audible ?)'}
    return {
        'file': path,
        'events': len(offsets),
        'mean_ms': statistics.mean(offsets),
        'mean_abs_ms': statistics.mean(abs(o) for o in offsets),
        'audio_lead_ms': max(0.0, -min(offsets)),
        'drift_ms': offsets[-1] - offsets[0],
        'offsets_ms': [round(o, 1) for o in offsets],
    }


def verdict(results: list[dict]) -> tuple[bool, list[str]]:
    fails = []
    ok_results = [r for r in results if 'error' not in r]
    for r in ok_results:
        if r['mean_abs_ms'] > MEAN_ABS_MS:
            fails.append(f"{r['file']}: écart moyen {r['mean_abs_ms']:.1f} ms > {MEAN_ABS_MS} ms")
        if r['audio_lead_ms'] > AUDIO_LEAD_MS:
            fails.append(f"{r['file']}: son en avance de {r['audio_lead_ms']:.1f} ms > {AUDIO_LEAD_MS} ms")
        if abs(r['drift_ms']) > DRIFT_MS:
            fails.append(f"{r['file']}: dérive {r['drift_ms']:.1f} ms > {DRIFT_MS} ms")
    if len(ok_results) >= 2:
        means = [r['mean_ms'] for r in ok_results]
        spread = max(means) - min(means)
        if spread > REPEAT_SPREAD_MS:
            fails.append(f'variation entre clips {spread:.1f} ms > {REPEAT_SPREAD_MS} ms')
    return not fails, fails


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('files', nargs='+')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()

    results = [analyse(f) for f in args.files]
    passed, fails = verdict(results)
    if args.json:
        print(json.dumps({'results': results, 'passed': passed, 'failures': fails}, ensure_ascii=False, indent=2))
    else:
        for r in results:
            if 'error' in r:
                print(f"✗ {r['file']}: {r['error']}")
                continue
            print(f"{r['file']}: {r['events']} événements, moyen {r['mean_ms']:+.1f} ms, "
                  f"|moyen| {r['mean_abs_ms']:.1f} ms, avance son max {r['audio_lead_ms']:.1f} ms, "
                  f"dérive {r['drift_ms']:+.1f} ms")
        print('SEUILS RESPECTÉS' if passed else 'ÉCHEC :\n  ' + '\n  '.join(fails))
    if any('error' in r for r in results):
        return 2
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
