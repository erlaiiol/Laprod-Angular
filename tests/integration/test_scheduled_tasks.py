"""
Tests d'intégration — tâches planifiées (scheduled_tasks.py)

Couvre :
  - run_expiry_notifications() : envoie pour les licences à J-7, pas pour J-91
  - run_expiry_notifications() : pas de doublon si appelé deux fois le même jour
  - run_sole_licensee_notifications() : envoie si 1 seul acheteur sur le track
  - run_sole_licensee_notifications() : n'envoie pas si 2 acheteurs
  - run_contract_expiry_update() : passe license_status='expired', libère exclusivité
"""
import uuid
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

from tests.factories import bound_factories  # noqa: F401
from tests.scenarios.users import user_free  # noqa: F401
from tests.scenarios.tracks import track_default_prices  # noqa: F401


# ── Helpers de fixtures ───────────────────────────────────────────────────────

def _make_purchase(db, bound_factories, track, is_exclusive=False,
                   expires_in_days: int | None = None, buyer_suffix: str = ''):
    from tests.factories.user_factory import UserFactory
    from tests.factories.purchase_factory import PurchaseFactory
    uid = uuid.uuid4().hex[:8]
    buyer = UserFactory(
        email=f'sched_{buyer_suffix}_{uid}@test.fr',
        username=f'sched_{buyer_suffix}_{uid}',
    )
    db.session.commit()

    expires_at = None
    if expires_in_days is not None:
        expires_at = datetime.now() + timedelta(days=expires_in_days)

    p = PurchaseFactory(
        track_id=track.id,
        buyer_id=buyer.id,
        license_status='active',
        is_exclusive=is_exclusive,
        is_lifetime=(expires_in_days is None),
        duration_years=None if expires_in_days is None else 3,
        expires_at=expires_at,
        territory='France',
    )
    db.session.commit()
    return buyer, p


# ── run_expiry_notifications ──────────────────────────────────────────────────

class TestRunExpiryNotifications:

    def test_sends_notification_for_expiring_in_7_days(
        self, app, db, bound_factories, track_default_prices
    ):
        buyer, purchase = _make_purchase(
            db, bound_factories, track_default_prices, expires_in_days=7, buyer_suffix='exp7'
        )

        notified_ids: list[int] = []

        def _capture(p, days): notified_ids.append(p.id)

        with patch('utils.notification_service.notify_expiry_approaching', side_effect=_capture), \
             patch('utils.email_service.send_expiry_reminder_email'):
            from utils.scheduled_tasks import run_expiry_notifications
            run_expiry_notifications(app)

        assert purchase.id in notified_ids

    def test_no_notification_for_expiring_in_91_days(
        self, app, db, bound_factories, track_default_prices
    ):
        buyer, purchase = _make_purchase(
            db, bound_factories, track_default_prices, expires_in_days=91, buyer_suffix='exp91'
        )

        notified_ids: list[int] = []

        def _capture(p, days): notified_ids.append(p.id)

        with patch('utils.notification_service.notify_expiry_approaching', side_effect=_capture), \
             patch('utils.email_service.send_expiry_reminder_email'):
            from utils.scheduled_tasks import run_expiry_notifications
            run_expiry_notifications(app)

        assert purchase.id not in notified_ids

    def test_no_duplicate_on_second_run(
        self, app, db, bound_factories, track_default_prices
    ):
        buyer, purchase = _make_purchase(
            db, bound_factories, track_default_prices, expires_in_days=7, buyer_suffix='dedup'
        )

        notified_ids: list[int] = []

        def _capture(p, days): notified_ids.append(p.id)

        with patch('utils.notification_service.notify_expiry_approaching', side_effect=_capture), \
             patch('utils.email_service.send_expiry_reminder_email'):
            from utils.scheduled_tasks import run_expiry_notifications
            run_expiry_notifications(app)
            count_first = notified_ids.count(purchase.id)
            run_expiry_notifications(app)
            count_second = notified_ids.count(purchase.id)

        # Le deuxième run ne ré-envoie pas pour le même purchase le même jour
        assert count_second == count_first


# ── run_sole_licensee_notifications ──────────────────────────────────────────

class TestRunSoleLicenseeNotifications:

    def test_sends_notification_when_sole_licensee(
        self, app, db, bound_factories, track_default_prices
    ):
        buyer, purchase = _make_purchase(
            db, bound_factories, track_default_prices, expires_in_days=30, buyer_suffix='sole'
        )

        notified_ids: list[int] = []
        def _capture(p): notified_ids.append(p.id)

        with patch('utils.notification_service.notify_sole_licensee_monthly', side_effect=_capture), \
             patch('utils.email_service.send_sole_licensee_email'):
            from utils.scheduled_tasks import run_sole_licensee_notifications
            run_sole_licensee_notifications(app)

        assert purchase.id in notified_ids

    def test_no_notification_when_two_buyers(
        self, app, db, bound_factories, track_default_prices
    ):
        buyer1, p1 = _make_purchase(
            db, bound_factories, track_default_prices, expires_in_days=30, buyer_suffix='dual1'
        )
        buyer2, p2 = _make_purchase(
            db, bound_factories, track_default_prices, expires_in_days=30, buyer_suffix='dual2'
        )

        notified_ids: list[int] = []
        def _capture(p): notified_ids.append(p.id)

        with patch('utils.notification_service.notify_sole_licensee_monthly', side_effect=_capture), \
             patch('utils.email_service.send_sole_licensee_email'):
            from utils.scheduled_tasks import run_sole_licensee_notifications
            run_sole_licensee_notifications(app)

        assert p1.id not in notified_ids
        assert p2.id not in notified_ids

    def test_no_duplicate_sole_notification(
        self, app, db, bound_factories, track_default_prices
    ):
        buyer, purchase = _make_purchase(
            db, bound_factories, track_default_prices, expires_in_days=30, buyer_suffix='sole_dedup'
        )

        notified_ids: list[int] = []
        def _capture(p): notified_ids.append(p.id)

        with patch('utils.notification_service.notify_sole_licensee_monthly', side_effect=_capture), \
             patch('utils.email_service.send_sole_licensee_email'):
            from utils.scheduled_tasks import run_sole_licensee_notifications
            run_sole_licensee_notifications(app)
            count_first = notified_ids.count(purchase.id)
            run_sole_licensee_notifications(app)
            count_second = notified_ids.count(purchase.id)

        assert count_second == count_first


