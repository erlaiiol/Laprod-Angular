"""
Tests de la normalisation de casse du style (utils/styles.py).

Avant resolve_style_casing(), rien n'empêchait "trap" et "Trap" de coexister
comme deux styles distincts dans les filtres — ces tests protègent l'invariant
qu'une seule casse par style survit, quelle que soit la casse saisie ensuite.
"""
from utils.styles import resolve_style_casing


class TestResolveStyleCasing:
    def test_style_inconnu_devient_la_reference(self, db, bound_factories):
        assert resolve_style_casing('Cloud') == 'Cloud'

    def test_reutilise_la_casse_existante_peu_importe_la_saisie(self, db, user, bound_factories):
        from tests.factories.track_factory import TrackFactory
        TrackFactory(composer_id=user.id, style='Trap')
        db.session.commit()

        assert resolve_style_casing('trap')  == 'Trap'
        assert resolve_style_casing('TRAP')  == 'Trap'
        assert resolve_style_casing('tRaP')  == 'Trap'
        assert resolve_style_casing('Trap')  == 'Trap'

    def test_espaces_et_vide(self, db, bound_factories):
        assert resolve_style_casing('  Drill  ') == 'Drill'
        assert resolve_style_casing('')     == ''
        assert resolve_style_casing('   ')  == ''
        assert resolve_style_casing(None)   == ''
