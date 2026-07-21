"""
Tests d'intégration — utils/planning_jobs.py::run_planning_event_reminders_job

Couvre :
  - Rappel 48h envoyé aux deux parties d'un événement confirmé dans la fenêtre
  - Rappel 2h envoyé dans sa propre fenêtre
  - Pas de rappel hors fenêtre, pour un événement non confirmé, ou un lien
    roster qui n'est plus actif
  - Pas de doublon sur un deuxième run (dédup applicative via UserNotificationLog)
  - Race condition : une ligne UserNotificationLog déjà présente (simulant un
    autre process qui a gagné la course) fait sauter l'envoi sans erreur
  - La contrainte unique de UserNotificationLog est le véritable garde-fou :
    un doublon en base lève IntegrityError, pas seulement le check applicatif
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from models import (
    Notification, PlanningEvent, PlanningEventStatus, PlanningEventTypeEnum,
    RosterLink, RosterLinkStatus, UserNotificationLog,
)
from tests.factories.user_factory import UserFactory
from tests.scenarios import _teardown_user


@pytest.fixture()
def producer(db, bound_factories):
    u = UserFactory(is_producer=True, subscription_plan='premium')
    db.session.commit()
    yield u
    _teardown_user(db, u)


@pytest.fixture()
def artist(db, bound_factories):
    u = UserFactory(is_artist=True, subscription_plan='free')
    db.session.commit()
    yield u
    _teardown_user(db, u)


@pytest.fixture()
def active_link(db, producer, artist):
    link = RosterLink(
        producer_id=producer.id, artist_id=artist.id,
        invited_by_id=producer.id, status=RosterLinkStatus.active,
    )
    db.session.add(link)
    db.session.commit()
    yield link
    db.session.rollback()
    # SQLite réutilise les rowids après suppression (cf. conftest.py) : une
    # ligne UserNotificationLog orpheline avec period_key="planning-event-<id>"
    # entrerait en collision avec un futur événement qui recycle ce même id.
    db.session.query(UserNotificationLog).filter(
        UserNotificationLog.user_id.in_([producer.id, artist.id]),
        UserNotificationLog.notification_type.in_(['planning_reminder_48h', 'planning_reminder_2h']),
    ).delete(synchronize_session=False)
    db.session.query(PlanningEvent).filter_by(roster_link_id=link.id).delete()
    existing = db.session.get(RosterLink, link.id)
    if existing:
        db.session.delete(existing)
    db.session.commit()


def _make_event(db, link, hours_from_now, status=PlanningEventStatus.confirmed):
    event = PlanningEvent(
        roster_link_id=link.id,
        created_by_id=link.producer_id,
        title='Session studio',
        event_type=PlanningEventTypeEnum.recording_session,
        status=status,
        start_at=datetime.now() + timedelta(hours=hours_from_now),
    )
    db.session.add(event)
    db.session.commit()
    return event


def _notif_count(user_id, notif_type):
    return Notification.query.filter_by(user_id=user_id, type=notif_type).count()


class TestReminderWindows:
    def test_rappel_48h_envoye_aux_deux_parties_dans_la_fenetre(self, app, db, producer, artist, active_link):
        _make_event(db, active_link, hours_from_now=47)

        from utils.planning_jobs import run_planning_event_reminders_job
        sent = run_planning_event_reminders_job(app)

        assert sent == 2  # producteur + artiste
        assert _notif_count(producer.id, 'planning_reminder_48h') == 1
        assert _notif_count(artist.id, 'planning_reminder_48h') == 1

    def test_rappel_2h_envoye_dans_sa_fenetre(self, app, db, producer, artist, active_link):
        _make_event(db, active_link, hours_from_now=1.5)

        from utils.planning_jobs import run_planning_event_reminders_job
        run_planning_event_reminders_job(app)

        assert _notif_count(producer.id, 'planning_reminder_2h') == 1
        assert _notif_count(artist.id, 'planning_reminder_2h') == 1

    def test_pas_de_rappel_hors_fenetre(self, app, db, producer, artist, active_link):
        _make_event(db, active_link, hours_from_now=72)  # bien au-delà de 48h

        from utils.planning_jobs import run_planning_event_reminders_job
        sent = run_planning_event_reminders_job(app)

        assert sent == 0
        assert _notif_count(producer.id, 'planning_reminder_48h') == 0

    def test_pas_de_rappel_pour_evenement_passe(self, app, db, producer, artist, active_link):
        _make_event(db, active_link, hours_from_now=-1)

        from utils.planning_jobs import run_planning_event_reminders_job
        sent = run_planning_event_reminders_job(app)

        assert sent == 0

    def test_pas_de_rappel_pour_evenement_non_confirme(self, app, db, producer, artist, active_link):
        _make_event(db, active_link, hours_from_now=47, status=PlanningEventStatus.proposed)

        from utils.planning_jobs import run_planning_event_reminders_job
        sent = run_planning_event_reminders_job(app)

        assert sent == 0

    def test_pas_de_rappel_pour_evenement_annule(self, app, db, producer, artist, active_link):
        _make_event(db, active_link, hours_from_now=1, status=PlanningEventStatus.cancelled)

        from utils.planning_jobs import run_planning_event_reminders_job
        sent = run_planning_event_reminders_job(app)

        assert sent == 0

    def test_pas_de_rappel_si_le_lien_roster_n_est_plus_actif(self, app, db, producer, artist, active_link):
        _make_event(db, active_link, hours_from_now=1)
        active_link.status = RosterLinkStatus.ended
        db.session.commit()

        from utils.planning_jobs import run_planning_event_reminders_job
        sent = run_planning_event_reminders_job(app)

        assert sent == 0


class TestDeduplication:
    def test_pas_de_doublon_sur_un_deuxieme_run(self, app, db, producer, artist, active_link):
        _make_event(db, active_link, hours_from_now=1.5)

        from utils.planning_jobs import run_planning_event_reminders_job
        first_run  = run_planning_event_reminders_job(app)
        second_run = run_planning_event_reminders_job(app)

        assert first_run == 2
        assert second_run == 0
        assert _notif_count(producer.id, 'planning_reminder_2h') == 1
        assert _notif_count(artist.id, 'planning_reminder_2h') == 1

    def test_fenetres_mutuellement_exclusives(self, app, db, producer, artist, active_link):
        """Un événement créé tardivement (moins de 2h avant) ne doit recevoir QUE
        le rappel 2h, jamais le 48h en même temps : les fenêtres ne se chevauchent
        pas, sinon le message « a lieu dans 48h » serait faux pour un événement
        en réalité imminent — et il n'y a pas de façon exacte de rattraper un
        rappel 48h manqué rétroactivement."""
        _make_event(db, active_link, hours_from_now=1)

        from utils.planning_jobs import run_planning_event_reminders_job
        sent = run_planning_event_reminders_job(app)

        assert sent == 2  # 2h uniquement, producteur + artiste
        assert _notif_count(producer.id, 'planning_reminder_48h') == 0
        assert _notif_count(producer.id, 'planning_reminder_2h') == 1

    def test_race_condition_ligne_deja_prise_par_un_autre_process(self, app, db, producer, artist, active_link):
        """Simule un autre process/worker qui aurait déjà gagné la course pour ce
        rappel précis : le job ne doit ni planter, ni renvoyer de notification."""
        event = _make_event(db, active_link, hours_from_now=1.5)
        period_key = f'planning-event-{event.id}'

        db.session.add(UserNotificationLog(
            user_id=producer.id, notification_type='planning_reminder_2h', period_key=period_key,
        ))
        db.session.commit()

        from utils.planning_jobs import run_planning_event_reminders_job
        sent = run_planning_event_reminders_job(app)

        # Seul l'artiste reçoit son rappel — le producteur était déjà "pris".
        assert sent == 1
        assert _notif_count(producer.id, 'planning_reminder_2h') == 0
        assert _notif_count(artist.id, 'planning_reminder_2h') == 1


class TestUserNotificationLogUniqueConstraint:
    """Le vrai garde-fou contre les races n'est pas le check applicatif (`already`,
    lui-même racy en théorie) mais la contrainte unique en base : si deux
    transactions concurrentes committent la même clé, une seule doit survivre."""

    def test_contrainte_unique_leve_integrity_error_sur_doublon(self, db, producer):
        period_key = 'planning-event-race-test'
        db.session.add(UserNotificationLog(
            user_id=producer.id, notification_type='planning_reminder_2h', period_key=period_key,
        ))
        db.session.commit()

        db.session.add(UserNotificationLog(
            user_id=producer.id, notification_type='planning_reminder_2h', period_key=period_key,
        ))
        with pytest.raises(IntegrityError):
            db.session.commit()

        db.session.rollback()
        db.session.query(UserNotificationLog).filter_by(
            user_id=producer.id, notification_type='planning_reminder_2h', period_key=period_key,
        ).delete()
        db.session.commit()
