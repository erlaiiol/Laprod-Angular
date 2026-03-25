"""
Validation sécurisée des fichiers uploadés
"""
import config
import magic
import os
import zipfile
import rarfile
from werkzeug.utils import secure_filename
from pathlib import Path
import re

class FileValidator:
    """Validateur de fichiers avec vérification MIME type"""
    
    # MIME types autorisés pour LaProd
    ALLOWED_AUDIO_MIMES = {
        'audio/mpeg',        # MP3
        'audio/wav',         # WAV
        'audio/x-wav',       # WAV (variant)
        'audio/wave',        # WAV (variant)
        'audio/ogg',         # OGG
        'audio/flac',        # FLAC
        'audio/x-flac',      # FLAC (variant)
        'audio/webm',        # WebM (enregistrements navigateur Chrome/Edge)
        'video/webm',        # WebM (variant - parfois détecté comme video)
    }
    
    ALLOWED_IMAGE_MIMES = {
        'image/jpeg',        # JPEG/JPG
        'image/png',         # PNG
        'image/gif',         # GIF
        'image/webp',        # WEBP
    }
    
    ALLOWED_ARCHIVE_MIMES = {
        'application/zip',               # ZIP
        'application/x-zip-compressed',  # ZIP (variant)
        'application/x-rar-compressed',  # RAR
        'application/x-rar',             # RAR (variant)
    }
    
    # Tailles (en octets)
    MAX_AUDIO_SIZE = config.MAX_AUDIO_SIZE
    MIN_MP3_SIZE = config.MIN_MP3_SIZE
    MIN_WAV_SIZE = config.MIN_WAV_SIZE
    MIN_STEMS_SIZE = config.MIN_STEMS_SIZE
    MAX_IMAGE_SIZE = config.MAX_IMAGE_SIZE
    MAX_TOPLINE_SIZE = config.MAX_TOPLINE_SIZE
    MAX_ARCHIVE_SIZE = config.MAX_ARCHIVE_SIZE

    @staticmethod
    def validate_filename(filename):
        """
        Valider qu'un nom de fichier ne contient que des caractères sûrs

        Protection contre Path Traversal en complément de secure_filename()

        Args:
            filename: Nom de fichier (déjà passé dans secure_filename())

        Returns:
            str: Le nom de fichier validé

        Raises:
            ValueError: Si le nom contient des caractères dangereux

        Usage:
            safe_title = secure_filename(title)[:30]
            validated_title = FileValidator.validate_filename(safe_title)
        """
        if not filename:
            raise ValueError("Nom de fichier vide")

        # Vérifier que le nom ne contient que des caractères alphanumériques, tirets et underscores
        if not re.match(r'^[a-zA-Z0-9_-]+$', filename):
            raise ValueError(f"Nom de fichier invalide: '{filename}'. Seuls les lettres, chiffres, tirets et underscores sont autorisés.")

        # Vérifier que le nom n'est pas trop court (éviter des noms comme '-' ou '_')
        if len(filename) < 2:
            raise ValueError("Nom de fichier trop court (minimum 2 caractères)")

        # Vérifier que le nom n'est pas trop long
        if len(filename) > 100:
            raise ValueError("Nom de fichier trop long (maximum 100 caractères)")

        return filename

    @staticmethod
    def validate_audio(file):
        """
        Valider un fichier audio
        
        Args:
            file: Objet FileStorage de Flask
            
        Returns:
            tuple: (is_valid, error_message)
        """
        # Vérifier que le fichier existe
        if not file or not file.filename:
            return False, "Aucun fichier fourni"
        
        # Vérifier le nom du fichier
        filename = secure_filename(file.filename)
        if not filename:
            return False, "Nom de fichier invalide"
        
        # Vérifier la taille
        file.seek(0, os.SEEK_END)  # Aller à la fin
        size = file.tell()         # Lire la position (= taille)
        file.seek(0)               # Revenir au début
        
        if size == 0:
            return False, "Le fichier est vide"
        
        if size > FileValidator.MAX_AUDIO_SIZE:
            size_mb = size / (1024 * 1024)
            max_mb = FileValidator.MAX_AUDIO_SIZE / (1024 * 1024)
            return False, f"Fichier trop volumineux ({size_mb:.1f} MB). Maximum : {max_mb} MB"
        
        # Vérifier le MIME type RÉEL
        try:
            # Lire les premiers 2048 octets pour détecter le type
            file_header = file.read(2048)
            file.seek(0)  # Revenir au début pour la suite
            
            mime_type = magic.from_buffer(file_header, mime=True)
            
            if mime_type not in FileValidator.ALLOWED_AUDIO_MIMES:
                return False, f"Type de fichier non autorisé : {mime_type}. Types acceptés : MP3, WAV, OGG, FLAC"
            
            return True, "Fichier audio valide"
            
        except Exception as e:
            return False, f"Erreur lors de la validation : {str(e)}"
    
    @staticmethod
    def validate_image(file):
        """
        Valider un fichier image
        
        Args:
            file: Objet FileStorage de Flask
            
        Returns:
            tuple: (is_valid, error_message)
        """
        if not file or not file.filename:
            return False, "Aucun fichier fourni"
        
        filename = secure_filename(file.filename)
        if not filename:
            return False, "Nom de fichier invalide"
        
        # Vérifier la taille
        file.seek(0, os.SEEK_END)
        size = file.tell()
        file.seek(0)
        
        if size == 0:
            return False, "Le fichier est vide"
        
        if size > FileValidator.MAX_IMAGE_SIZE:
            size_mb = size / (1024 * 1024)
            max_mb = FileValidator.MAX_IMAGE_SIZE / (1024 * 1024)
            return False, f"Image trop volumineuse ({size_mb:.1f} MB). Maximum : {max_mb} MB"
        
        # Vérifier le MIME type
        try:
            file_header = file.read(2048)
            file.seek(0)
            
            mime_type = magic.from_buffer(file_header, mime=True)
            
            if mime_type not in FileValidator.ALLOWED_IMAGE_MIMES:
                return False, f"Type d'image non autorisé : {mime_type}. Types acceptés : JPEG, PNG, GIF, WEBP"
            
            return True, "Image valide"
            
        except Exception as e:
            return False, f"Erreur lors de la validation : {str(e)}"
    
    @staticmethod
    def validate_archive(file):
        """
        Valider un fichier archive (ZIP, RAR pour stems)
        
        Args:
            file: Objet FileStorage de Flask
            
        Returns:
            tuple: (is_valid, error_message)
        """
        if not file or not file.filename:
            return False, "Aucun fichier fourni"
        
        filename = secure_filename(file.filename)
        if not filename:
            return False, "Nom de fichier invalide"
        
        # Vérifier la taille
        file.seek(0, os.SEEK_END)
        size = file.tell()
        file.seek(0)
        
        if size == 0:
            return False, "Le fichier est vide"
        
        if size > FileValidator.MAX_ARCHIVE_SIZE:
            size_mb = size / (1024 * 1024)
            max_mb = FileValidator.MAX_ARCHIVE_SIZE / (1024 * 1024)
            return False, f"Archive trop volumineuse ({size_mb:.1f} MB). Maximum : {max_mb} MB"
        
        # Vérifier le MIME type
        try:
            file_header = file.read(2048)
            file.seek(0)
            
            mime_type = magic.from_buffer(file_header, mime=True)
            
            if mime_type not in FileValidator.ALLOWED_ARCHIVE_MIMES:
                return False, f"Type d'archive non autorisé : {mime_type}. Types acceptés : ZIP, RAR"
            
            return True, "Archive valide"
            
        except Exception as e:
            return False, f"Erreur lors de la validation : {str(e)}"


