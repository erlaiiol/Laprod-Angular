"""
Tests unitaires — utils/recommendation_service.py

Stratégie :
  - _listen_weight()   : fonction pure, aucun mock. On teste les 4 zones + chaque frontière.
  - _recency_bonus()   : utilise datetime.now(), on tolère quelques ms avec pytest.approx.
  - score_track()      : fonction pure (zéro appel DB), mocks via SimpleNamespace.
  - build_user_vector(): 3 requêtes DB mockées + redis_client forcé à None.

Vocabulaire rappel :
  completion_ratio  — durée_écoutée / durée_totale (0.0 = rien, 1.0 = tout)
  poids (weight)    — signal de qualité d'une écoute, de -0.2 (skip) à +1.5 (completed)
  vecteur           — dict {gamme: score_cumulé, tag: score_cumulé, ...}
"""

import pytest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock


# ── Helpers de construction ────────────────────────────────────────────────────

def _make_track(key='', style='', bpm=100, tags=None, composer_id=1, created_at=None):
    """
    Track minimal utilisable par score_track() sans SQLAlchemy.
    created_at très ancien par défaut → _recency_bonus() = 0.0 → score prévisible.
    """
    tag_ns = [SimpleNamespace(name=t) for t in (tags or [])]
    return SimpleNamespace(
        key=key,
        style=style,
        bpm=bpm,
        tags=tag_ns,
        composer_id=composer_id,
        created_at=created_at or datetime(2000, 1, 1),
    )


def _make_vector(keys=None, tags=None, styles=None, bpm_center=100.0,
                 duration=120.0, avg_completion=0.5, beatmakers=None):
    """
    Vecteur utilisateur minimal.
    duration=120.0 → pénalité de durée = abs(120-120)/60×0.3 = 0.0 (neutre).
    """
    return {
        'keys':                 keys or {},
        'tags':                 tags or {},
        'styles':               styles or {},
        'preferred_bpm_center': bpm_center,
        'preferred_duration':   duration,
        'avg_completion':       avg_completion,
        'favorite_beatmakers':  beatmakers or {},
    }


def _make_listen_event(track_id, completion_ratio, key='A minor', bpm=90,
                       style='trap', tags=None, composer_id=1, track_duration=180.0):
    """Événement d'écoute simulé pour build_user_vector()."""
    tag_ns = [SimpleNamespace(name=t) for t in (tags or [])]
    track = SimpleNamespace(key=key, style=style, bpm=bpm, tags=tag_ns, composer_id=composer_id)
    ev = MagicMock()
    ev.track_id = track_id
    ev.completion_ratio = completion_ratio
    ev.track_duration = track_duration
    ev.track = track
    return ev


def _setup_vector_db(mocker, events, purchases=None, favorites=None):
    """
    Configure le mock DB pour build_user_vector().

    build_user_vector() fait 3 requêtes :
      1. query(ListenEvent).filter_by(...).order_by(...).limit(...).all()   — chaîne longue
      2. query(Purchase).filter_by(...).all()                               — chaîne courte
      3. query(Favorite).filter_by(...).all()                               — chaîne courte

    Les deux chaînes courtes sont différenciées via side_effect (retour successif).
    redis_client est forcé à None → _apply_redis_correlations() ne fait rien,
    ce qui isole le test de toute dépendance Redis.
    """
    mock_db = mocker.patch('utils.recommendation_service.db')
    mocker.patch('utils.recommendation_service.redis_client', None)

    q = mock_db.session.query.return_value

    # Chaîne longue : ListenEvent
    q.filter_by.return_value.order_by.return_value.limit.return_value.all.return_value = events

    # Chaînes courtes : Purchase puis Favorite (side_effect = liste de retours successifs)
    q.filter_by.return_value.all.side_effect = [purchases or [], favorites or []]

    return mock_db


# ── _listen_weight() ──────────────────────────────────────────────────────────

class TestListenWeight:
    """
    Vérifie les 4 zones de poids et chaque frontière exacte.

    Zones :
      [0.00, 0.10[ → -0.2  (skip)
      [0.10, 0.30[ →  0.3  (early exit)
      [0.30, 0.80[ →  1.0  (engaged)
      [0.80, 1.00] →  1.5  (completed)
    """

    @pytest.mark.parametrize('ratio,expected', [
        (0.00, -0.2),   # skip absolu
        (0.05, -0.2),   # skip milieu
        (0.09, -0.2),   # juste avant la frontière skip/early-exit
        (0.10,  0.3),   # frontière skip → early-exit (incluse dans early-exit)
        (0.20,  0.3),   # early-exit milieu
        (0.29,  0.3),   # juste avant la frontière early-exit/engaged
        (0.30,  1.0),   # frontière early-exit → engaged
        (0.50,  1.0),   # engaged milieu
        (0.79,  1.0),   # juste avant la frontière engaged/completed
        (0.80,  1.5),   # frontière engaged → completed
        (1.00,  1.5),   # completed parfait
    ])
    def test_weight_by_zone(self, ratio, expected):
        from utils.recommendation_service import _listen_weight
        assert _listen_weight(ratio) == expected


