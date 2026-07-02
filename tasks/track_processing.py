from uuid import uuid4

import config
from pathlib import Path
import shutil, logging
from extensions import db
from app import create_app
from models import Track, User, Tag, Playlist, playlist_track, SimilarArtist
from sqlalchemy import func
from helpers import generate_track_image

try:
    from utils.audio_processing import apply_watermark_and_trim, convert_to_mp3
    WATERMARK_AVAILABLE = True
    logging.info('\'WATERMARK_AVAILABLE\': utils.audio_processing imported successfully in track_processing.py.')
except ImportError as e:
    logging.error(f"Error importing utils \'WATERMARK_AVAILABLE\' in track_processing.py: {e}")
    WATERMARK_AVAILABLE = False

try:
    from utils.stems_helper import extract_primary_from_stems
    STEMS_HELPER_AVAILABLE = True
except ImportError as e:
    logging.error(f"Error importing utils.stems_helper in track_processing.py: {e}")
    STEMS_HELPER_AVAILABLE = False

class TrackProcessingError(Exception):
    """class custom d'exception pour les erreurs
    de processing de track, afin d'éviter les
    multi-logs d'erreur dans RQ (anciennement RuntimeError)"""
    pass

def process_track_data(job_payload : dict):
    """
    Exécutée par le worker RQ — pas dans un contexte Flask HTTP.
    job_payload contient tout ce que post_track() a préparé :
      - chemins des fichiers uploadés (mp3_disk_path, wav_disk_path, stems_disk_path)
      - données du track (title, bpm, key, ...)
      - user_id / job_id

    Orchestration :
      1. Stems seuls → extraction *_current.* / *_master.*
      2. WAV sans MP3 → conversion WAV → MP3 (pour colonne file_mp3)
      3. Génération du preview watermarqué depuis le meilleur audio disponible
      4. Création Track en DB
    """
    flask_app = create_app()

    # Importer redis_client APRÈS create_app() — init_extensions() l'a initialisé.
    from extensions import redis_client

    try:
        with flask_app.app_context():

            user = db.session.get(User, job_payload['user_id'])
            if not user:
                redis_client.hset(f"job:{job_payload['job_id']}", mapping={'status':'error', 'error_message': 'User not found'})
                return

            redis_client.hset(f"job:{job_payload['job_id']}", mapping={'status': 'started'})

            job_id      = job_payload['job_id']
            safe_title  = job_payload['safe_title']
            unique_id   = job_payload['unique_id']

            mp3_disk_path   = job_payload.get('mp3_disk_path')
            mp3_filename    = job_payload.get('mp3_filename')
            wav_disk_path   = job_payload.get('wav_disk_path')
            wav_filename    = job_payload.get('wav_filename')
            stems_disk_path = job_payload.get('stems_disk_path')

            # ── Étape 1 : stems seuls → extraction *_current.* / *_master.* ──────
            if stems_disk_path and not mp3_disk_path and not wav_disk_path:
                if not STEMS_HELPER_AVAILABLE:
                    redis_client.hset(f"job:{job_id}", mapping={
                        'status': 'error',
                        'error_message': "Impossible d'extraire les stems (module indisponible)"
                    })
                    raise TrackProcessingError(f"Job {job_id}: stems_helper indisponible")

                extracted_path, extracted_name, extracted_ext = extract_primary_from_stems(
                    stems_disk_path, config.UPLOAD_FOLDER, safe_title, unique_id
                )
                if not extracted_path:
                    redis_client.hset(f"job:{job_id}", mapping={
                        'status': 'error',
                        'error_message': (
                            "Aucun fichier *_current.* ni *_master.* trouvé dans l'archive. "
                            "Vérifiez que votre export FL Studio inclut bien ces fichiers."
                        )
                    })
                    raise TrackProcessingError(f"Job {job_id}: pas de fichier primary dans les stems")

                if extracted_ext == '.mp3':
                    mp3_disk_path = str(extracted_path)
                    mp3_filename  = extracted_name
                else:
                    # WAV extrait — sera converti en MP3 à l'étape suivante
                    wav_disk_path = str(extracted_path)
                    wav_filename  = extracted_name

            # ── Étape 2 : WAV sans MP3 → conversion WAV → MP3 ────────────────────
            if wav_disk_path and not mp3_disk_path:
                mp3_filename_conv = f"{safe_title}_{unique_id}_full.mp3"
                mp3_disk_path_conv = config.UPLOAD_FOLDER / mp3_filename_conv

                if WATERMARK_AVAILABLE:
                    success = convert_to_mp3(wav_disk_path, str(mp3_disk_path_conv), bitrate='320k')
                    if success:
                        mp3_disk_path = str(mp3_disk_path_conv)
                        mp3_filename  = mp3_filename_conv
                    else:
                        logging.warning(f"Job {job_id}: conversion WAV→MP3 échouée, preview depuis WAV")
                else:
                    logging.warning(f"Job {job_id}: audio_processing indisponible, pas de conversion WAV→MP3")

            # ── Étape 3 : génération preview watermarqué ──────────────────────────
            # Préférer le MP3 comme source (plus rapide à traiter), fallback WAV
            primary_audio_path = mp3_disk_path or wav_disk_path
            if not primary_audio_path:
                redis_client.hset(f"job:{job_id}", mapping={
                    'status': 'error', 'error_message': 'Aucun fichier audio utilisable'
                })
                raise TrackProcessingError(f"Job {job_id}: aucun audio disponible après extraction")

            preview_disk_path = job_payload['preview_disk_path']

            if WATERMARK_AVAILABLE:
                apply_watermark_and_trim(
                    input_path=primary_audio_path,
                    output_path=preview_disk_path,
                    watermark_path=config.WATERMARK_AUDIO_PATH,
                    preview_duration=config.PREVIEW_DURATION,
                    watermark_positions=config.WATERMARK_INTERVALS)

            if not Path(preview_disk_path).exists():
                logging.warning('preview absente après watermark. Copie du fichier audio original.')
                try:
                    shutil.copy(primary_audio_path, preview_disk_path)
                except Exception as e:
                    logging.error(f"Fallback watermark échoué: {e}", exc_info=True)
                    redis_client.hset(f"job:{job_id}", mapping={
                        'status': 'error', 'error_message': 'Audio processing failed'
                    })
                    raise TrackProcessingError(f"Job {job_id} failed during audio processing: {e}")

            # ── Génération ou copie de l'image ────────────────────────────────────
            image_filename = None

            if job_payload['image_filename'] is None:
                image_filename = f"{job_payload['title']}_{uuid4().hex[:8]}.png"
                image_disk_path = config.IMAGES_FOLDER / 'tracks' / image_filename

                try:
                    generate_track_image(title=job_payload['title'], scale=job_payload['key'], output_path=image_disk_path)
                except Exception as e:
                    logging.error(f"Error occurred while generating track image: {e}", exc_info=True)
                    redis_client.hset(f"job:{job_id}", mapping={'status': 'error', 'error_message': 'Image generation failed (track_processing.py generate_track_image())'})
                    raise TrackProcessingError(f"Job {job_id} failed during image generation: {e}") from e
            else:
                image_filename = f"{job_payload['title']}_{uuid4().hex[:8]}.png"

                try:
                    image_disk_path = Path(config.IMAGES_FOLDER) / 'tracks' / image_filename
                    shutil.copy(job_payload['image_disk_path'], image_disk_path)
                except Exception as e:
                    logging.error(f"Error occurred while copying uploaded image: {e}", exc_info=True)
                    redis_client.hset(f"job:{job_id}", mapping={'status': 'error', 'error_message': 'Image copying failed (track_processing.py shutil.copy())'})
                    raise TrackProcessingError(f"Job {job_id} failed during image copying: {e}") from e

            # ── Création Track en DB ──────────────────────────────────────────────
            selected_tags    = db.session.query(Tag).filter(Tag.id.in_(job_payload['tag_ids'])).all()
            selected_artists = db.session.query(SimilarArtist).filter(
                SimilarArtist.id.in_(job_payload.get('artist_ids', []))
            ).all()

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
                file_mp3=mp3_filename,
                file_wav=wav_filename,
                file_stems=job_payload.get('stems_filename'),
                image_file=f'images/tracks/{image_filename}',
                file_hash=job_payload['file_hash'],
                is_approved=True,
                tags=selected_tags,
                similar_artists=selected_artists,
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

            redis_client.hset(f"job:{job_id}", mapping={'status': 'finalizing'})

            user.upload_track_tokens -= 1
            try:
                db.session.add(track)
                db.session.commit()

                # Ajouter le track aux playlists sélectionnées (propriétaires uniquement)
                playlist_ids = job_payload.get('playlist_ids', [])
                if playlist_ids:
                    playlists = db.session.query(Playlist).filter(
                        Playlist.id.in_(playlist_ids),
                        Playlist.beatmaker_id == user.id,
                    ).all()
                    for pl in playlists:
                        max_pos = db.session.query(func.max(playlist_track.c.position)).filter(
                            playlist_track.c.playlist_id == pl.id
                        ).scalar() or 0
                        db.session.execute(
                            playlist_track.insert().values(
                                playlist_id=pl.id, track_id=track.id, position=max_pos + 1
                            )
                        )
                    db.session.commit()

                redis_client.hset(f"job:{job_id}", mapping={'status': 'done', 'track_id': str(track.id)})
                redis_client.expire(f"job:{job_id}", 3600)
            except Exception as e:
                db.session.rollback()
                logging.error(f"Database error during track creation: {e}", exc_info=True)
                redis_client.hset(f"job:{job_id}", mapping={'status': 'error', 'error_message': 'Database error during track creation'})
                raise TrackProcessingError(f"Job {job_id} failed during database operations: {e}") from e


    except TrackProcessingError:
        raise

    except Exception as e:
        logging.error(f"Unexpected error in track processing job: {e}", exc_info=True)
        redis_client.hset(f"job:{job_payload['job_id']}", mapping={'status': 'error', 'error_message': 'Unexpected error during track processing'})


