from django.core.management.base import BaseCommand

from accounts.models import User


class Command(BaseCommand):
    help = ("Delete accounts that asked for a sign-in link long ago and never used one "
            "(SIGN_IN_UNUSED_ACCOUNT_AGE). Asking for a link also does this; run this "
            "on a schedule to do it when nobody is asking.")

    def handle(self, *args, **options):
        removed = User.objects.remove_unused()
        self.stdout.write(f"Removed {removed} unused account{'' if removed == 1 else 's'}.")
