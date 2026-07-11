"""
Tests unitaires — utils/stems_helper.py

Couvre extract_primary_from_stems() :
  - Priorité *_current.* > *_master.* > premier WAV > premier audio
  - Fallback *_master.* si *_current.* absent
  - (None, None, None) si aucun fichier audio dans l'archive
  - Nommage de sortie : {safe_title}_{unique_id}_full{ext}
  - Tolérance : __MACOSX, sous-dossiers, casse
  - Robustesse : archive vide, fichier non-archive, erreur I/O
"""
import io
import zipfile
import pytest
from pathlib import Path


# ── Helpers ───────────────────────────────────────────────────────────────────

# En-têtes minimaux reconnaissables comme audio (pas besoin d'un vrai flux audio
# — stems_helper n'inspecte pas le contenu, seulement le nom)
FAKE_WAV = b'RIFF$\x00\x00\x00WAVEfmt ' + b'\x00' * 100
FAKE_MP3 = b'\xff\xfb\x90\x00' + b'\x00' * 100


def _make_zip(files: dict, path: Path) -> Path:
    """Crée un ZIP physique à *path* contenant les entrées *files*."""
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_STORED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return path


# ── Tests : cas nominaux ──────────────────────────────────────────────────────

class TestExtractPrimaryHappyPath:

    def test_extracts_current_wav(self, tmp_path):
        """_current.wav extrait, renommé en {title}_{id}_full.wav."""
        archive = _make_zip(
            {'Beat_current.wav': FAKE_WAV, 'Beat_kick.wav': b'\x00' * 50},
            tmp_path / 'stems.zip',
        )
        from utils.stems_helper import extract_primary_from_stems
        out_path, out_name, ext = extract_primary_from_stems(
            archive, tmp_path, 'MyBeat', 'abc123'
        )
        assert out_path is not None
        assert ext == '.wav'
        assert out_name == 'MyBeat_abc123_full.wav'
        assert out_path.exists()

    def test_extracts_current_mp3(self, tmp_path):
        """_current.mp3 extrait — extension .mp3 conservée."""
        archive = _make_zip(
            {'Beat_current.mp3': FAKE_MP3},
            tmp_path / 'stems.zip',
        )
        from utils.stems_helper import extract_primary_from_stems
        _, out_name, ext = extract_primary_from_stems(archive, tmp_path, 'Beat', 'x1')
        assert ext == '.mp3'
        assert out_name == 'Beat_x1_full.mp3'

    def test_fallback_to_master_when_no_current(self, tmp_path):
        """Sans _current.*, _master.* utilisé en fallback."""
        archive = _make_zip(
            {'Beat_master.wav': FAKE_WAV, 'Beat_kick.wav': b'\x00' * 50},
            tmp_path / 'stems.zip',
        )
        from utils.stems_helper import extract_primary_from_stems
        out_path, out_name, ext = extract_primary_from_stems(
            archive, tmp_path, 'Beat', 'yz'
        )
        assert out_path is not None
        assert out_name == 'Beat_yz_full.wav'

    def test_current_beats_master_when_both_present(self, tmp_path):
        """_current.* prioritaire sur _master.* quand les deux sont présents."""
        archive = _make_zip(
            {
                'Beat_current.wav': FAKE_WAV + b'\x01',  # marqueur unique
                'Beat_master.wav':  FAKE_WAV + b'\x02',
            },
            tmp_path / 'stems.zip',
        )
        from utils.stems_helper import extract_primary_from_stems
        out_path, _, _ = extract_primary_from_stems(archive, tmp_path, 'Beat', 'zz')
        assert out_path is not None
        # Le contenu doit correspondre au _current (dernier octet = 0x01)
        assert out_path.read_bytes()[-1:] == b'\x01'

    def test_output_naming_format(self, tmp_path):
        """Vérification du format exact du nom de sortie."""
        archive = _make_zip(
            {'MySong_current.wav': FAKE_WAV},
            tmp_path / 'stems.zip',
        )
        from utils.stems_helper import extract_primary_from_stems
        out_path, out_name, ext = extract_primary_from_stems(
            archive, tmp_path, 'CoolTitle', 'deadbeef'
        )
        assert out_name == 'CoolTitle_deadbeef_full.wav'
        assert out_path == tmp_path / 'CoolTitle_deadbeef_full.wav'

    def test_extracted_file_written_in_target_dir(self, tmp_path):
        """Le fichier extrait est créé dans target_dir, pas ailleurs."""
        archive = _make_zip(
            {'Beat_current.wav': FAKE_WAV},
            tmp_path / 'stems.zip',
        )
        target = tmp_path / 'output'
        target.mkdir()
        from utils.stems_helper import extract_primary_from_stems
        out_path, _, _ = extract_primary_from_stems(archive, target, 'B', 'id1')
        assert out_path.parent == target

    def test_extracted_content_matches_archive_entry(self, tmp_path):
        """Le contenu du fichier extrait correspond exactement à l'entrée de l'archive."""
        content = FAKE_WAV + b'\xAB\xCD\xEF'
        archive = _make_zip(
            {'Beat_current.wav': content},
            tmp_path / 'stems.zip',
        )
        from utils.stems_helper import extract_primary_from_stems
        out_path, _, _ = extract_primary_from_stems(archive, tmp_path, 'B', 'c')
        assert out_path.read_bytes() == content


