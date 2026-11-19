from django.core.management.base import BaseCommand

from interviews import world_reviewing


class Command(BaseCommand):
    help = ("Run a World review in every World whose Organization, or an Organization "
            "Admin for that World, has turned on \"Run a World review after each Event\", "
            "once the latest Event has ended and it has not been reviewed since. Safe to run "
            "as often as you like, and alongside another run: no World is reviewed twice "
            "for one Event. Does nothing when World review is not set up. Run it on a "
            "schedule, such as daily.")

    def handle(self, *args, **options):
        outcomes = world_reviewing.run_scheduled()
        for outcome in outcomes:
            if outcome.reviewed:
                self.stdout.write(f"Reviewed {outcome.said}.")
            else:
                self.stdout.write(f"Did not review {outcome.said}: {outcome.why}")
        reviewed = sum(outcome.reviewed for outcome in outcomes)
        self.stdout.write(f"Reviewed {reviewed} World{'' if reviewed == 1 else 's'}.")
