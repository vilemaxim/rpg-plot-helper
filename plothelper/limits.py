"""Counting how often something happens, to refuse it past a limit.

Counts live in Django's cache, which is per process unless a shared cache is
configured, so each process keeps its own count. That is a brake on abuse,
not an exact limit. Shared by every limit in the app (see #16).
"""

from django.core.cache import cache


def reached(key, allowed):
    """Whether `key` has been counted `allowed` times or more."""
    return cache.get(key, 0) >= allowed


def count(key, window):
    """Count one more for `key`. The count starts over `window` seconds after
    its first."""
    if cache.add(key, 1, timeout=window):
        return
    try:
        cache.incr(key)
    except ValueError:
        # It ran out between the two calls; this is the first of a new count.
        cache.add(key, 1, timeout=window)