# ── Tests : filtrage des noms ─────────────────────────────────────────────────

class TestExtractPrimaryFiltering:

    def test_macos_metadata_ignored(self, tmp_path):
        """__MACOSX/_current.wav ne doit pas être sélectionné."""
        archive = _make_zip(
            {
                '__MACOSX/._Beat_current.wav': FAKE_WAV,
                'Beat_master.wav':             FAKE_WAV,
            },
            tmp_path / 'stems.zip',
        )
        from utils.stems_helper import extract_primary_from_stems
        _, out_name, _ = extract_primary_from_stems(archive, tmp_path, 'Beat', 'mac')
        # Doit sélectionner Beat_master.wav, pas le fichier __MACOSX
        assert out_name == 'Beat_mac_full.wav'

    def test_case_insensitive_current_detection(self, tmp_path):
        """_CURRENT. (majuscules) doit être détecté (insensible à la casse)."""
        archive = _make_zip(
            {'BEAT_CURRENT.WAV': FAKE_WAV},
            tmp_path / 'stems.zip',
        )
        from utils.stems_helper import extract_primary_from_stems
        out_path, _, ext = extract_primary_from_stems(archive, tmp_path, 'Beat', 'c1')
        assert out_path is not None
        assert ext == '.wav'

    def test_case_insensitive_master_detection(self, tmp_path):
        """_MASTER. (majuscules) est détecté en fallback."""
        archive = _make_zip(
            {'BEAT_MASTER.WAV': FAKE_WAV},
            tmp_path / 'stems.zip',
        )
        from utils.stems_helper import extract_primary_from_stems
        out_path, _, _ = extract_primary_from_stems(archive, tmp_path, 'Beat', 'm1')
        assert out_path is not None

    def test_subdirectory_file_detected(self, tmp_path):
        """_current.wav dans un sous-dossier du ZIP est également détecté."""
        archive = _make_zip(
            {'Stems/Beat_current.wav': FAKE_WAV},
            tmp_path / 'stems.zip',
        )
        from utils.stems_helper import extract_primary_from_stems
        out_path, out_name, ext = extract_primary_from_stems(
            archive, tmp_path, 'Beat', 's1'
        )
        assert out_path is not None
        assert ext == '.wav'

    def test_non_audio_files_do_not_interfere(self, tmp_path):
        """Les fichiers .fls, .txt, .png dans le ZIP n'interfèrent pas."""
        archive = _make_zip(
            {
                'project.fls':        b'\x00' * 200,
                'readme.txt':         b'Some notes',
                'cover.png':          b'\x89PNG\r\n' + b'\x00' * 100,
                'Beat_current.wav':   FAKE_WAV,
            },
            tmp_path / 'stems.zip',
        )
        from utils.stems_helper import extract_primary_from_stems
        out_path, _, ext = extract_primary_from_stems(archive, tmp_path, 'Beat', 'nf')
        assert out_path is not None
        assert ext == '.wav'