# Fonctions helper pour usage simple
def validate_audio_file(file):
    """Raccourci pour valider un audio"""
    return FileValidator.validate_audio(file)

def validate_topline_file(file):
    """
    Valider un fichier topline (limite de taille plus stricte: 5 MB pour forcer MP3)

    Args:
        file: Objet FileStorage de Flask

    Returns:
        tuple: (is_valid, error_message)
    """
    # Vérifier que le fichier existe
    if not file or not file.filename:
        return False, "Aucun fichier fourni"

    # Vérifier le nom du fichier
    filename = secure_filename(file.filename)
    if not filename:
        return False, "Nom de fichier invalide"

    # Vérifier la taille (limite plus stricte pour toplines: 5 MB force MP3)
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)

    if size == 0:
        return False, "Le fichier est vide"

    if size > FileValidator.MAX_TOPLINE_SIZE:
        size_mb = size / (1024 * 1024)
        max_mb = FileValidator.MAX_TOPLINE_SIZE / (1024 * 1024)
        return False, f"Topline trop volumineuse ({size_mb:.1f} MB). Maximum : {max_mb} MB (utilisez MP3)"

    # Vérifier le MIME type RÉEL
    try:
        file_header = file.read(2048)
        file.seek(0)

        mime_type = magic.from_buffer(file_header, mime=True)

        if mime_type not in FileValidator.ALLOWED_AUDIO_MIMES:
            return False, f"Type de fichier non autorisé : {mime_type}. Types acceptés : MP3, WAV, OGG, FLAC, WebM"

        return True, "Topline valide"

    except Exception as e:
        return False, f"Erreur lors de la validation : {str(e)}"

