"""Worker RQ — analyse audio post-upload (BPM, gamme, style).

Ce job est mis en queue avec `depends_on=process_track_job` : il attend
que le track soit créé en base avant de démarrer.
"""

import logging
import time

logger = logging.getLogger(__name__)


def detect_bpm(path: str) -> int:
    import numpy as np
    import librosa

    y, sr = librosa.load(path, sr=None, mono=True, duration=60)
    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
    return int(round(float(np.atleast_1d(tempo)[0])))


def detect_key(path: str) -> str:
    import numpy as np
    import librosa

    y, sr = librosa.load(path, sr=None, mono=True, duration=60)
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr).mean(axis=1)

    # Profils Krumhansl-Kessler
    major  = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
    minor  = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
    notes  = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

    best_key, best_score = 'C', -2.0
    for i, note in enumerate(notes):
        ch = np.roll(chroma, -i)
        for profile, suffix in [(major, ''), (minor, 'm')]:
            score = float(np.corrcoef(ch, profile)[0, 1])
            if score > best_score:
                best_score, best_key = score, f'{note}{suffix}'
    return best_key


def analyze_track(payload: dict):
    """
    Payload attendu :
        job_id    : str   — clé Redis du job process_track (pour récupérer track_id)
        user_id   : int
        mp3_path  : str   — chemin absolu du fichier MP3 déjà copié sur disque
        auto_bpm  : bool
        auto_key  : bool
        auto_style: bool
    """
    from app import create_app
    app = create_app()
    with app.app_context():
        from extensions import db, redis_client
        from models import Track, User
        from utils import notification_service, email_service

        # Attendre que process_track stocke le track_id dans Redis (max 60 s)
        track_id = None
        for _ in range(30):
            raw = redis_client.hget(f"job:{payload['job_id']}", 'track_id')
            if raw:
                track_id = int(raw)
                break
            time.sleep(2)

        if not track_id:
            logger.error('audio_analysis: track_id introuvable pour job %s', payload.get('job_id'))
            return

        track = db.session.get(Track, track_id)
        if not track:
            logger.error('audio_analysis: Track %s introuvable', track_id)
            return

        suggestions: dict = {}
        mp3_path = payload.get('mp3_path', '')

        if payload.get('auto_bpm') and mp3_path:
            try:
                bpm = detect_bpm(mp3_path)
                if 40 <= bpm <= 300:
                    track.bpm = bpm
                    suggestions['bpm'] = bpm
            except Exception as e:
                logger.warning('audio_analysis: échec détection BPM — %s', e)

        if payload.get('auto_key') and mp3_path:
            try:
                key = detect_key(mp3_path)
                track.key = key
                suggestions['key'] = key
            except Exception as e:
                logger.warning('audio_analysis: échec détection gamme — %s', e)

        if payload.get('auto_style'):
            try:
                from sqlalchemy import func
                most_used = (
                    db.session.query(Track.style, func.count(Track.id))
                    .filter(
                        Track.composer_id == payload['user_id'],
                        Track.style.isnot(None),
                        Track.style != '',
                        Track.id != track_id,
                    )
                    .group_by(Track.style)
                    .order_by(func.count(Track.id).desc())
                    .first()
                )
                if most_used:
                    track.style = most_used[0]
                    suggestions['style'] = most_used[0]
            except Exception as e:
                logger.warning('audio_analysis: échec style — %s', e)

        if suggestions:
            track.is_ai_suggested = True

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error('audio_analysis: commit échoué — %s', e)
            return

        user = db.session.get(User, payload['user_id'])
        if user and suggestions:
            try:
                notification_service.notify_audio_analysis_done(user, track, suggestions)
                db.session.commit()
            except Exception as e:
                logger.warning('audio_analysis: notif échouée — %s', e)
            try:
                email_service.send_audio_analysis_email(user, track, suggestions)
            except Exception as e:
                logger.warning('audio_analysis: email échoué — %s', e)
