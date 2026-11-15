"""Private links to one Mod, for Mod Runners with no account.

A Plot Master creates a link for a Mod and sends it to whoever runs it. Anyone
holding the link can read the Mod, download its file, see its open Flags and
file an After-Action Report on it, and nothing else in the World. A link works
while its Mod can take a report (approved or in progress) and until a Plot
Master turns it off.

The secret in a link is long and random, and only its hash is kept, so it is
shown once, when it is created. Guessing a secret is not practical, and is
limited anyway: an address that presents too many secrets no link has is
refused for a while. A link that has stopped working is not a guess, so
reloading one does not count. Reports sent through one link are limited too,
since each is checked against the whole World with the World locked.
"""

import secrets

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from organizations import tenancy
from organizations.models import World
from plothelper import limits

from .models import Document, ModLink
from .submitting import can_be_reported_on

# Bits of randomness in a secret: far past guessing, as a URL-safe string of
# 43 characters.
SECRET_BYTES = 32
MAX_LABEL = 200


class LinkRefused(Exception):
    """No link was created or changed. `str()` says why."""


class TooMany(Exception):
    """Refused for now: too many guesses from this address, or too many
    reports through this link. `str()` says which."""


def create(world, mod, label, user):
    """Create a private link to a Mod. Returns the link and its secret, which
    is not kept and cannot be had again."""
    label = " ".join(label.split())
    if len(label) > MAX_LABEL:
        raise LinkRefused(f"Keep who it is for to {MAX_LABEL} characters.")
    with transaction.atomic():
        World.objects.select_for_update().get(pk=world.pk)
        mod = Document.objects.get(organization=world.organization, world=world, pk=mod.pk)
        if not can_be_reported_on(mod):
            raise LinkRefused(f"{mod.name} cannot be run in its present state, so it gets no "
                              f"link. A Mod can be linked to while it is approved or in "
                              f"progress.")
        secret = secrets.token_urlsafe(SECRET_BYTES)
        link = ModLink.objects.create(
            organization=world.organization, world=world, mod=mod, label=label,
            token_hash=ModLink.hash_of(secret), created_by=user)
    return link, secret


def turn_off(world, mod, link_id, user):
    """Turn a link off for good. Returns how many were turned off."""
    with transaction.atomic():
        World.objects.select_for_update().get(pk=world.pk)
        return ModLink.objects.filter(organization=world.organization, world=world, mod=mod,
                                      pk=link_id, turned_off_at=None) \
            .update(turned_off_by=user, turned_off_at=timezone.now())


def works(link):
    return link.turned_off_at is None and can_be_reported_on(link.mod)


def opened(request, secret):
    """The link this secret opens, with its Mod, if it still works, or None.
    On success the request is told the link's Organization and works in it
    from then on with no person set: everything it shows must come from the
    link's Mod. Raises `TooMany` if this address has guessed too often lately."""
    address = limits.requester(request)
    if limits.reached("mod-link-guesses", address, settings.MOD_LINK_FAILURES_ALLOWED):
        raise TooMany("Too many links that open nothing have come from here. Try again "
                      "later.")
    token_hash = ModLink.hash_of(secret)
    with tenancy.link_presented(token_hash):
        link = ModLink.objects.filter(token_hash=token_hash).first()
    if link is None:
        limits.count("mod-link-guesses", address, settings.MOD_LINK_FAILURE_WINDOW)
        return None
    tenancy.set_context(organization=link.organization_id)
    link = ModLink.objects.select_related("mod", "world", "world__organization") \
        .get(organization_id=link.organization_id, pk=link.pk)
    return link if works(link) else None


def count_report(link):
    """Count a report sent through this link, saved or not. Raises `TooMany`
    once the link has sent its share for now. Counted before it is checked,
    so reports sent at the same moment cannot all slip under the limit."""
    if not limits.take("mod-link-reports", link.pk, settings.MOD_LINK_REPORTS_ALLOWED,
                       settings.MOD_LINK_REPORT_WINDOW):
        raise TooMany("Too many reports have been sent through this link lately. Try again "
                      "later, or ask a Plot Master.")
