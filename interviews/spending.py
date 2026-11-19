"""What Interviews may spend (ADR-0008): turns per person per day, and tokens
per Organization per month, set in `[limits]` of `interviews.toml`.

The deployment's operator pays for every Organization on it. Before each of
the person's turns, `turn_refused` says whether a limit has been reached, and
counts the turn if not. Every LLM call an Interview makes, the person's turns
and fix attempts alike, reports its tokens to `record`. Days and months are
UTC, and both counts are kept in Postgres, shared by every process.

A Reconciliation and a World review spend from the same monthly tokens
(`tokens_refused` before each runs, and `record` after), but take no
person's turn.
"""

from datetime import UTC, date, datetime, time, timedelta

from django.db import connection
from django.utils import timezone

from organizations import tenancy
from plothelper import limits as counters

from . import config
from .models import TokenUsage

TURNS = "interview-turns"


def _now():
    return timezone.now().astimezone(UTC)


def _month(now):
    return date(now.year, now.month, 1)


def _next_month(now):
    return date(now.year + now.month // 12, now.month % 12 + 1, 1)


def record(organization, usage):
    """Count the tokens of one LLM call an Interview made against its
    Organization (an object or an id) for this month. `usage` is the
    provider's `Usage`, from the turn's `Ended`. Call it for every call: the
    person's turns and fix attempts alike. Safe when two calls record at
    once, and inside or outside a transaction: a turn streams after its
    request's transaction has ended."""
    table = TokenUsage._meta.db_table
    with tenancy.working_in(organization) as organization_id, connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {table} (organization_id, month, tokens) VALUES (%s, %s, %s) "
            f"ON CONFLICT (organization_id, month) DO UPDATE "
            f"SET tokens = {table}.tokens + EXCLUDED.tokens",
            [organization_id, _month(_now()), usage.total])


def tokens_refused(organization, spent_on="the LLM"):
    """Why the Organization (an object or an id) may not spend more tokens
    this month: a sentence saying it has used this month's and when more
    are allowed, or None if it may. Its tokens have reached the cap: the
    call that crosses it is allowed to finish. Counts nothing."""
    cap = config.current().limits.tokens_per_organization_per_month
    if cap is None:
        return None
    now = _now()
    with tenancy.working_in(organization) as organization_id:
        used = (TokenUsage.objects.filter(organization_id=organization_id, month=_month(now))
                .values_list("tokens", flat=True).first() or 0)
    if used < cap:
        return None
    starts = _next_month(now)
    return (f"Your Organization has used this month's tokens for {spent_on}. "
            f"More are allowed from {starts.day} {starts:%B} (UTC).")


def turn_refused(person, organization):
    """Count one more of `person`'s turns in `organization`, and say why it
    may not be taken: a sentence naming the limit reached and when it starts
    again, or None if it may. A refused turn counts nothing.

    A turn is refused once the Organization's tokens this month have reached
    the cap: the turn that crosses it is allowed to finish."""
    limits = config.current().limits
    now = _now()
    refused = tokens_refused(organization, "Interviews")
    if refused:
        return refused
    allowed = limits.turns_per_person_per_day
    if allowed is None:
        return None
    day = now.date()
    midnight = datetime.combine(day + timedelta(days=1), time(), tzinfo=UTC)
    key = f"{person.pk}:{day.isoformat()}"
    if counters.reached(TURNS, key, allowed) or not counters.take(
            TURNS, key, allowed, (midnight - now).total_seconds()):
        return (f"You have had today's {allowed} turns with the LLM. More are allowed from "
                f"midnight UTC.")
    return None
