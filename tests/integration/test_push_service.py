"""
Tests d'intégration — utils/push_service.py

Couvre la discipline best-effort (cf. docs/conventions.md § Cache Redis) :
  - send_push() ne fait rien sans push_opt_in, sans jeton actif, sans Firebase configuré
  - send_push() désactive un jeton mort côté FCM (UNREGISTERED) sans le supprimer
  - register_token() est idempotent sur un même jeton
  - deactivate_all_tokens() coupe tous les appareils d'un utilisateur
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

from models import DeviceToken
from utils import push_service


class TestSendPushGating:

    def test_no_push_without_opt_in(self, db, user, mocker):
        user.push_opt_in = False
        db.session.commit()
        mocker.patch('utils.push_service._get_app', return_value=object())

        assert push_service.send_push(user.id, 'Titre', 'Corps') is False

    def test_no_push_without_active_device(self, db, user, mocker):
        user.push_opt_in = True
        db.session.commit()
        mocker.patch('utils.push_service._get_app', return_value=object())

        assert push_service.send_push(user.id, 'Titre', 'Corps') is False

    def test_no_push_when_firebase_not_configured(self, db, user, mocker):
        user.push_opt_in = True
        db.session.add(DeviceToken(user_id=user.id, token='tok-1', platform='android'))
        db.session.commit()
        mocker.patch('utils.push_service._get_app', return_value=None)

        assert push_service.send_push(user.id, 'Titre', 'Corps') is False


class TestSendPushDelivery:

    def _mock_multicast_response(self, results):
        """results: liste de (success: bool, error_code: str | None)."""
        responses = []
        for success, code in results:
            exc = SimpleNamespace(code=code) if code else None
            responses.append(SimpleNamespace(success=success, exception=exc))
        return SimpleNamespace(
            responses=responses,
            success_count=sum(1 for s, _ in results if s),
        )

    def test_successful_send_returns_true(self, db, user, mocker):
        user.push_opt_in = True
        db.session.add(DeviceToken(user_id=user.id, token='tok-ok', platform='android'))
        db.session.commit()

        mocker.patch('utils.push_service._get_app', return_value=object())
        fake_messaging = MagicMock()
        fake_messaging.send_each_for_multicast.return_value = self._mock_multicast_response(
            [(True, None)]
        )
        mocker.patch('firebase_admin.messaging', fake_messaging, create=True)
        result = push_service.send_push(user.id, 'Titre', 'Corps', link='/upload-track')

        assert result is True

    def test_unregistered_token_is_deactivated_not_deleted(self, db, user, mocker):
        user.push_opt_in = True
        db.session.add(DeviceToken(user_id=user.id, token='tok-dead', platform='ios'))
        db.session.commit()

        mocker.patch('utils.push_service._get_app', return_value=object())
        fake_messaging = MagicMock()
        fake_messaging.send_each_for_multicast.return_value = self._mock_multicast_response(
            [(False, 'UNREGISTERED')]
        )
        mocker.patch('firebase_admin.messaging', fake_messaging, create=True)
        result = push_service.send_push(user.id, 'Titre', 'Corps')

        assert result is False
        row = DeviceToken.query.filter_by(token='tok-dead').first()
        assert row is not None            # jamais supprimé
        assert row.is_active is False


class TestRegisterToken:

    def test_register_is_idempotent_on_same_token(self, db, user):
        push_service.register_token(user.id, 'tok-a', 'android')
        db.session.commit()
        push_service.register_token(user.id, 'tok-a', 'android')
        db.session.commit()

        assert DeviceToken.query.filter_by(token='tok-a').count() == 1

    def test_deactivate_all_tokens_covers_every_device(self, db, user):
        push_service.register_token(user.id, 'tok-1', 'android')
        push_service.register_token(user.id, 'tok-2', 'ios')
        db.session.commit()

        push_service.deactivate_all_tokens(user.id)
        db.session.commit()

        actives = DeviceToken.query.filter_by(user_id=user.id, is_active=True).count()
        assert actives == 0
