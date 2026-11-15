import uuid

from django.core.management.base import BaseCommand, CommandError

from accounts.models import User
from organizations import tenancy
from organizations.models import Membership, Organization


class Command(BaseCommand):
    help = ("Make a person Organization Admin of an Organization. For when it has "
            "none left, so nobody can do it from the Organization page. The person "
            "must have an account, which asking for a sign-in link makes.")

    def add_arguments(self, parser):
        parser.add_argument("email", help="The person's email address.")
        parser.add_argument(
            "--organization",
            help="Its name, if they belong to it, or its id. Needed when they belong "
                 "to more than one, or to add them to one they do not belong to.")

    def handle(self, *args, email, organization=None, **options):
        user = User.objects.filter(email=User.objects.tidy(email)).first()
        if user is None:
            raise CommandError(f"Nobody has an account with {email}.")
        organization = self.choose(user, organization)
        # Row-level security lets a change be made only in the Organization set.
        with tenancy.acting_as(user=user, organization=organization):
            Membership.objects.update_or_create(organization=organization, user=user,
                                                defaults={"is_admin": True})
        self.stdout.write(f"{user.email} is now Organization Admin of {organization.name}.")

    def choose(self, user, wanted):
        """The Organization meant: the one they belong to, the one of theirs with
        this name or id, or failing that any Organization with this id."""
        with tenancy.acting_as(user=user):
            theirs = [m.organization for m in
                      Membership.objects.filter(user=user).select_related("organization")
                      .order_by("organization__name")]
        names = ", ".join(o.name for o in theirs) or "none"
        if wanted is None:
            if len(theirs) == 1:
                return theirs[0]
            raise CommandError(
                f"{user.email} belongs to {len(theirs)} Organizations ({names}). "
                "Say which with --organization.")
        matching = [o for o in theirs if wanted in (o.name, str(o.pk))]
        if len(matching) == 1:
            return matching[0]
        if matching:
            raise CommandError(f"{user.email} belongs to several Organizations called "
                               f"{wanted}. Name one by its id: "
                               + ", ".join(str(o.pk) for o in matching))
        try:
            organization_id = uuid.UUID(wanted)
        except ValueError:
            raise CommandError(f"{user.email} belongs to no Organization called {wanted}. "
                               f"They belong to: {names}.") from None
        # Each Organization is hidden from a query until it is the one set.
        with tenancy.acting_as(organization=organization_id):
            found = Organization.objects.filter(pk=organization_id).first()
        if found is None:
            raise CommandError(f"No Organization has the id {wanted}.")
        return found