def validate_image_file(file):
    """Raccourci pour valider une image"""
    return FileValidator.validate_image(file)

def validate_archive_file(file):
    """Raccourci pour valider une archive"""
    return FileValidator.validate_archive(file)


def validate_specific_audio_format(file, expected_format):
    """
    Valider qu'un fichier audio correspond exactement au format attendu

    Args:
        file: Objet FileStorage de Flask
        expected_format: 'mp3', 'wav', ou 'flac'

    Returns:
        tuple: (is_valid, error_message)
    """
    # Mapping format -> MIME types autorisés
    FORMAT_MIMES = {
        'mp3': {'audio/mpeg'},
        'wav': {'audio/wav', 'audio/x-wav', 'audio/wave'},
        'flac': {'audio/flac', 'audio/x-flac'},
    }

    if expected_format not in FORMAT_MIMES:
        return False, f"Format non supporté : {expected_format}"

    # D'abord, validation audio générale
    is_valid, error_msg = FileValidator.validate_audio(file)
    if not is_valid:
        return False, error_msg

    # Taille minimum (un beat fait au moins ~1min10)
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)

    if expected_format == 'mp3' and size < FileValidator.MIN_MP3_SIZE:
        size_mb = size / (1024 * 1024)
        return False, f"Fichier MP3 trop petit ({size_mb:.1f} MB). Un beat complet doit faire au moins 1.2 MB"

    if expected_format == 'wav' and size < FileValidator.MIN_WAV_SIZE:
        size_mb = size / (1024 * 1024)
        return False, f"Fichier WAV trop petit ({size_mb:.1f} MB). Un beat complet doit faire au moins 10 MB"

    # Vérifier le MIME type spécifique
    try:
        file_header = file.read(2048)
        file.seek(0)

        mime_type = magic.from_buffer(file_header, mime=True)
        allowed_mimes = FORMAT_MIMES[expected_format]

        if mime_type not in allowed_mimes:
            return False, f"Ce fichier n'est pas un {expected_format.upper()} valide (détecté: {mime_type})"

        return True, f"Fichier {expected_format.upper()} valide"

    except Exception as e:
        return False, f"Erreur lors de la validation : {str(e)}"


