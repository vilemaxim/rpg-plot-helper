"""Whether a World's draft Mods are reconciled when they are submitted.

One of the settings in `llm_runs.py`: an Organization Admin sets it for the
whole Organization, off by default, and may set it for one World.
"""

from .llm_runs import RunsByItself
from .models import ReconcilingOverride

SETTING = RunsByItself("reconciles_on_submission", ReconcilingOverride)


def reconciles_on_submission(world):
    """Whether a draft Mod in this World is reconciled when it is submitted or
    revised."""
    return SETTING.is_on(world)
