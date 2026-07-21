"""
utils/ical_export.py — Génération de flux iCal (RFC 5545) pour le rétroplanning.

PlanningEvent stocke des datetime naïfs + un nom de fuseau IANA (`timezone`) —
convention du projet (cf. models.py) plutôt qu'un premier champ tz-aware isolé.
On localise ici, au moment de l'export, pour produire un TZID correct.
"""
from zoneinfo import ZoneInfo

from icalendar import Calendar, Event

from models import PlanningEventStatus

_ICAL_STATUS = {
    PlanningEventStatus.proposed:  'TENTATIVE',
    PlanningEventStatus.confirmed: 'CONFIRMED',
    PlanningEventStatus.cancelled: 'CANCELLED',
}


def event_to_vevent(event) -> Event:
    """Convertit un PlanningEvent en composant VEVENT icalendar."""
    tz = ZoneInfo(event.timezone)

    vevent = Event()
    # UID stable : permet à Apple/Google Calendar de reconnaître une mise à
    # jour du même événement plutôt que de le dupliquer à chaque resynchro.
    vevent.add('uid', f'planning-event-{event.id}@laprod.fr')
    vevent.add('dtstamp', event.updated_at or event.created_at)
    vevent.add('summary', event.title)
    if event.description:
        vevent.add('description', event.description)
    if event.location:
        vevent.add('location', event.location)
    vevent.add('status', _ICAL_STATUS.get(event.status, 'TENTATIVE'))

    if event.all_day:
        vevent.add('dtstart', event.start_at.date())
        vevent.add('dtend', (event.end_at or event.start_at).date())
    else:
        vevent.add('dtstart', event.start_at.replace(tzinfo=tz))
        if event.end_at:
            vevent.add('dtend', event.end_at.replace(tzinfo=tz))

    return vevent


def build_ics_calendar(events, calendar_name: str = 'LaProd — Rétroplanning') -> bytes:
    """Construit un flux .ics complet à partir d'une liste de PlanningEvent."""
    cal = Calendar()
    cal.add('prodid', '-//LaProd//Rétroplanning//FR')
    cal.add('version', '2.0')
    cal.add('calscale', 'GREGORIAN')
    cal.add('x-wr-calname', calendar_name)

    for event in events:
        cal.add_component(event_to_vevent(event))

    return cal.to_ical()