# ── _recency_bonus() ──────────────────────────────────────────────────────────

class TestRecencyBonus:
    """
    Décroissance linéaire de 0.5 (jour J) à 0.0 (≥ 30 jours).
    Formule : 0.5 × (1 - age_jours / 30)
    pytest.approx tolère ±0.01 pour absorber les quelques ms entre creation
    et assertion.
    """

    def test_today_gives_max_bonus(self):
        from utils.recommendation_service import _recency_bonus
        bonus = _recency_bonus(datetime.now())
        assert bonus == pytest.approx(0.5, abs=0.01)

    def test_15_days_ago_gives_half_bonus(self):
        from utils.recommendation_service import _recency_bonus
        bonus = _recency_bonus(datetime.now() - timedelta(days=15))
        assert bonus == pytest.approx(0.25, abs=0.01)

    def test_30_days_ago_gives_zero(self):
        from utils.recommendation_service import _recency_bonus
        bonus = _recency_bonus(datetime.now() - timedelta(days=30))
        assert bonus == 0.0

    def test_past_30_days_still_zero(self):
        from utils.recommendation_service import _recency_bonus
        bonus = _recency_bonus(datetime.now() - timedelta(days=60))
        assert bonus == 0.0


# ── score_track() ─────────────────────────────────────────────────────────────

class TestScoreTrack:
    """
    score_track() est une fonction pure : aucun appel DB.
    On utilise _make_track() et _make_vector() pour contrôler chaque entrée.

    Référence des coefficients :
      gamme  × 2.0
      tag    × 1.5  (par tag)
      style  × 1.2
      bpm    - abs(bpm - center) / 50 × 0.5
      durée  - abs(120 - duration_center) / 60 × 0.3
      récence + max 0.5, décroît sur 30 jours
      beatmaker boost × 1.5 (multiplicatif sur le score total)

    Convention dans ces tests : created_at=datetime(2000,1,1) → recency_bonus=0.0.
    duration=120 dans le vecteur → pénalité durée = 0.0.
    bpm_center=100, bpm_track=100 → pénalité BPM = 0.0.
    """

    def test_matching_key_adds_score(self):
        """Gamme correspondante : score += key_score × 2.0."""
        from utils.recommendation_service import score_track
        track = _make_track(key='A minor')
        vector = _make_vector(keys={'A minor': 2.0})
        # 2.0 × 2.0 = 4.0
        assert score_track(track, vector) == pytest.approx(4.0)

    def test_unmatched_key_contributes_nothing(self):
        """Gamme absente du vecteur : contribution nulle."""
        from utils.recommendation_service import score_track
        track = _make_track(key='C major')
        vector = _make_vector(keys={'A minor': 2.0})
        assert score_track(track, vector) == pytest.approx(0.0)

    def test_negative_key_score_lowers_total(self):
        """Vecteur négatif sur une gamme (accumulation de skips) : score diminue."""
        from utils.recommendation_service import score_track
        track = _make_track(key='C major')
        vector = _make_vector(keys={'C major': -0.4})
        # -0.4 × 2.0 = -0.8
        assert score_track(track, vector) == pytest.approx(-0.8)

    def test_each_matching_tag_adds_score(self):
        """Chaque tag du track qui correspond au vecteur ajoute tag_score × 1.5."""
        from utils.recommendation_service import score_track
        track = _make_track(tags=['trap', 'dark'])
        vector = _make_vector(tags={'trap': 1.0, 'dark': 1.0})
        # 1.0×1.5 + 1.0×1.5 = 3.0
        assert score_track(track, vector) == pytest.approx(3.0)

    def test_partial_tag_match_only_counts_present_tags(self):
        """Un tag absent du vecteur ne contribue pas."""
        from utils.recommendation_service import score_track
        track = _make_track(tags=['trap', 'orchestral'])
        vector = _make_vector(tags={'trap': 2.0})
        # 'orchestral' absent → 2.0×1.5 = 3.0 seulement
        assert score_track(track, vector) == pytest.approx(3.0)

    def test_matching_style_adds_score(self):
        """Style correspondant : score += style_score × 1.2."""
        from utils.recommendation_service import score_track
        track = _make_track(style='hip-hop')
        vector = _make_vector(styles={'hip-hop': 2.0})
        # 2.0 × 1.2 = 2.4
        assert score_track(track, vector) == pytest.approx(2.4)

    def test_bpm_penalty_at_50_bpm_distance(self):
        """Écart de 50 BPM exactement → pénalité = 0.5."""
        from utils.recommendation_service import score_track
        track = _make_track(bpm=150)
        vector = _make_vector(bpm_center=100.0)
        # abs(150 - 100) / 50 × 0.5 = 1.0 × 0.5 = 0.5
        assert score_track(track, vector) == pytest.approx(-0.5)

    def test_bpm_exact_match_no_penalty(self):
        """BPM identique au centre → pénalité nulle."""
        from utils.recommendation_service import score_track
        track = _make_track(bpm=100)
        vector = _make_vector(bpm_center=100.0)
        assert score_track(track, vector) == pytest.approx(0.0)

    def test_bpm_penalty_at_25_bpm_distance(self):
        """Écart de 25 BPM → pénalité = 0.25 (moitié de l'écart max)."""
        from utils.recommendation_service import score_track
        track = _make_track(bpm=125)
        vector = _make_vector(bpm_center=100.0)
        # abs(125 - 100) / 50 × 0.5 = 0.5 × 0.5 = 0.25
        assert score_track(track, vector) == pytest.approx(-0.25)

    def test_favorite_beatmaker_multiplies_total_score(self):
        """Beatmaker favori : score total × 1.5 (multiplicatif, pas additif)."""
        from utils.recommendation_service import score_track
        track = _make_track(key='A minor', composer_id=42)
        vector = _make_vector(keys={'A minor': 2.0}, beatmakers={42: 1.0})
        # base = 2.0×2.0 = 4.0 → × 1.5 = 6.0
        assert score_track(track, vector) == pytest.approx(6.0)

    def test_unknown_beatmaker_no_boost(self):
        """Beatmaker non favori : pas de multiplicateur."""
        from utils.recommendation_service import score_track
        track = _make_track(key='A minor', composer_id=99)
        vector = _make_vector(keys={'A minor': 2.0}, beatmakers={42: 1.0})
        # 42 ≠ 99 → pas de boost → 4.0
        assert score_track(track, vector) == pytest.approx(4.0)


