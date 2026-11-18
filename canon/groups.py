"""Parallel Groups (ADR-0011): what plotcanon says about a report that
played side by side with others."""

import plotcanon

from .presenting import group_of
from .storing import files_of

# How plotcanon's warning reads when two Groups that played side by side
# change the same field of the same entity. It is the one warning about that,
# and the tests hold it to plotcanon's wording.
CLASH = "which played alongside this one"


def clashes(world, report):
    """plotcanon's warnings, as text, that `report` and a report from another
    Group that played alongside it change the same field of the same entity.
    Their changes are decided in order of report id, so the plot team checks
    they agree. A report with no `group` played alongside nothing.

    They name every document involved, so they are for the plot team only."""
    if not group_of(report):
        return []
    return [warning.message for warning in plotcanon.load_world(files_of(world)).warnings
            if warning.path == report.path and CLASH in warning.message]
