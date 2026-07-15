"""
Tests d'intégration — routes/admin_api.py : toggle_user_role

Couvre le rôle "mix_engineer" (auto-déclaration) ajouté pour que l'admin
puisse le révoquer directement, séparément de "engineer" (certification
is_mixmaster_engineer), et la cascade entre les deux :
  - révoquer mix_engineer doit aussi révoquer la certification et ses dérivés
  - certifier (engineer) exige d'avoir d'abord le rôle mix_engineer déclaré
"""
import pytest

from tests.factories.user_factory import UserFactory


@pytest.fixture()
def target(db, bound_factories):
    u = UserFactory()
    yield u
    existing = db.session.get(type(u), u.id)
    if existing:
        db.session.delete(existing)
        db.session.commit()


class TestToggleMixEngineer:
    def test_active_le_role_declare(self, client, db, admin_headers, target):
        assert target.is_mix_engineer is False
        res = client.post(f'/api/admin/users/{target.id}/toggle-role/mix_engineer',
                          headers=admin_headers)
        assert res.status_code == 200
        db.session.refresh(target)
        assert target.is_mix_engineer is True

    def test_revocation_cascade_sur_la_certification(self, client, db, admin_headers, target):
        target.is_mix_engineer                 = True
        target.is_mixmaster_engineer            = True
        target.is_certified_master_engineer     = True
        target.is_certified_producer_arranger   = True
        db.session.commit()

        res = client.post(f'/api/admin/users/{target.id}/toggle-role/mix_engineer',
                          headers=admin_headers)
        assert res.status_code == 200
        db.session.refresh(target)
        assert target.is_mix_engineer is False
        assert target.is_mixmaster_engineer is False
        assert target.is_certified_master_engineer is False
        assert target.is_certified_producer_arranger is False


class TestToggleEngineerPrerequisite:
    def test_certification_refusee_sans_role_declare(self, client, db, admin_headers, target):
        assert target.is_mix_engineer is False
        res = client.post(f'/api/admin/users/{target.id}/toggle-role/engineer',
                          headers=admin_headers)
        assert res.status_code == 400
        db.session.refresh(target)
        assert target.is_mixmaster_engineer is False

    def test_certification_possible_apres_declaration(self, client, db, admin_headers, target):
        target.is_mix_engineer = True
        db.session.commit()

        res = client.post(f'/api/admin/users/{target.id}/toggle-role/engineer',
                          headers=admin_headers)
        assert res.status_code == 200
        db.session.refresh(target)
        assert target.is_mixmaster_engineer is True
