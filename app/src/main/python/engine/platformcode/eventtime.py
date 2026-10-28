# -*- coding: utf-8 -*-
"""Provider wall clocks -> UTC instant -> Italian civil time (never team time).

The A1A170 catalogue has no zone metadata. Its current UTC+02 wall-clock
convention was calibrated against Inter U23/Scafatese and Sassuolo/Lazio on
2026-10-27 and corroborated by Fleetwood/Arsenal (20:00 GMT -> 22:00 feed).
Keep this explicit and isolated: do not apply it to other providers. Prefer a
provider-supplied offset/timestamp when one becomes available.
"""
from datetime import datetime, timedelta, timezone

CATALOGUE_OFFSET_MINUTES = 120
TIME_BASIS_VERSION = 'a1a170-utc02-rome-v1'


def rome_from_utc(instant):
    """EU civil-time rule; works on Kodi/Windows without an IANA tzdata install."""
    if instant.tzinfo is not None:
        instant = instant.astimezone(timezone.utc).replace(tzinfo=None)
    def last_sunday(month):
        day = datetime(instant.year, month, 31, 1)
        return day - timedelta(days=(day.weekday() + 1) % 7)
    summer = last_sunday(3) <= instant < last_sunday(10)
    return instant + timedelta(hours=2 if summer else 1)


def now_rome():
    return rome_from_utc(datetime.now(timezone.utc))


def normalize_calendar(event, offset_minutes=CATALOGUE_OFFSET_MINUTES):
    """Idempotent migration of both old disk cache and fresh catalogue entries."""
    event = dict(event)
    if event.get('time_basis') == TIME_BASIS_VERSION:
        return event
    date = event.get('source_date') or event.get('date', '')
    clock = event.get('source_time') or event.get('time', '')
    try:
        wall = datetime.strptime(date + ' ' + clock, '%d/%m/%Y %H:%M')
        utc = wall - timedelta(minutes=offset_minutes)
        local = rome_from_utc(utc)
    except (TypeError, ValueError):
        return event
    event.update(source_date=date, source_time=clock,
                 source_utc_offset_minutes=offset_minutes,
                 time_basis=TIME_BASIS_VERSION, timezone='Europe/Rome',
                 start_utc=utc.isoformat() + 'Z', date=local.strftime('%d/%m/%Y'),
                 time=local.strftime('%H:%M'))
    event['fulltitle'] = '%s %s %s (%s)' % (
        local.strftime('%d/%m'), event['time'], event.get('teams', ''), event.get('league', ''))
    return event
