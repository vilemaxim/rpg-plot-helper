"""What Interviews may spend (ADR-0008): turns per person per day, and tokens
per Organization per month, set in `[limits]` of `interviews.toml`.

The deployment's operator pays for every Organization on it. Before each of
the person's turns, `turn_refused` says whether a limit has been reached, and
counts the turn if not. Every LLM call an Interview makes, the person's turns
and fix attempts alike, reports its tokens to `record`. Days and months are
UTC, and both counts are kept in Postgres, shared by every process.
"""

from datetime import UTC, datetime, time, timedelta

from django.utils import timezone

from plothelper import limits as counters

from . import config

TURNS = "interview-turns"


def turn_refused(person):
    """Count one more of `person`'s turns, and say why it may not be taken:
    a sentence naming the limit reached and when it starts again, or None if
    it may. A refused turn counts nothing."""
    allowed = config.current().limits.turns_per_person_per_day
    if allowed is None:
        return None
    now = timezone.now().astimezone(UTC)
    day = now.date()
    midnight = datetime.combine(day + timedelta(days=1), time(), tzinfo=UTC)
    key = f"{person.pk}:{day.isoformat()}"
    if counters.reached(TURNS, key, allowed) or not counters.take(
            TURNS, key, allowed, (midnight - now).total_seconds()):
        return (f"You have had today's {allowed} turns with the LLM. More are allowed from "
                f"midnight UTC.")
    return None
