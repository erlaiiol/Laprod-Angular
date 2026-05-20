from uuid import uuid4

import config
from pathlib import Path
import shutil, logging
from extensions import db
from app import create_app
from models import Track, User, Tag
from helpers import generate_track_image

try:
    from utils.audio_processing import apply_watermark_and_trim
    WATERMARK_AVAILABLE = True
    logging.info('\'WATERMARK_AVAILABLE\': utils.audio_processing imported successfully in track_processing.py.')
except ImportError as e:
    logging.error(f"Error importing utils \'WATERMARK_AVAILABLE\' in track_processing.py: {e}")
    WATERMARK_AVAILABLE = False

class TrackProcessingError(Exception):
    """class custom d'exception pour les erreurs 
    de processing de track, afin d'éviter les 
    multi-logs d'erreur dans RQ (anciennement RuntimeError)"""
    pass

def process_track_data(job_payload : dict):
    """
    Exécutée par le worker RQ — pas dans un contexte Flask HTTP.
    job_payload contient tout ce que post_track() a préparé :
      - chemins des fichiers temporaires
      - données du track (title, bpm, key, ...)
      - user_id
      - job_id (pour mettre à jour Redis)
    """
    flask_app = create_app()

    # Importer redis_client APRÈS create_app() — init_extensions() l'a initialisé.
    # Un import au niveau module capturerait None (valeur avant init).
    from extensions import redis_client

    try:
        with flask_app.app_context():  

            user = db.session.get(User, job_payload['user_id'])
            if not user:
                redis_client.hset(f"job:{job_payload['job_id']}", mapping={'status':'error', 'error_message': 'User not found'})
                return

            redis_client.hset(f"job:{job_payload['job_id']}", mapping={'status': 'started'})

            if WATERMARK_AVAILABLE:
                apply_watermark_and_trim(
                    input_path=job_payload['mp3_disk_path'], 
                    output_path=job_payload['preview_disk_path'],
                    watermark_path=config.WATERMARK_AUDIO_PATH,
                    preview_duration=config.PREVIEW_DURATION,
                    watermark_positions=config.WATERMARK_INTERVALS)

            if not Path(job_payload['preview_disk_path']).exists():
                logging.warning('preview absente après watermark. Copie du MP3 original.')
                try:
                    shutil.copy(job_payload['mp3_disk_path'], job_payload['preview_disk_path'])
                except Exception as e:
                    logging.error(f"Fallback watermark échoué: {e}", exc_info=True)
                    redis_client.hset(f"job:{job_payload['job_id']}", mapping={
                        'status': 'error', 'error_message': 'Audio processing failed'
                    })
                    raise TrackProcessingError(f"Job {job_payload['job_id']} failed during audio processing: {e}")

            image_filename = None


            if job_payload['image_filename'] is None:
                
                image_filename = f"{job_payload['title']}_{uuid4().hex[:8]}.png"
                image_disk_path = config.IMAGES_FOLDER / 'tracks' / image_filename


                try:
                    generate_track_image(title=job_payload['title'], scale=job_payload['key'], output_path=image_disk_path)
                except Exception as e:
                        logging.error(f"Error occurred while generating track image: {e}", exc_info=True)
                        redis_client.hset(f"job:{job_payload['job_id']}", mapping={'status': 'error', 'error_message': 'Image generation failed (track_processing.py generate_track_image())'})
                        raise TrackProcessingError(f"Job {job_payload['job_id']} failed during image generation: {e}") from e
            else:

                image_filename = f"{job_payload['title']}_{uuid4().hex[:8]}.png"

                try:
                    # Si une image a été uploadée, on la copie dans le dossier final (db_assets/images/)
                    image_disk_path = Path(config.IMAGES_FOLDER) / 'tracks' / image_filename
                    shutil.copy(job_payload['image_disk_path'], image_disk_path)


                except Exception as e:
                        logging.error(f"Error occurred while copying uploaded image: {e}", exc_info=True)
                        redis_client.hset(f"job:{job_payload['job_id']}", mapping={'status': 'error', 'error_message': 'Image copying failed (track_processing.py shutil.copy())'})
                        raise TrackProcessingError(f"Job {job_payload['job_id']} failed during image copying: {e}") from e


            selected_tags = db.session.query(Tag).filter(Tag.id.in_(job_payload['tag_ids'])).all()
            # Créer le track
            track = Track(
                title=job_payload['title'],
                bpm=job_payload['bpm'],
                key=job_payload['key'],
                style=job_payload['style'],
                price_mp3=job_payload['price_mp3'],
                price_wav=job_payload['price_wav'],
                price_stems=job_payload['price_stems'],
                sacem_percentage_composer=job_payload['sacem_percentage_composer'],
                composer_user=user,
                audio_file=job_payload['preview_filename'],
                file_mp3=job_payload['mp3_filename'],
                file_wav=job_payload['wav_filename'],
                file_stems=job_payload['stems_filename'],
                image_file=f'images/tracks/{image_filename}',
                file_hash=job_payload['file_hash'],
                is_approved=True,
                tags=selected_tags,
                contract_price_exclusive=job_payload.get('contract_price_exclusive'),
                contract_price_duration_3y=job_payload.get('contract_price_duration_3y'),
                contract_price_duration_5y=job_payload.get('contract_price_duration_5y'),
                contract_price_duration_10y=job_payload.get('contract_price_duration_10y'),
                contract_price_lifetime=job_payload.get('contract_price_lifetime'),
                contract_price_mechanical=job_payload.get('contract_price_mechanical'),
                contract_price_public_show=job_payload.get('contract_price_public_show'),
                contract_price_arrangement=job_payload.get('contract_price_arrangement'),
                contract_price_territory_eu=job_payload.get('contract_price_territory_eu'),
                contract_price_territory_world=job_payload.get('contract_price_territory_world'),
            )

            redis_client.hset(f"job:{job_payload['job_id']}", mapping={'status': 'finalizing'})

            user.upload_track_tokens -= 1
            try: 
                db.session.add(track)
                db.session.commit()
                
                redis_client.hset(f"job:{job_payload['job_id']}", mapping={'status': 'done', 'track_id': str(track.id)})
                redis_client.expire(f"job:{job_payload['job_id']}", 3600)  
            except Exception as e:
                db.session.rollback()
                logging.error(f"Database error during track creation: {e}", exc_info=True)
                redis_client.hset(f"job:{job_payload['job_id']}", mapping={'status': 'error', 'error_message': 'Database error during track creation'})
                raise TrackProcessingError(f"Job {job_payload['job_id']} failed during database operations: {e}") from e
            

    except TrackProcessingError:
        raise

    except Exception as e:
        # Le with app_context() est déjà fermé ici — on ouvre un nouveau contexte
        # minimal juste pour le rollback, puis on log et on remonte l'erreur.
        logging.error(f"Unexpected error in track processing job: {e}", exc_info=True)
        redis_client.hset(f"job:{job_payload['job_id']}", mapping={'status': 'error', 'error_message': 'Unexpected error during track processing'})
        try:
            with flask_app.app_context():
                db.session.rollback()
        except Exception:
            pass  # rollback best-effort — ne pas masquer l'erreur originale
        raise TrackProcessingError(f"Job {job_payload['job_id']} failed with unexpected error: {e}") from e