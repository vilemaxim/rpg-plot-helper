from .models import Invitation, Membership


def organization(request):
    """What every page needs to show where the person is working: their
    Organization, whether they are its Organization Admin, the other
    Organizations they could switch to, and how many invitations are waiting
    for their answer."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    context = {
        "waiting_invitation_count": Invitation.objects.waiting_for(user).count(),
    }
    membership = getattr(request, "membership", None)
    if membership is None:
        return context
    others = (Membership.objects.filter(user=user)
              .exclude(pk=membership.pk).select_related("organization")
              .order_by("organization__name"))
    return {
        **context,
        "organization": membership.organization,
        "is_organization_admin": membership.is_admin,
        "other_organizations": [m.organization for m in others],
    }
