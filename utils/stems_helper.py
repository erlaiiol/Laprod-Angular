"""
Utilitaires pour le traitement des archives de stems FL Studio.
"""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

AUDIO_EXTS = {'.wav', '.mp3', '.aiff', '.aif', '.flac'}


def extract_primary_from_stems(archive_path, target_dir, safe_title, unique_id):
    """
    Extrait le fichier audio principal d'une archive stems FL Studio (ZIP ou RAR).

    Priorité de sélection :
      1. *_current.*  (mix courant FL Studio)
      2. *_master.*   (master mixé)
      3. *current*    (variantes sans underscore ni point)
      4. *master*
      5. Premier WAV disponible (fallback)
      6. Premier fichier audio disponible

    L'ouverture est tentée directement en ZIP, puis en RAR — sans dépendance à
    python-magic, dont le comportement varie selon la config système.

    Returns:
        (Path, str, str) → (chemin absolu extrait, filename, extension .wav/.mp3/…)
        (None, None, None) si aucun fichier utilisable ou erreur
    """
    import zipfile

    archive_path = Path(archive_path)
    target_dir   = Path(target_dir)

    def _pick_and_extract(archive):
        names = archive.namelist()

        audio_files = [
            n for n in names
            if not n.endswith('/')
            and '__macosx' not in n.lower()
            and Path(n).suffix.lower() in AUDIO_EXTS
        ]

        logger.info(
            f"Stems {archive_path.name} — {len(names)} entrées ZIP, "
            f"{len(audio_files)} fichiers audio : "
            f"{[Path(n).name for n in audio_files]}"
        )

        if not audio_files:
            logger.error(
                f"Aucun fichier audio ({', '.join(AUDIO_EXTS)}) "
                f"dans {archive_path.name}. Contenu : {names[:20]}"
            )
            return None, None, None

        def _name(n):
            return Path(n).name.lower()

        # Priorité 1 & 2 : _current. / _master. (underscore + mot + point)
        current_strict = [n for n in audio_files if '_current.' in _name(n)]
        master_strict  = [n for n in audio_files if '_master.'  in _name(n)]

        # Priorité 3 & 4 : "current" / "master" n'importe où dans le nom
        current_loose = [n for n in audio_files if 'current' in _name(n)]
        master_loose  = [n for n in audio_files if 'master'  in _name(n)]

        # Priorité 5 : premier WAV
        wav_files  = [n for n in audio_files if Path(n).suffix.lower() == '.wav']

        if current_strict:
            chosen, reason = current_strict[0], '_current.'
        elif master_strict:
            chosen, reason = master_strict[0], '_master.'
        elif current_loose:
            chosen, reason = current_loose[0], 'current (loose)'
        elif master_loose:
            chosen, reason = master_loose[0], 'master (loose)'
        elif wav_files:
            chosen, reason = wav_files[0], 'premier WAV (fallback)'
        else:
            chosen, reason = audio_files[0], 'premier audio (fallback)'

        logger.info(f"Fichier sélectionné [{reason}] : {Path(chosen).name}")

        ext      = Path(chosen).suffix.lower()
        out_name = f"{safe_title}_{unique_id}_full{ext}"
        out_path = target_dir / out_name
        out_path.write_bytes(archive.read(chosen))
        logger.info(f"Stem extrait → {out_name}")
        return out_path, out_name, ext

    # ── Essai ZIP (sans dépendance à python-magic) ────────────────────────────
    try:
        with zipfile.ZipFile(archive_path) as arch:
            return _pick_and_extract(arch)
    except zipfile.BadZipFile:
        logger.info(f"{archive_path.name} : pas un ZIP valide, essai RAR…")
    except Exception as e:
        logger.error(f"Extraction ZIP échouée ({archive_path.name}) : {e}", exc_info=True)
        return None, None, None

    # ── Fallback RAR ─────────────────────────────────────────────────────────
    try:
        import rarfile
        with rarfile.RarFile(str(archive_path)) as arch:
            return _pick_and_extract(arch)
    except ImportError:
        logger.error("rarfile non installé — impossible de traiter les archives RAR")
    except Exception as e:
        logger.error(f"Extraction RAR échouée ({archive_path.name}) : {e}", exc_info=True)

    return None, None, None
