"""Whether a World's draft Mods are reconciled when they are submitted.

An Organization Admin sets it for the whole Organization, off by default, and
may set it on or off for one World, which then wins. Both are kept in the
database, not in `world.yml`: they decide what the app spends on the LLM, not
anything about the World's Canon.
"""

from .models import Organization


def reconciles_on_submission(world):
    """Whether a draft Mod in this World is reconciled when it is submitted or
    revised."""
    return (Organization.objects.filter(pk=world.organization_id)
            .values_list("reconciles_on_submission", flat=True).get())