def regenerate_preview(track_id: int, primary_audio_path: str, new_preview_path: str, new_preview_filename: str) -> None:
    """
    Régénère le preview watermarqué d'un track existant. Exécutée par RQ.

    Réutilise apply_watermark_and_trim() (même pipeline que l'upload initial).
    Met à jour track.audio_file en DB et supprime l'ancien fichier preview.
    """
    flask_app = create_app()

    try:
        if WATERMARK_AVAILABLE:
            apply_watermark_and_trim(
                input_path=primary_audio_path,
                output_path=new_preview_path,
                watermark_path=config.WATERMARK_AUDIO_PATH,
                preview_duration=config.PREVIEW_DURATION,
                watermark_positions=config.WATERMARK_INTERVALS,
            )
        if not Path(new_preview_path).exists():
            logging.warning(f'Preview absente après watermark (track {track_id}). Copie du fichier source.')
            shutil.copy(primary_audio_path, new_preview_path)

    except Exception as e:
        logging.error(f"Erreur génération preview (track {track_id}): {e}", exc_info=True)
        try:
            shutil.copy(primary_audio_path, new_preview_path)
        except Exception as copy_err:
            logging.error(f"Fallback preview échoué (track {track_id}): {copy_err}")
            return

    with flask_app.app_context():
        track = db.session.get(Track, track_id)
        if not track:
            logging.error(f"Track {track_id} introuvable lors de la mise à jour du preview.")
            return

        old_preview = config.UPLOAD_FOLDER / track.audio_file
        track.audio_file = new_preview_filename
        db.session.commit()

        if old_preview.exists() and old_preview.name != new_preview_filename:
            try:
                old_preview.unlink()
            except Exception as e:
                logging.warning(f"Impossible de supprimer l'ancien preview (track {track_id}): {e}")
        try:
            with flask_app.app_context():
                db.session.rollback()
        except Exception:
            pass
        raise TrackProcessingError(f"Job {job_payload['job_id']} failed with unexpected error: {e}") from e
