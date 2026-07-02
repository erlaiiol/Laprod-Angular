"""
Worker RQ — Traitement asynchrone des toplines.

Calqué sur tasks/track_processing.py.
Reçoit un job_payload dict préparé par routes/cud_toplines_api.py upload_topline().

Étapes :
  1. Conversion du fichier brut en WAV
  2. Application d'effets vocaux + autotune optionnel
  3. Fusion voix + beat
  4. Enregistrement Topline en BDD + décrément token
  5. Cleanup fichiers temporaires
"""
import logging
from pathlib import Path

from app import create_app
from models import Topline, User


class ToplineProcessingError(Exception):
    """Exception custom pour éviter les multi-logs RQ."""
    pass


def process_topline_data(job_payload: dict):
    """
    Exécutée par le worker RQ — pas dans un contexte Flask HTTP.
    job_payload contient tout ce que upload_topline() a préparé.
    """
    flask_app = create_app()

    # Import après create_app() — redis_client initialisé par init_extensions()
    from extensions import redis_client, db
    from utils.toplines_processor import (
        convert_to_wav,
        apply_audio_effects,
        merge_voice_and_beat,
        cleanup_temp_files,
    )

    job_id = job_payload['job_id']

    try:
        with flask_app.app_context():

            user = db.session.get(User, job_payload['user_id'])
            if not user:
                redis_client.hset(f"job:{job_id}", mapping={
                    'status': 'error', 'error_message': 'User not found'
                })
                return

            redis_client.hset(f"job:{job_id}", mapping={'status': 'started'})

            raw_path = Path(job_payload['raw_path'])

            # ── Étape 1 : conversion WAV ──────────────────────────────────────
            try:
                wav_temp_path = convert_to_wav(raw_path)
            except ValueError as e:
                # Fichier vide ou invalide — message explicite pour l'utilisateur
                logging.warning(f"Topline job {job_id} — invalid audio file: {e}")
                redis_client.hset(f"job:{job_id}", mapping={
                    'status': 'error', 'error_message': str(e)
                })
                raise ToplineProcessingError(str(e)) from e
            except Exception as e:
                logging.error(f"Topline job {job_id} — convert_to_wav failed: {e}", exc_info=True)
                redis_client.hset(f"job:{job_id}", mapping={
                    'status': 'error',
                    'error_message': 'Impossible de décoder le fichier audio. Format non supporté ?'
                })
                raise ToplineProcessingError(f"Job {job_id} failed at convert_to_wav: {e}") from e

            # ── Étape 2 : effets vocaux + autotune ───────────────────────────
            try:
                wav_effects_path = apply_audio_effects(
                    wav_temp_path,
                    sample_rate=48000,
                    autotune_key=job_payload['track_key'] if job_payload['use_autotune'] else None,
                )
            except Exception as e:
                logging.error(f"Topline job {job_id} — apply_audio_effects failed: {e}", exc_info=True)
                cleanup_temp_files([raw_path, wav_temp_path])
                redis_client.hset(f"job:{job_id}", mapping={
                    'status': 'error', 'error_message': 'Audio effects processing failed'
                })
                raise ToplineProcessingError(f"Job {job_id} failed at apply_audio_effects: {e}") from e

            # ── Étape 3 : fusion voix + beat ──────────────────────────────────
            beat_audio_file = job_payload['beat_audio_file']
            beat_path = Path(flask_app.root_path) / 'db_assets' / 'audio' / beat_audio_file
            if not beat_path.exists():
                cleanup_temp_files([raw_path, wav_temp_path, wav_effects_path])
                redis_client.hset(f"job:{job_id}", mapping={
                    'status': 'error', 'error_message': 'Beat file not found on server'
                })
                raise ToplineProcessingError(f"Job {job_id} — beat file not found: {beat_path}")

            try:
                final_relative_path = merge_voice_and_beat(
                    voice_path=wav_effects_path,
                    beat_path=str(beat_path),
                    track_id=job_payload['track_id'],
                    user_id=job_payload['user_id'],
                    timestamp=job_payload['timestamp'],
                    latency_ms=job_payload.get('latency_hint_ms', 0),
                )
            except Exception as e:
                logging.error(f"Topline job {job_id} — merge_voice_and_beat failed: {e}", exc_info=True)
                cleanup_temp_files([raw_path, wav_temp_path, wav_effects_path])
                redis_client.hset(f"job:{job_id}", mapping={
                    'status': 'error', 'error_message': 'Voice/beat merge failed'
                })
                raise ToplineProcessingError(f"Job {job_id} failed at merge_voice_and_beat: {e}") from e

            redis_client.hset(f"job:{job_id}", mapping={'status': 'finalizing'})

            # ── Étape 4 : enregistrement BDD ──────────────────────────────────
            try:
                topline = Topline(
                    track_id=job_payload['track_id'],
                    artist_id=job_payload['user_id'],
                    audio_file=final_relative_path,
                    description=job_payload['description'],
                )
                db.session.add(topline)
                user.consume_topline_token()
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                logging.error(f"Topline job {job_id} — DB error: {e}", exc_info=True)
                cleanup_temp_files([raw_path, wav_temp_path, wav_effects_path])
                redis_client.hset(f"job:{job_id}", mapping={
                    'status': 'error', 'error_message': 'Database error during topline creation'
                })
                raise ToplineProcessingError(f"Job {job_id} failed at DB commit: {e}") from e

            # ── Étape 5 : cleanup + finalisation ──────────────────────────────
            cleanup_temp_files([raw_path, wav_temp_path, wav_effects_path])

            redis_client.hset(f"job:{job_id}", mapping={
                'status':     'done',
                'topline_id': str(topline.id),
            })
            redis_client.expire(f"job:{job_id}", 3600)

            logging.info(
                f"Topline job {job_id} done — topline #{topline.id} "
                f"pour user #{job_payload['user_id']} sur track #{job_payload['track_id']}"
            )

    except ToplineProcessingError:
        raise

    except Exception as e:
        logging.error(f"Unexpected error in topline processing job {job_id}: {e}", exc_info=True)
        redis_client.hset(f"job:{job_id}", mapping={
            'status': 'error', 'error_message': 'Unexpected error during topline processing'
        })
        try:
            with flask_app.app_context():
                db.session.rollback()
        except Exception:
            pass
        raise ToplineProcessingError(f"Job {job_id} failed with unexpected error: {e}") from e
