"""Telling the database who is asking, and for which Organization.

Row-level security (see `rls.py`) reads two values that last only for the
current transaction. They are transaction-local on purpose: a pooled database
connection is shared between requests, and a value that outlived its
transaction would leak one person's Organization into the next request.
"""

import uuid
from contextlib import contextmanager

from django.db import connection, transaction

from .models import Membership

SESSION_KEY = "organization_id"


def set_context(user=None, organization=None):
    """Set who is asking and which Organization they are working in, until the
    current transaction ends. Either can be an object or an id; None clears it."""
    if not connection.in_atomic_block:
        raise RuntimeError("the Organization can only be set inside a transaction")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('app.user_id', %s, true), "
            "set_config('app.organization_id', %s, true)",
            [_id(user), _id(organization)],
        )


def present_link(token_hash):
    """Let this transaction see the one private link whose secret hashes to
    this, with no Organization set, until `""` is presented or the transaction
    ends. See canon's migration 0013. Use `link_presented` to be sure it is
    taken back."""
    if not connection.in_atomic_block:
        raise RuntimeError("a link can only be presented inside a transaction")
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.mod_link', %s, true)", [token_hash])


@contextmanager
def link_presented(token_hash):
    """Present a link's hash for the length of a block only."""
    present_link(token_hash)
    try:
        yield
    finally:
        present_link("")


def _id(thing):
    if thing is None:
        return ""
    return str(getattr(thing, "pk", thing))


@contextmanager
def acting_as(user=None, organization=None):
    """Run a block as this person in this Organization, then clear both. For
    code that runs outside a web request, such as tests and commands."""
    with transaction.atomic():
        set_context(user, organization)
        yield
        # Not in a `finally`: if the block failed, the transaction is rolled
        # back, and that undoes the setting along with everything else.
        set_context()


@contextmanager
def working_in(organization):
    """Run a block in this Organization (an object or an id), as whoever
    the database was told is asking, then put back the Organization it was
    told before. Inside a transaction, the block shares it; outside one, it
    gets its own, as `acting_as`. Yields the Organization's id."""
    organization_id = _id(organization)
    if not connection.in_atomic_block:
        with acting_as(organization=organization_id):
            yield organization_id
        return
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_setting('app.user_id', true), "
                       "current_setting('app.organization_id', true)")
        user_id, was = cursor.fetchone()
    set_context(user_id or None, organization_id)
    try:
        yield organization_id
    finally:
        set_context(user_id or None, was or None)


def _preferred_organization(request):
    """The Organization id held in the session, or None if there is none or it
    is not an id at all."""
    try:
        return uuid.UUID(str(request.session.get(SESSION_KEY)))
    except ValueError:
        return None


def activate(request, user):
    """Work out which Organization this person is working in, tell the database
    and remember it in their session. Sets `request.membership` to their
    Membership there and `request.organization` to the Organization, or both to
    None if they belong to no Organization.

    This is the only place the database is told which Organization a request
    works in. The database trusts what it is told, so the choice is always made
    from the person's own Memberships. Other code may put a preference in the
    session (switching, or joining by invitation), but it is used only if the
    person is a member of that Organization.
    """
    set_context(user)
    memberships = (Membership.objects.filter(user=user)
                   .select_related("organization").order_by("joined_at", "pk"))
    wanted = _preferred_organization(request)
    membership = (memberships.filter(organization_id=wanted).first() if wanted else None) \
        or memberships.first()
    request.membership = membership
    request.organization = membership.organization if membership else None
    if membership is None:
        return
    if wanted != membership.organization_id:
        request.session[SESSION_KEY] = str(membership.organization_id)
    set_context(user, membership.organization_id)


class OrganizationMiddleware:
    """Run each request in one transaction, with the database told who is
    asking and for which Organization.

    Sets `request.membership` (and `request.organization`) for a signed-in
    person, or None for both.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        with transaction.atomic():
            if request.user.is_authenticated:
                activate(request, request.user)
            else:
                request.membership = request.organization = None
                set_context()
            response = self.get_response(request)
            # Django turns an exception in a view into a 500 response before it
            # gets back here, so the transaction would otherwise commit whatever
            # the view wrote before it failed.
            if response.status_code >= 500:
                transaction.set_rollback(True)
            return response
