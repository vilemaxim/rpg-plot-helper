"""The Interview config loader: which LLM each kind of Interview uses.

The config is a TOML file, `interviews.toml` at the repo root, committed with
defaults. A self-hoster points the `INTERVIEWS_CONFIG` environment variable at
another (settings.INTERVIEWS_CONFIG). It is read and checked once, at startup
(`apps.py`); a key the app does not know, an unknown provider, a missing
`model` or an `effort` the provider rejects stops the app with a message
naming the key (ADR-0008).

    [providers.anthropic]
    key_env = "ANTHROPIC_API_KEY"   # the environment variable holding the key

    [interviews.new-mod]
    provider = "anthropic"
    model = "claude-opus-5-5"
    effort = "high"                 # the provider's own values
    max_tokens = 32000
    max_fix_attempts = 3            # times the LLM is sent its file's errors

A kind of Interview is on only if it has an entry here and its provider's key
is set in the environment: `llm_for(kind)` answers that, and gives the
provider adapter to talk to. Otherwise it is off, and the paste path takes its
place.

To add a setting (a limit, say), add it to `INTERVIEW_KEYS` or
`PROVIDER_KEYS` with the function that checks its value, and a field to the
matching dataclass.
"""

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings

from .providers import ADAPTERS

DEFAULT_MAX_TOKENS = 32000
DEFAULT_MAX_FIX_ATTEMPTS = 3

# The kinds of Interview plotcanon has instructions for
# (`plotcanon.interview_instructions`), which does not export the list.
KINDS = ("new-mod", "revise-mod")


class ConfigError(Exception):
    """The config cannot be used. `str()` names the file and the key."""


@dataclass(frozen=True)
class ProviderSettings:
    name: str
    key_env: str


@dataclass(frozen=True)
class InterviewSettings:
    """One kind of Interview's entry: which provider and model, and how."""

    kind: str
    provider: str
    model: str
    effort: str | None = None
    max_tokens: int = DEFAULT_MAX_TOKENS
    # How many times a Mod file with errors goes back to the LLM to fix
    # before the person is shown it with its errors (#45).
    max_fix_attempts: int = DEFAULT_MAX_FIX_ATTEMPTS


@dataclass(frozen=True)
class Config:
    providers: dict[str, ProviderSettings] = field(default_factory=dict)
    interviews: dict[str, InterviewSettings] = field(default_factory=dict)


@dataclass(frozen=True)
class Llm:
    """A kind of Interview that is on: its settings, and the adapter to talk
    to its provider with."""

    settings: InterviewSettings
    provider: object  # a providers.Provider


def _text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("must be a word in quotes")
    return value.strip()


def _positive(value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("must be a whole number above 0")
    return value


def _not_negative(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("must be a whole number, 0 or more")
    return value


# Each key a table may hold, with the function that checks its value.
PROVIDER_KEYS = {"key_env": _text}
INTERVIEW_KEYS = {"provider": _text, "model": _text, "effort": _text,
                  "max_tokens": _positive, "max_fix_attempts": _not_negative}
REQUIRED_INTERVIEW_KEYS = ("provider", "model")
TOP_LEVEL_KEYS = ("providers", "interviews")


def load(path, *, required=True):
    """Read and check the config at `path`. Raises `ConfigError` naming the
    bad key. With `required=False`, a file that is not there means no
    Interviews at all, which is how the committed default is read."""
    path = Path(path)
    try:
        raw = tomllib.loads(path.read_text())
    except FileNotFoundError:
        if not required:
            return Config()
        raise ConfigError(f"There is no Interview config at {path}.") from None
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise ConfigError(f"{path} cannot be read as TOML: {error}") from None
    return _checked(raw, path.name)


def _checked(raw, where):
    def refuse(key, why):
        raise ConfigError(f"{where}: `{key}` {why}.")

    for key in raw:
        if key not in TOP_LEVEL_KEYS:
            refuse(key, f"is not a setting. The file has only {_listed(TOP_LEVEL_KEYS)}")

    providers = {}
    for name, table in _tables(raw, "providers", refuse).items():
        if name not in ADAPTERS:
            refuse(f"providers.{name}", f"is not a provider. Known: {_listed(ADAPTERS)}")
        values = _values(table, f"providers.{name}", PROVIDER_KEYS, refuse)
        providers[name] = ProviderSettings(
            name, values.get("key_env", ADAPTERS[name].default_key_env))

    interviews = {}
    for kind, table in _tables(raw, "interviews", refuse).items():
        prefix = f"interviews.{kind}"
        if kind not in KINDS:
            refuse(prefix, f"is not a kind of Interview. Known: "
                           f"{_listed(KINDS)}")
        values = _values(table, prefix, INTERVIEW_KEYS, refuse)
        for key in REQUIRED_INTERVIEW_KEYS:
            if key not in values:
                refuse(f"{prefix}.{key}", "is missing")
        provider = values["provider"]
        if provider not in ADAPTERS:
            refuse(f"{prefix}.provider", f"is `{provider}`, which is not a provider. "
                                         f"Known: {_listed(ADAPTERS)}")
        if provider not in providers:
            refuse(f"providers.{provider}", f"is missing, and {prefix} uses it. Add a "
                                            f"[providers.{provider}] table saying key_env")
        effort = values.get("effort")
        if not ADAPTERS[provider].check_effort(effort):
            refuse(f"{prefix}.effort", f"is `{effort}`, which {provider} does not take. "
                                       f"It takes {_listed(ADAPTERS[provider].efforts)}")
        interviews[kind] = InterviewSettings(kind=kind, **values)
    return Config(providers, interviews)


def _tables(raw, key, refuse):
    tables = raw.get(key, {})
    if not isinstance(tables, dict):
        refuse(key, "must be tables, such as [" + key + ".<name>]")
    for name, table in tables.items():
        if not isinstance(table, dict):
            refuse(f"{key}.{name}", "must be a table")
    return tables


def _values(table, prefix, known, refuse):
    values = {}
    for key, value in table.items():
        if key not in known:
            refuse(f"{prefix}.{key}", f"is not a setting. Known: {_listed(known)}")
        try:
            values[key] = known[key](value)
        except ValueError as error:
            refuse(f"{prefix}.{key}", str(error))
    return values


def _listed(names):
    return ", ".join(f"`{name}`" for name in names) or "none"


_current = None


def configure():
    """Read the config named by settings, check it and keep it for
    `current()`. Called once at startup; raises `ConfigError`."""
    global _current
    path = settings.INTERVIEWS_CONFIG
    _current = load(path, required=bool(os.environ.get("INTERVIEWS_CONFIG")))
    return _current


def current():
    """The config the app started with."""
    return _current if _current is not None else configure()


def llm_for(kind, loaded=None):
    """The LLM for this kind of Interview, or None if that kind is off: it has
    no entry, or its provider's key is not set in the environment. `loaded`
    is a `Config`, the one the app started with if not given."""
    loaded = loaded or current()
    entry = loaded.interviews.get(kind)
    if entry is None:
        return None
    key = os.environ.get(loaded.providers[entry.provider].key_env, "").strip()
    if not key:
        return None
    return Llm(entry, ADAPTERS[entry.provider](key, entry))
