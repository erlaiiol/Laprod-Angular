# utils/audio_processing.py
"""
Module de traitement audio pour watermarking et découpe
Utilise pydub avec ffmpeg pour l'encodage/décodage
"""

from pydub import AudioSegment
from pathlib import Path
from flask import current_app
import config


def apply_watermark_and_trim(input_path, output_path, watermark_path=None,
                            preview_duration=90, watermark_positions=[15, 30, 70]):
    """
    Applique un watermark et découpe à 1:30 (90 secondes)

    Args:
        input_path: Fichier audio source (MP3, WAV, etc.)
        output_path: Fichier de sortie (MP3)
        watermark_path: Fichier watermark à insérer (défaut: config.WATERMARK_AUDIO_PATH)
        preview_duration: Durée du preview en secondes (défaut: 70)
        watermark_positions: Liste des positions en secondes où insérer le watermark

    Returns:
        bool: True si succès, False si erreur
    """
    try:
        # Utiliser le watermark par défaut depuis config si non spécifié
        if watermark_path is None:
            watermark_path = config.WATERMARK_AUDIO_PATH

        current_app.logger.info(f"Traitement audio: {Path(input_path).name}")

        # Vérifier que le fichier source existe
        if not Path(input_path).exists():
            current_app.logger.error(f"Fichier source introuvable: {input_path}")
            return False

        # Charger l'audio principal
        audio = AudioSegment.from_file(input_path)
        current_app.logger.debug(f"Audio charge: {len(audio)/1000:.1f}s, {audio.frame_rate}Hz")

        # Charger et appliquer le watermark si le fichier existe
        if Path(watermark_path).exists():
            watermark = AudioSegment.from_file(watermark_path)

            # Réduire le volume du watermark pour qu'il ne soit pas trop fort
            watermark = watermark + 5  # Augmenter de 2dB
            current_app.logger.debug(f"Watermark charge: {len(watermark)/1000:.1f}s")

            # Insérer aux positions définies
            for position_sec in watermark_positions:
                position_ms = position_sec * 1000

                # Vérifier que la position est dans la durée de l'audio
                if position_ms < len(audio):
                    current_app.logger.debug(f"Insertion watermark a {position_sec}s")
                    audio = audio.overlay(watermark, position=position_ms)
                else:
                    current_app.logger.warning(f"Position {position_sec}s hors limite, ignoree")
        else:
            current_app.logger.warning(f"Watermark introuvable: {watermark_path}, preview sans watermark")

        # Découper à la durée spécifiée
        preview_ms = preview_duration * 1000
        if len(audio) > preview_ms:
            current_app.logger.debug(f"Decoupe a {preview_duration}s")
            preview = audio[:preview_ms]
        else:
            current_app.logger.warning(f"Audio plus court que {preview_duration}s, pas de decoupe")
            preview = audio

        # Fade out sur les 2 dernières secondes pour une fin propre
        current_app.logger.debug("Application du fade-out (2s)")
        preview = preview.fade_out(2000)

        # Créer le dossier de sortie si nécessaire
        output_dir = Path(output_path).parent
        if output_dir and not output_dir.exists():
            output_dir.mkdir(parents=True, exist_ok=True)
            current_app.logger.debug(f"Dossier cree: {output_dir}")

        # Exporter en MP3 avec qualité correcte
        current_app.logger.debug(f"Export vers: {Path(output_path).name}")
        preview.export(
            output_path,
            format="mp3",
            bitrate="192k",  # Bonne qualité pour preview
            parameters=["-q:a", "2"]  # Qualité VBR élevée
        )

        # Vérifier que le fichier a bien été créé
        if Path(output_path).exists():
            file_size = Path(output_path).stat().st_size
            current_app.logger.info(f"Preview creee: {file_size/1024:.1f} KB")
            return True
        else:
            current_app.logger.error("Le fichier de sortie n'a pas ete cree")
            return False

    except Exception as e:
        current_app.logger.error(f"Erreur traitement audio: {e}", exc_info=True)

        # En cas d'erreur, essayer de copier le fichier original comme fallback
        try:
            import shutil
            current_app.logger.info("Tentative de copie du fichier original comme fallback")
            shutil.copy(input_path, output_path)
            current_app.logger.warning("Preview creee sans watermark (erreur de traitement)")
            return False
        except Exception as copy_error:
            current_app.logger.error(f"Impossible de copier le fichier: {copy_error}", exc_info=True)
            return False


def convert_to_mp3(input_path, output_path, bitrate="192k"):
    """
    Convertit un fichier audio en MP3

    Args:
        input_path: Fichier audio source
        output_path: Fichier MP3 de sortie
        bitrate: Bitrate de sortie (défaut: 192k)

    Returns:
        bool: True si succès, False si erreur
    """
    try:
        current_app.logger.debug(f"Conversion MP3: {Path(input_path).name} -> {Path(output_path).name}")

        audio = AudioSegment.from_file(input_path)
        audio.export(output_path, format="mp3", bitrate=bitrate)

        current_app.logger.debug("Conversion reussie")
        return True

    except Exception as e:
        current_app.logger.error(f"Erreur conversion MP3: {e}", exc_info=True)
        return False


def get_audio_duration(audio_path):
    """
    Récupère la durée d'un fichier audio en secondes

    Args:
        audio_path: Chemin vers le fichier audio

    Returns:
        float: Durée en secondes, ou None si erreur
    """
    try:
        audio = AudioSegment.from_file(audio_path)
        duration_seconds = len(audio) / 1000.0
        return duration_seconds
    except Exception as e:
        current_app.logger.error(f"Erreur lecture duree audio: {e}", exc_info=True)
        return None
