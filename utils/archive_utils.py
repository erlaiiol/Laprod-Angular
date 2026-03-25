"""
Utilitaires pour manipuler les archives (zip, rar)
"""
import zipfile
import rarfile
from pathlib import Path
from typing import List, Dict, Optional


def get_archive_file_tree(archive_path: str) -> Optional[List[Dict]]:
    """
    Extrait l'arborescence des fichiers d'une archive zip ou rar.

    Args:
        archive_path: Chemin vers l'archive

    Returns:
        Liste de dictionnaires contenant les informations sur chaque fichier:
        - name: nom du fichier
        - size: taille en octets
        - is_dir: True si c'est un dossier
        - path: chemin complet dans l'archive

        None si l'archive ne peut pas être lue
    """
    path = Path(archive_path)

    if not path.exists():
        return None

    file_tree = []

    try:
        # Déterminer le type d'archive
        if path.suffix.lower() == '.zip':
            with zipfile.ZipFile(archive_path, 'r') as archive:
                for info in archive.filelist:
                    # Ignorer les fichiers système macOS
                    if '__MACOSX' in info.filename or info.filename.startswith('.'):
                        continue

                    file_tree.append({
                        'name': Path(info.filename).name,
                        'path': info.filename,
                        'size': info.file_size,
                        'is_dir': info.is_dir(),
                        'compressed_size': info.compress_size
                    })

        elif path.suffix.lower() == '.rar':
            with rarfile.RarFile(archive_path, 'r') as archive:
                for info in archive.infolist():
                    # Ignorer les fichiers système
                    if '__MACOSX' in info.filename or info.filename.startswith('.'):
                        continue

                    file_tree.append({
                        'name': Path(info.filename).name,
                        'path': info.filename,
                        'size': info.file_size,
                        'is_dir': info.isdir(),
                        'compressed_size': info.compress_size
                    })

        else:
            return None

        # Trier par chemin pour avoir une arborescence cohérente
        file_tree.sort(key=lambda x: x['path'])

        return file_tree

    except Exception as e:
        from flask import current_app
        current_app.logger.error(f"Erreur lecture archive {archive_path}: {e}", exc_info=True)
        return None


def format_file_size(size_bytes: int) -> str:
    """
    Formatte une taille en octets en format lisible.

    Args:
        size_bytes: Taille en octets

    Returns:
        String formaté (ex: "1.5 MB")
    """
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


def check_file_naming_convention(file_tree: List[Dict]) -> Dict[str, any]:
    """
    Vérifie si les fichiers audio respectent la convention de nommage.
    Convention: [NOM INSTRUMENT] | [EFFETS/INTENTIONS] | [VOLUME/IMPORTANCE]

    Args:
        file_tree: Liste des fichiers de l'archive

    Returns:
        Dictionnaire avec:
        - audio_files: liste des fichiers audio
        - properly_named: nombre de fichiers bien nommés
        - improperly_named: liste des fichiers mal nommés
        - total_audio: nombre total de fichiers audio
    """
    audio_extensions = {'.wav', '.mp3', '.flac', '.aiff', '.ogg', '.m4a'}

    audio_files = []
    properly_named = 0
    improperly_named = []

    for file_info in file_tree:
        if file_info['is_dir']:
            continue

        file_path = Path(file_info['path'])

        # Vérifier si c'est un fichier audio
        if file_path.suffix.lower() in audio_extensions:
            audio_files.append(file_info)

            # Vérifier la convention de nommage (contient au moins 2 pipes |)
            if file_info['name'].count('|') >= 2:
                properly_named += 1
            else:
                improperly_named.append(file_info)

    return {
        'audio_files': audio_files,
        'properly_named': properly_named,
        'improperly_named': improperly_named,
        'total_audio': len(audio_files)
    }
