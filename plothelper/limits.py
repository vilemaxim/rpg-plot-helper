"""Counting how often something happens, to refuse it past a limit.

Counts are kept in Postgres (`accounts.LimitCount`), since the app has no cache or
background workers (ADR-0003), and one count is then shared by every process.
What is counted is kept as a hash, not as it was given. Counts that have run out are deleted
as new ones are made.

Used by sign-in (#16) and private links to a Mod.
"""

import hashlib
import ipaddress
from datetime import timedelta

from django.conf import settings
from django.db import connection
from django.utils import timezone

from accounts.models import LimitCount

# One IPv6 host can use any address in its /64, so all of them count as one.
IPV6_NETWORK = 64


def key_of(name, value):
    return hashlib.sha256(f"{name}\0{value}".encode()).hexdigest()


def reached(name, value, allowed):
    """Whether `value` has been counted under `name` `allowed` times or more
    in its current window."""
    row = LimitCount.objects.filter(key=key_of(name, value), expires_at__gt=timezone.now()).first()
    return row is not None and row.count >= allowed


def count(name, value, window):
    """Count `value` once more under `name`, in a window of `window` seconds
    from its first count, and return its count. Safe when two requests count
    the same thing at once."""
    now = timezone.now()
    table = LimitCount._meta.db_table
    with connection.cursor() as cursor:
        # Counts that have run out go, a few at a time. Rows another request
        # holds are left for later rather than waited for.
        cursor.execute(f"DELETE FROM {table} WHERE id IN (SELECT id FROM {table} "
                       f"WHERE expires_at <= %s LIMIT 100 FOR UPDATE SKIP LOCKED)", [now])
        cursor.execute(
            f"INSERT INTO {table} (key, count, expires_at) VALUES (%s, 1, %s) "
            f"ON CONFLICT (key) DO UPDATE SET "
            f"count = CASE WHEN {table}.expires_at <= %s THEN 1 ELSE {table}.count + 1 END, "
            f"expires_at = CASE WHEN {table}.expires_at <= %s THEN EXCLUDED.expires_at "
            f"ELSE {table}.expires_at END "
            f"RETURNING count",
            [key_of(name, value), now + timedelta(seconds=window), now, now])
        return cursor.fetchone()[0]


def take(name, value, allowed, window):
    """Count `value` once more and say whether it is still within `allowed`."""
    return count(name, value, window) <= allowed


def requester(request):
    """Who a request came from, as a network address: an IPv4 address, or an
    IPv6 /64 network. Behind `TRUSTED_PROXIES` proxies of our own, it is the
    address the outermost of them was connected from, read from the right of
    `X-Forwarded-For`, where each of our proxies added one. With none,
    `X-Forwarded-For` is the visitor's to make up, so it is ignored."""
    address = request.META.get("REMOTE_ADDR", "")
    proxies = settings.TRUSTED_PROXIES
    if proxies:
        forwarded = [part.strip() for part in
                     request.META.get("HTTP_X_FORWARDED_FOR", "").split(",") if part.strip()]
        if len(forwarded) >= proxies:
            address = forwarded[-proxies]
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return address
    if parsed.version == 6:
        if parsed.ipv4_mapped:
            return str(parsed.ipv4_mapped)
        return str(ipaddress.ip_network(f"{parsed}/{IPV6_NETWORK}", strict=False))
    return str(parsed)
