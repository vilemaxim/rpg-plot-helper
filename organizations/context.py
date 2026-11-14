from .models import Membership


def organization(request):
    """What every page needs to show where the person is working: their
    Organization, whether they are its Organization Admin, and the other
    Organizations they could switch to."""
    membership = getattr(request, "membership", None)
    if membership is None:
        return {}
    others = (Membership.objects.filter(user=request.user)
              .exclude(pk=membership.pk).select_related("organization")
              .order_by("organization__name"))
    return {
        "organization": membership.organization,
        "is_organization_admin": membership.is_admin,
        "other_organizations": [m.organization for m in others],
    }
