"""
Utilitaires pour le traitement des archives de stems FL Studio.
"""
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def extract_primary_from_stems(archive_path, target_dir, safe_title, unique_id):
    """
    Extrait le fichier audio principal (*_current.* ou *_master.* en fallback) d'une
    archive de stems FL Studio (ZIP ou RAR).

    Priorité : *_current.* > *_master.*

    Args:
        archive_path : chemin vers l'archive (str ou Path)
        target_dir   : dossier de destination (str ou Path)
        safe_title   : titre sécurisé pour nommage du fichier extrait
        unique_id    : identifiant unique pour nommage

    Returns:
        (Path, str, str) → (chemin absolu extrait, filename, extension .wav/.mp3)
        (None, None, None) si aucun fichier trouvé ou erreur
    """
    import zipfile
    import rarfile
    import magic as _magic

    archive_path = Path(archive_path)
    target_dir = Path(target_dir)

    try:
        with open(archive_path, 'rb') as fh:
            header = fh.read(2048)
        mime = _magic.from_buffer(header, mime=True)
    except Exception as e:
        logger.error(f"Lecture entête archive échouée ({archive_path.name}): {e}")
        return None, None, None

    def _pick_and_extract(archive):
        names = archive.namelist()
        audio_files = [
            n for n in names
            if not n.endswith('/') and not n.startswith('__MACOSX')
        ]
        current_files = [n for n in audio_files if '_current.' in Path(n).name.lower()]
        master_files  = [n for n in audio_files if '_master.'  in Path(n).name.lower()]

        chosen = current_files[0] if current_files else (master_files[0] if master_files else None)
        if not chosen:
            return None, None, None

        ext = Path(chosen).suffix.lower()
        out_name = f"{safe_title}_{unique_id}_full{ext}"
        out_path = target_dir / out_name
        out_path.write_bytes(archive.read(chosen))
        logger.info(f"Stem extrait : {Path(chosen).name} → {out_name}")
        return out_path, out_name, ext

    try:
        if 'zip' in mime:
            with zipfile.ZipFile(archive_path) as arch:
                return _pick_and_extract(arch)
        elif 'rar' in mime:
            with rarfile.RarFile(str(archive_path)) as arch:
                return _pick_and_extract(arch)
        else:
            logger.error(f"Format d'archive non reconnu : {mime}")
    except Exception as e:
        logger.error(f"Extraction stems échouée ({archive_path.name}): {e}", exc_info=True)

    return None, None, None