def validate_stems_archive(file):
    """
    Valider une archive de stems (doit contenir uniquement des fichiers FLAC)

    Args:
        file: Objet FileStorage de Flask (archive ZIP ou RAR)

    Returns:
        tuple: (is_valid, error_message)
    """
    # D'abord, valider que c'est une archive
    is_valid, error_msg = FileValidator.validate_archive(file)
    if not is_valid:
        return False, error_msg

    # Taille minimum pour stems (pistes FLAC separees)
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size < FileValidator.MIN_STEMS_SIZE:
        size_mb = size / (1024 * 1024)
        return False, f"Archive de stems trop petite ({size_mb:.1f} MB). Minimum 40 MB attendu pour des pistes FLAC"

    # Sauvegarder temporairement l'archive pour l'inspecter
    import tempfile

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as tmp_file:
            file.save(tmp_file.name)
            file.seek(0)  # Remettre le curseur au début

            # Déterminer si c'est un ZIP ou un RAR
            file_header = file.read(2048)
            file.seek(0)
            mime_type = magic.from_buffer(file_header, mime=True)

            # Lister les fichiers dans l'archive
            filenames = []

            if 'zip' in mime_type:
                with zipfile.ZipFile(tmp_file.name, 'r') as archive:
                    filenames = archive.namelist()
            elif 'rar' in mime_type:
                with rarfile.RarFile(tmp_file.name, 'r') as archive:
                    filenames = archive.namelist()
            else:
                return False, "Type d'archive non reconnu"

            # Vérifier que tous les fichiers sont des FLAC (ignorer les dossiers)
            audio_files = [f for f in filenames if not f.endswith('/') and not f.startswith('__MACOSX')]

            if len(audio_files) == 0:
                return False, "L'archive ne contient aucun fichier audio"

            non_flac_files = [f for f in audio_files if not f.lower().endswith('.flac')]

            if non_flac_files:
                return False, f"L'archive contient des fichiers non-FLAC : {', '.join(non_flac_files[:3])}"

            return True, f"Archive de stems valide ({len(audio_files)} fichiers FLAC)"

    except zipfile.BadZipFile:
        return False, "Archive ZIP corrompue"
    except rarfile.BadRarFile:
        return False, "Archive RAR corrompue"
    except Exception as e:
        return False, f"Erreur lors de la validation de l'archive : {str(e)}"
    finally:
        # Nettoyer le fichier temporaire
        try:
            os.unlink(tmp_file.name)
        except:
            pass


def validate_audio_duration_match(file_mp3, file_wav, tolerance_ms=2000):
    """
    Vérifier que deux fichiers audio (MP3 et WAV) ont la même durée.
    Tolérance de 2 secondes par défaut (padding MP3).

    Args:
        file_mp3: FileStorage du MP3
        file_wav: FileStorage du WAV
        tolerance_ms: Ecart max autorisé en millisecondes

    Returns:
        tuple: (is_valid, error_message)
    """
    import io
    from pydub import AudioSegment

    try:
        file_mp3.seek(0)
        mp3_segment = AudioSegment.from_file(io.BytesIO(file_mp3.read()), format='mp3')
        file_mp3.seek(0)

        file_wav.seek(0)
        wav_segment = AudioSegment.from_file(io.BytesIO(file_wav.read()), format='wav')
        file_wav.seek(0)

        mp3_duration = len(mp3_segment)
        wav_duration = len(wav_segment)
        diff = abs(mp3_duration - wav_duration)

        if diff > tolerance_ms:
            mp3_sec = mp3_duration / 1000
            wav_sec = wav_duration / 1000
            return False, (
                f"Les fichiers MP3 ({mp3_sec:.1f}s) et WAV ({wav_sec:.1f}s) "
                f"n'ont pas la même durée (écart de {diff / 1000:.1f}s). "
                f"Assurez-vous d'uploader le même beat dans les deux formats."
            )

        return True, "Durées cohérentes"

    except Exception as e:
        return False, f"Impossible de comparer les durées : {str(e)}"