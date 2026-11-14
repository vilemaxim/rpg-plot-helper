"""Reading settings from the environment."""

import os


def flag(name, *, default):
    """An on/off setting. It is on for `1`, `true`, `yes` or `on` in any case,
    off for anything else, and `default` when the variable is not set at all."""
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