# ── Tests : cas de défaillance ────────────────────────────────────────────────

class TestExtractPrimaryFailures:

    def test_no_current_or_master_falls_back_to_first_wav(self, tmp_path):
        """Sans _current./_master., le premier WAV sert de piste principale
        (priorité 5 du helper) : mieux vaut une preview imparfaite qu'un
        upload en échec."""
        archive = _make_zip(
            {'kick.wav': b'\x00' * 100, 'snare.wav': b'\x00' * 100},
            tmp_path / 'stems.zip',
        )
        from utils.stems_helper import extract_primary_from_stems
        out_path, out_name, ext = extract_primary_from_stems(archive, tmp_path, 'Beat', 'abc')
        assert out_name == 'Beat_abc_full.wav'
        assert ext == '.wav'
        assert out_path.exists()

    def test_no_wav_falls_back_to_first_audio(self, tmp_path):
        """Sans WAV du tout, le premier fichier audio est retenu (priorité 6)."""
        archive = _make_zip(
            {'lead.mp3': FAKE_MP3, 'notes.txt': b'infos'},
            tmp_path / 'stems.zip',
        )
        from utils.stems_helper import extract_primary_from_stems
        out_path, out_name, ext = extract_primary_from_stems(archive, tmp_path, 'Beat', 'abc')
        assert out_name == 'Beat_abc_full.mp3'
        assert ext == '.mp3'
        assert out_path.exists()

    def test_empty_zip_returns_none(self, tmp_path):
        """ZIP vide → (None, None, None)."""
        archive = tmp_path / 'empty.zip'
        with zipfile.ZipFile(archive, 'w'):
            pass
        from utils.stems_helper import extract_primary_from_stems
        result = extract_primary_from_stems(archive, tmp_path, 'Beat', 'empty')
        assert result == (None, None, None)

    def test_non_archive_file_returns_none(self, tmp_path):
        """Fichier non-archive → (None, None, None) sans lever d'exception."""
        fake = tmp_path / 'not_an_archive.zip'
        fake.write_bytes(b'\x00' * 1024)
        from utils.stems_helper import extract_primary_from_stems
        result = extract_primary_from_stems(fake, tmp_path, 'Beat', 'x')
        assert result == (None, None, None)

    def test_missing_archive_returns_none(self, tmp_path):
        """Chemin inexistant → (None, None, None) sans lever d'exception."""
        from utils.stems_helper import extract_primary_from_stems
        result = extract_primary_from_stems(
            tmp_path / 'ghost.zip', tmp_path, 'Beat', 'g'
        )
        assert result == (None, None, None)

    def test_zip_only_directories_returns_none(self, tmp_path):
        """ZIP ne contenant que des entrées de dossier → (None, None, None)."""
        archive = tmp_path / 'dirs.zip'
        with zipfile.ZipFile(archive, 'w') as zf:
            zf.mkdir('subfolder/')  # dossier uniquement
        from utils.stems_helper import extract_primary_from_stems
        result = extract_primary_from_stems(archive, tmp_path, 'Beat', 'dirs')
        assert result == (None, None, None)

    def test_returns_tuple_of_three_none_not_exception(self, tmp_path):
        """En cas d'erreur, la fonction retourne un tuple, n'est pas censée lever."""
        from utils.stems_helper import extract_primary_from_stems
        # Dossier passé à la place d'une archive
        result = extract_primary_from_stems(tmp_path, tmp_path, 'Beat', 'err')
        assert isinstance(result, tuple)
        assert len(result) == 3
