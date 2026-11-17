"""
Auto-test de l'outil de mesure de la synchro (scripts/clip_sync_check.py) sur une
vidéo synthétique au décalage connu : si l'outil se trompe, toute la recette
« mire de synchro » (docs/roadmap.md § 4.3) est faussée.
"""
import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'),
                                reason='ffmpeg/ffprobe absents')


def _load():
    spec = importlib.util.spec_from_file_location('clip_sync_check', ROOT / 'scripts' / 'clip_sync_check.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _synthetic(path: Path, audio_delay_ms: int, drift_ms_per_event: float = 0.0) -> None:
    """MP4 30 fps : éclair blanc d'1 frame toutes les 2 s, bip 2 kHz décalé de audio_delay_ms."""
    dur, events = 10, [2, 4, 6, 8]
    flashes = '+'.join(f'between(T,{t},{t + 0.033})' for t in events)   # geq : T = temps
    beeps = '+'.join(
        f'between(t,{t + (audio_delay_ms + i * drift_ms_per_event) / 1000},{t + (audio_delay_ms + i * drift_ms_per_event) / 1000 + 0.01})'
        for i, t in enumerate(events))
    subprocess.run([
        'ffmpeg', '-v', 'error', '-y',
        '-f', 'lavfi', '-i', f'color=c=black:s=180x320:r=30:d={dur}',
        '-f', 'lavfi', '-i', f"aevalsrc='0.9*sin(2*PI*2000*t)*({beeps})':s=48000:d={dur}",
        '-vf', f"geq=lum='if({flashes},255,16)':cb=128:cr=128",
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-shortest', str(path),
    ], check=True, capture_output=True)


def test_mesure_un_decalage_connu(tmp_path):
    mod = _load()
    f = tmp_path / 'clip.mp4'
    _synthetic(f, audio_delay_ms=25)
    r = mod.analyse(str(f))
    assert r.get('events') == 4, r
    # Tolérance : 1 frame vidéo (33 ms) de quantification + délai de l'encodeur AAC.
    assert abs(r['mean_ms'] - 25) <= 35, r
    assert abs(r['drift_ms']) <= 5, r


def test_detecte_une_derive(tmp_path):
    mod = _load()
    f = tmp_path / 'clip.mp4'
    _synthetic(f, audio_delay_ms=0, drift_ms_per_event=15)
    r = mod.analyse(str(f))
    assert r['drift_ms'] >= 30, r
    passed, fails = mod.verdict([r])
    assert not passed and any('dérive' in x for x in fails)


def test_variation_entre_clips(tmp_path):
    mod = _load()
    a, b = tmp_path / 'a.mp4', tmp_path / 'b.mp4'
    _synthetic(a, 0)
    _synthetic(b, 120)
    passed, fails = mod.verdict([mod.analyse(str(a)), mod.analyse(str(b))])
    assert not passed and any('variation' in x for x in fails)
