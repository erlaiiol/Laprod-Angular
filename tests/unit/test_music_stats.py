"""
Tests des statistiques scientifico-musicales (utils/music_stats.py).

Vérifie le parsing des tonalités, le bucketing des tempos, et la cohérence des
corrélations croisées (mode×style, tempo×style).
"""
import pytest

from utils.music_stats import (
    _parse_key, _tempo_family, catalog_music_stats, CHROMATIC, TEMPO_FAMILIES,
)


class TestParsing:
    @pytest.mark.parametrize('raw, tonic, mode', [
        ('C major',  'C',  'major'),
        ('A minor',  'A',  'minor'),
        ('F# minor', 'F#', 'minor'),
        ('G# major', 'G#', 'major'),
    ])
    def test_cles_valides(self, raw, tonic, mode):
        assert _parse_key(raw) == (tonic, mode)

    @pytest.mark.parametrize('raw', ['', None, 'C', 'H minor', 'C flat', 'C majeur', 'random'])
    def test_cles_invalides(self, raw):
        assert _parse_key(raw) == (None, None)

    def test_toniques_en_ordre_chromatique(self):
        # C en premier, B en dernier — l'ordre du clavier, pas l'alphabet.
        assert CHROMATIC[0] == 'C' and CHROMATIC[-1] == 'B'
        assert len(CHROMATIC) == 12


class TestTempoFamily:
    @pytest.mark.parametrize('bpm, family', [
        (60,  'Lo-fi / Ambient'),
        (85,  'Boom bap / Soul'),
        (95,  'Hip-hop / Trap lent'),
        (120, 'Trap / Drill'),
        (140, 'Afro / Dance'),
        (175, 'Rapide (DnB, Phonk…)'),
    ])
    def test_bucketing(self, bpm, family):
        assert _tempo_family(bpm) == family

    def test_bornes_exclusives_pas_de_recouvrement(self):
        # 90 tombe dans « Hip-hop » (borne basse incluse), pas dans « Boom bap ».
        assert _tempo_family(89) == 'Boom bap / Soul'
        assert _tempo_family(90) == 'Hip-hop / Trap lent'

    def test_bpm_nul(self):
        assert _tempo_family(0) is None
        assert _tempo_family(None) is None


class TestCatalogStats:
    """catalog_music_stats() lit TOUT le catalogue approuvé. Le fixture db ne fait
    pas de rollback (juste session.remove), donc d'autres tests peuvent laisser des
    tracks : ces tests sont écrits en DELTAS et avec des styles uniques pour être
    robustes à un catalogue non vide, et nettoient ce qu'ils créent."""

    @pytest.fixture()
    def make_track(self, db, user, bound_factories):
        from tests.factories.track_factory import TrackFactory
        created = []

        def _make(**kw):
            t = TrackFactory(composer_user=user, is_approved=True, **kw)
            created.append(t)
            return t

        yield _make
        for t in created:
            db.session.delete(t)
        db.session.commit()

    def test_structure_stable(self, db):
        """La structure est toujours bien formée, quel que soit le contenu :
        12 toniques (axe de barres stable), 2 modes."""
        s = catalog_music_stats()
        assert len(s['keys']) == 12
        assert {k['label'] for k in s['keys']} == set(CHROMATIC)
        assert {m['label'] for m in s['modes']} == {'Mineur', 'Majeur'}
        assert len(s['tempo_families']) == len(TEMPO_FAMILIES)

    def test_repartition_mode_et_tempo_en_delta(self, db, make_track):
        before = catalog_music_stats()
        b_modes = {m['label']: m['value'] for m in before['modes']}
        b_tempo = {t['label']: t['value'] for t in before['tempo_families']}

        make_track(key='A minor', style='Trap', bpm=120)
        make_track(key='C major', style='Trap', bpm=140)
        make_track(key='E minor', style='Drill', bpm=118)
        db.session.commit()

        after = catalog_music_stats()
        a_modes = {m['label']: m['value'] for m in after['modes']}
        a_tempo = {t['label']: t['value'] for t in after['tempo_families']}

        assert after['total_tracks'] - before['total_tracks'] == 3
        assert a_modes['Mineur'] - b_modes['Mineur'] == 2
        assert a_modes['Majeur'] - b_modes['Majeur'] == 1
        assert a_tempo['Trap / Drill'] - b_tempo['Trap / Drill'] == 2   # 120 et 118
        assert a_tempo['Afro / Dance'] - b_tempo['Afro / Dance'] == 1   # 140

    def test_correlation_tempo_par_style(self, db, make_track):
        # Style unique → aucune collision avec des tracks laissés par d'autres tests.
        style = 'DrillTest_ZZ'
        for bpm in (120, 124, 128):   # ≥3 requis pour que la corrélation remonte
            make_track(key='A minor', style=style, bpm=bpm)
        db.session.commit()

        s = catalog_music_stats()
        row = next((r for r in s['avg_tempo_by_style'] if r['style'] == style), None)
        assert row is not None
        assert row['avg_bpm'] == pytest.approx(124.0, abs=0.1)
        assert row['count'] == 3

    def test_correlation_mode_par_style(self, db, make_track):
        style = 'RapTest_ZZ'
        for _ in range(3):
            make_track(key='A minor', style=style, bpm=90)
        db.session.commit()

        s = catalog_music_stats()
        row = next((r for r in s['mode_by_style'] if r['style'] == style), None)
        assert row is not None
        assert row['minor'] == 3 and row['major'] == 0