# ── build_user_vector() ───────────────────────────────────────────────────────

class TestBuildUserVector:
    """
    Vérifie que build_user_vector() construit correctement le vecteur
    à partir des événements d'écoute.

    Rappel des poids : skip(-0.2) / early-exit(0.3) / engaged(1.0) / completed(1.5)
    Bonus replay : +0.3 si le même track_id apparaît ≥ 3 fois dans les 90 événements.
    BPM moyen : moyenne pondérée sur les écoutes positives (w > 0) uniquement.
    """

    def test_single_completed_listen_sets_key_weight(self, mocker):
        """Une écoute complète (ratio 0.9 → poids 1.5) crédite la gamme."""
        ev = _make_listen_event(track_id=1, completion_ratio=0.9, key='A minor')
        _setup_vector_db(mocker, events=[ev])

        from utils.recommendation_service import build_user_vector
        vec = build_user_vector(user_id=1)

        assert vec['keys']['A minor'] == pytest.approx(1.5)

    def test_single_skip_sets_negative_key_weight(self, mocker):
        """Un skip (ratio 0.05 → poids -0.2) crédite négativement la gamme."""
        ev = _make_listen_event(track_id=1, completion_ratio=0.05, key='D minor')
        _setup_vector_db(mocker, events=[ev])

        from utils.recommendation_service import build_user_vector
        vec = build_user_vector(user_id=1)

        assert vec['keys']['D minor'] == pytest.approx(-0.2)

    def test_two_listens_same_key_accumulate(self, mocker):
        """Deux écoutes sur la même gamme → les poids s'additionnent (1.5 + 1.0 = 2.5)."""
        ev1 = _make_listen_event(track_id=1, completion_ratio=0.9, key='A minor')  # 1.5
        ev2 = _make_listen_event(track_id=2, completion_ratio=0.5, key='A minor')  # 1.0
        _setup_vector_db(mocker, events=[ev1, ev2])

        from utils.recommendation_service import build_user_vector
        vec = build_user_vector(user_id=1)

        assert vec['keys']['A minor'] == pytest.approx(2.5)

    def test_skip_and_complete_same_key_net_weight(self, mocker):
        """Un skip (-0.2) et un completed (+1.5) sur la même gamme → net = 1.3."""
        ev_skip     = _make_listen_event(track_id=1, completion_ratio=0.05, key='G major')
        ev_complete = _make_listen_event(track_id=2, completion_ratio=0.9,  key='G major')
        _setup_vector_db(mocker, events=[ev_skip, ev_complete])

        from utils.recommendation_service import build_user_vector
        vec = build_user_vector(user_id=1)

        assert vec['keys']['G major'] == pytest.approx(1.3)

    def test_different_keys_are_independent(self, mocker):
        """Deux gammes différentes ont des scores indépendants dans le vecteur."""
        ev1 = _make_listen_event(track_id=1, completion_ratio=0.9, key='A minor')
        ev2 = _make_listen_event(track_id=2, completion_ratio=0.5, key='C major')
        _setup_vector_db(mocker, events=[ev1, ev2])

        from utils.recommendation_service import build_user_vector
        vec = build_user_vector(user_id=1)

        assert vec['keys']['A minor'] == pytest.approx(1.5)
        assert vec['keys']['C major'] == pytest.approx(1.0)

    def test_replay_bonus_applied_when_same_track_3_times(self, mocker):
        """
        Même track_id × 3 écoutes → replay_count ≥ 3 → bonus +0.3 sur chaque poids.
        3 écoutes completed : poids par écoute = 1.5 + 0.3 = 1.8 → total = 5.4
        """
        events = [
            _make_listen_event(track_id=1, completion_ratio=0.9, key='A minor')
            for _ in range(3)
        ]
        _setup_vector_db(mocker, events=events)

        from utils.recommendation_service import build_user_vector
        vec = build_user_vector(user_id=1)

        assert vec['keys']['A minor'] == pytest.approx(5.4)

    def test_replay_bonus_not_applied_with_only_2_listens(self, mocker):
        """
        Même track_id × 2 écoutes seulement → replay_count < 3 → pas de bonus.
        2 écoutes completed : 1.5 + 1.5 = 3.0
        """
        events = [
            _make_listen_event(track_id=1, completion_ratio=0.9, key='A minor')
            for _ in range(2)
        ]
        _setup_vector_db(mocker, events=events)

        from utils.recommendation_service import build_user_vector
        vec = build_user_vector(user_id=1)

        assert vec['keys']['A minor'] == pytest.approx(3.0)

    def test_bpm_weighted_average(self, mocker):
        """
        BPM préféré = moyenne pondérée sur les écoutes positives.
        ev1 : BPM=80, poids=1.5 (completed)
        ev2 : BPM=100, poids=1.0 (engaged)
        → (80×1.5 + 100×1.0) / (1.5 + 1.0) = 220 / 2.5 = 88.0
        """
        ev1 = _make_listen_event(track_id=1, completion_ratio=0.9, bpm=80)
        ev2 = _make_listen_event(track_id=2, completion_ratio=0.5, bpm=100)
        _setup_vector_db(mocker, events=[ev1, ev2])

        from utils.recommendation_service import build_user_vector
        vec = build_user_vector(user_id=1)

        assert vec['preferred_bpm_center'] == pytest.approx(88.0)

    def test_skip_excluded_from_bpm_average(self, mocker):
        """
        Un skip (poids < 0) ne contribue PAS au calcul du BPM moyen.
        Seule l'écoute positive compte → BPM = BPM de l'écoute completed.
        """
        ev_skip     = _make_listen_event(track_id=1, completion_ratio=0.05, bpm=60)
        ev_complete = _make_listen_event(track_id=2, completion_ratio=0.9,  bpm=100)
        _setup_vector_db(mocker, events=[ev_skip, ev_complete])

        from utils.recommendation_service import build_user_vector
        vec = build_user_vector(user_id=1)

        assert vec['preferred_bpm_center'] == pytest.approx(100.0)

    def test_empty_events_returns_cold_start_defaults(self, mocker):
        """Sans aucune écoute : valeurs par défaut, vecteurs clés/tags vides."""
        _setup_vector_db(mocker, events=[])

        from utils.recommendation_service import build_user_vector
        vec = build_user_vector(user_id=1)

        assert vec['preferred_bpm_center'] == pytest.approx(100.0)
        assert vec['preferred_duration']   == pytest.approx(180.0)
        assert vec['avg_completion']       == pytest.approx(0.0)
        assert vec['keys']  == {}
        assert vec['tags']  == {}
        assert vec['styles'] == {}

    def test_tag_weights_accumulate_across_tracks(self, mocker):
        """Deux tracks avec le même tag → les poids s'accumulent dans vec['tags']."""
        ev1 = _make_listen_event(track_id=1, completion_ratio=0.9, tags=['trap'])  # 1.5
        ev2 = _make_listen_event(track_id=2, completion_ratio=0.5, tags=['trap'])  # 1.0
        _setup_vector_db(mocker, events=[ev1, ev2])

        from utils.recommendation_service import build_user_vector
        vec = build_user_vector(user_id=1)

        assert vec['tags']['trap'] == pytest.approx(2.5)