# ── run_contract_expiry_update ────────────────────────────────────────────────

class TestRunContractExpiryUpdate:

    def test_expires_overdue_non_exclusive_license(
        self, app, db, bound_factories, track_default_prices
    ):
        buyer, purchase = _make_purchase(
            db, bound_factories, track_default_prices, expires_in_days=-1, buyer_suffix='expired'
        )

        with patch('utils.notification_service.notify_license_expired'), \
             patch('utils.email_service.send_expiry_reminder_email'):
            from utils.scheduled_tasks import run_contract_expiry_update
            run_contract_expiry_update(app)

        from models import Purchase
        db.session.refresh(purchase)
        assert purchase.license_status == 'expired'

    def test_expires_exclusive_and_resets_track(
        self, app, db, bound_factories, track_default_prices
    ):
        from models import Track
        # Marquer le track en exclusif vendu
        track = db.session.get(Track, track_default_prices.id)
        track.is_exclusive_sold = True
        db.session.commit()

        buyer, purchase = _make_purchase(
            db, bound_factories, track_default_prices,
            is_exclusive=True, expires_in_days=-1, buyer_suffix='excl_exp'
        )
        purchase.buyer_id = buyer.id
        track.exclusive_buyer_id = buyer.id
        db.session.commit()

        with patch('utils.notification_service.notify_license_expired'), \
             patch('utils.notification_service.notify_exclusive_license_expired'), \
             patch('utils.email_service.send_expiry_reminder_email'):
            from utils.scheduled_tasks import run_contract_expiry_update
            run_contract_expiry_update(app)

        from models import Purchase
        db.session.refresh(purchase)
        assert purchase.license_status == 'expired'

        db.session.refresh(track)
        assert track.is_exclusive_sold is False
        assert track.exclusive_buyer_id is None


# ── run_premium_expiry_downgrade ──────────────────────────────────────────────

class TestRunPremiumExpiryDowngrade:

    def _make_lapsed_user(self, db, bound_factories, plan='pro', expires_in_days=-1):
        from tests.factories.user_factory import UserFactory
        u = UserFactory(
            subscription_plan=plan,
            premium_since=datetime.now() - timedelta(days=60),
            premium_expires_at=datetime.now() + timedelta(days=expires_in_days),
        )
        db.session.commit()
        return u

    def test_downgrades_lapsed_pro_user_to_free(self, app, db, bound_factories):
        user = self._make_lapsed_user(db, bound_factories, plan='pro', expires_in_days=-1)

        with patch('utils.notification_service.notify_plan_changed'), \
             patch('utils.email_service.send_plan_changed_email'):
            from utils.scheduled_tasks import run_premium_expiry_downgrade
            run_premium_expiry_downgrade(app)

        db.session.refresh(user)
        assert user.subscription_plan == 'free'

    def test_notifies_and_emails_the_downgraded_user(self, app, db, bound_factories):
        user = self._make_lapsed_user(db, bound_factories, plan='amateur', expires_in_days=-3)

        notified_ids: list[int] = []
        emailed_ids: list[int] = []

        def _capture_notif(u, new_plan, old_plan, **kwargs):
            notified_ids.append(u.id)
            assert new_plan == 'free'
            assert old_plan == 'amateur'

        def _capture_email(u, new_plan, **kwargs):
            emailed_ids.append(u.id)

        with patch('utils.notification_service.notify_plan_changed', side_effect=_capture_notif), \
             patch('utils.email_service.send_plan_changed_email', side_effect=_capture_email):
            from utils.scheduled_tasks import run_premium_expiry_downgrade
            run_premium_expiry_downgrade(app)

        assert user.id in notified_ids
        assert user.id in emailed_ids

    def test_does_not_touch_active_premium_user(self, app, db, bound_factories):
        active_user = self._make_lapsed_user(db, bound_factories, plan='pro', expires_in_days=10)

        with patch('utils.notification_service.notify_plan_changed') as mock_notif, \
             patch('utils.email_service.send_plan_changed_email'):
            from utils.scheduled_tasks import run_premium_expiry_downgrade
            run_premium_expiry_downgrade(app)
            mock_notif.assert_not_called()

        db.session.refresh(active_user)
        assert active_user.subscription_plan == 'pro'

    def test_is_idempotent_across_consecutive_runs(self, app, db, bound_factories):
        self._make_lapsed_user(db, bound_factories, plan='pro', expires_in_days=-1)

        notified_ids: list[int] = []

        def _capture(u, new_plan, old_plan, **kwargs):
            notified_ids.append(u.id)

        with patch('utils.notification_service.notify_plan_changed', side_effect=_capture), \
             patch('utils.email_service.send_plan_changed_email'):
            from utils.scheduled_tasks import run_premium_expiry_downgrade
            run_premium_expiry_downgrade(app)
            first_run_count = len(notified_ids)
            run_premium_expiry_downgrade(app)
            second_run_count = len(notified_ids)

        # Une fois passé à 'free', l'utilisateur ne matche plus la requête :
        # aucune notification supplémentaire au second run.
        assert first_run_count == 1
        assert second_run_count == first_run_count
