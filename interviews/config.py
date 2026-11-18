"""The Interview config loader: which LLM each kind of Interview uses.

The config is a TOML file, `interviews.toml` at the repo root, committed with
defaults. A self-hoster points the `INTERVIEWS_CONFIG` environment variable at
another (settings.INTERVIEWS_CONFIG). It is read and checked once, at startup
(`apps.py`); a key the app does not know, an unknown provider, a missing
`model` or an `effort` the provider rejects stops the app with a message
naming the key (ADR-0008).

    [providers.anthropic]
    key_env = "ANTHROPIC_API_KEY"   # the environment variable holding the key

    [providers.openrouter]          # any name: `kind` says which adapter
    kind = "openai-compatible"      # left out, the table's name is the kind
    base_url = "https://openrouter.ai/api/v1"
    key_env = "OPENROUTER_API_KEY"  # optional here, for a local model

    [interviews.new-mod]
    provider = "anthropic"
    model = "claude-opus-5-5"
    effort = "high"                 # the provider's own values
    max_tokens = 32000
    max_fix_attempts = 3            # times the LLM is sent its file's errors

    [reconciliation]                # the LLM that reconciles a draft Mod
    provider = "anthropic"          # `reconciliation_llm`; no fix attempts
    model = "claude-opus-5-5"
    effort = "high"
    max_tokens = 32000

    [limits]                        # either may be left out: no limit
    turns_per_person_per_day = 40
    tokens_per_organization_per_month = 5000000

A kind of Interview is on only if it has an entry here and its provider's key
is set in the environment (or it names no `key_env`, for an endpoint that
needs no key): `llm_for(kind)` answers that, and gives the
provider adapter to talk to. Otherwise it is off, and the paste path takes its
place.

To add a setting, add it to `INTERVIEW_KEYS`, `PROVIDER_KEYS` or
`LIMIT_KEYS` with the function that checks its value, and a field to the
matching dataclass.
"""

import os
import tomllib
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from django.conf import settings

from .providers import ADAPTERS, Provider

DEFAULT_MAX_TOKENS = 32000
DEFAULT_MAX_FIX_ATTEMPTS = 3

class Kind(StrEnum):
    """The kinds of Interview: those plotcanon has instructions for
    (`plotcanon.interview_instructions`), which does not export the list.
    The value is plotcanon's name for it, and the config's."""

    NEW_MOD = "new-mod"
    REVISE_MOD = "revise-mod"
    REPORT = "report"


class ConfigError(Exception):
    """The config cannot be used. `str()` names the file and the key."""


@dataclass(frozen=True)
class ProviderSettings:
    """A `[providers.<name>]` table. `kind` names the adapter in
    `providers.ADAPTERS`; `key_env` is None for an endpoint that needs no key;
    `base_url` is given for an adapter that `takes_base_url`."""

    name: str
    key_env: str | None
    kind: str = ""
    base_url: str | None = None


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
class ReconciliationSettings:
    """The `[reconciliation]` entry: which provider and model reconcile a
    draft, and how. One report, not a conversation: no file to fix."""

    provider: str
    model: str
    effort: str | None = None
    max_tokens: int = DEFAULT_MAX_TOKENS


@dataclass(frozen=True)
class Limits:
    """What the deployment's operator allows Interviews to spend. None is no
    limit. See `interviews.spending`."""

    turns_per_person_per_day: int | None = None
    tokens_per_organization_per_month: int | None = None


@dataclass(frozen=True)
class Config:
    providers: dict[str, ProviderSettings] = field(default_factory=dict)
    interviews: dict[str, InterviewSettings] = field(default_factory=dict)
    limits: Limits = field(default_factory=Limits)
    # The `[reconciliation]` entry, or None for none: Reconciliation is off.
    reconciliation: ReconciliationSettings | None = None


@dataclass(frozen=True)
class Llm:
    """An LLM that is on, for a kind of Interview or for Reconciliation: its
    settings, and the adapter to talk to its provider with."""

    settings: InterviewSettings | ReconciliationSettings
    provider: Provider


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
PROVIDER_KEYS = {"kind": _text, "key_env": _text, "base_url": _text}
INTERVIEW_KEYS = {"provider": _text, "model": _text, "effort": _text,
                  "max_tokens": _positive, "max_fix_attempts": _not_negative}
LIMIT_KEYS = {"turns_per_person_per_day": _positive,
              "tokens_per_organization_per_month": _positive}
# A Reconciliation is one report, not a conversation: no file to fix.
RECONCILIATION_KEYS = {key: check for key, check in INTERVIEW_KEYS.items()
                       if key != "max_fix_attempts"}
REQUIRED_INTERVIEW_KEYS = ("provider", "model")
TOP_LEVEL_KEYS = ("providers", "interviews", "reconciliation", "limits")
RECONCILIATION = "reconciliation"


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
        prefix = f"providers.{name}"
        values = _values(table, prefix, PROVIDER_KEYS, refuse)
        kind = values.get("kind", name)
        if kind not in ADAPTERS:
            if "kind" in values:
                refuse(f"{prefix}.kind", f"is `{kind}`, which is not a kind of provider. "
                                         f"Known: {_listed(ADAPTERS)}")
            refuse(prefix, f"is not a provider. Known: {_listed(ADAPTERS)}, or say "
                           f"which with `kind`")
        adapter = ADAPTERS[kind]
        if adapter.takes_base_url and "base_url" not in values:
            refuse(f"{prefix}.base_url", f"is missing. A {kind} provider needs the "
                                         f"endpoint's address")
        if not adapter.takes_base_url and "base_url" in values:
            refuse(f"{prefix}.base_url", f"is not a setting for {kind}")
        providers[name] = ProviderSettings(
            name, values.get("key_env", adapter.default_key_env or None), kind,
            values.get("base_url"))

    def entry(table, prefix, known):
        """An LLM entry's values, checked against the providers."""
        values = _values(table, prefix, known, refuse)
        for key in REQUIRED_INTERVIEW_KEYS:
            if key not in values:
                refuse(f"{prefix}.{key}", "is missing")
        provider = values["provider"]
        if provider not in providers:
            if provider in ADAPTERS:
                refuse(f"providers.{provider}", f"is missing, and {prefix} uses it. Add a "
                                                f"[providers.{provider}] table saying key_env")
            refuse(f"{prefix}.provider", f"is `{provider}`, which is not a provider. "
                                         f"Known: {_listed(providers)}")
        adapter = ADAPTERS[providers[provider].kind]
        effort = values.get("effort")
        if not adapter.check_effort(effort):
            refuse(f"{prefix}.effort", f"is `{effort}`, which {provider} does not take. "
                                       f"It takes {_listed(adapter.efforts)}")
        return values

    interviews = {}
    for kind, table in _tables(raw, "interviews", refuse).items():
        prefix = f"interviews.{kind}"
        if kind not in Kind:
            refuse(prefix, f"is not a kind of Interview. Known: "
                           f"{_listed(Kind)}")
        values = entry(table, prefix, INTERVIEW_KEYS)
        interviews[Kind(kind)] = InterviewSettings(kind=Kind(kind), **values)

    reconciliation = raw.get(RECONCILIATION)
    if reconciliation is not None:
        if not isinstance(reconciliation, dict):
            refuse(RECONCILIATION, "must be a table, [reconciliation]")
        reconciliation = ReconciliationSettings(
            **entry(reconciliation, RECONCILIATION, RECONCILIATION_KEYS))

    limits = raw.get("limits", {})
    if not isinstance(limits, dict):
        refuse("limits", "must be a table, [limits]")
    limits = Limits(**_values(limits, "limits", LIMIT_KEYS, refuse))
    return Config(providers, interviews, limits, reconciliation)


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


def is_on(kind):
    """Whether this kind of Interview is on (`llm_for`)."""
    return llm_for(kind) is not None


def llm_for(kind, loaded=None):
    """The LLM for this kind of Interview, or None if that kind is off: it has
    no entry, or its provider names a key that is not set in the environment.
    `loaded` is a `Config`, the one the app started with if not given."""
    loaded = loaded or current()
    return _llm(loaded.interviews.get(kind), loaded)


def reconciliation_llm(loaded=None):
    """The LLM that reconciles a draft Mod, or None if Reconciliation is off:
    there is no `[reconciliation]` entry, or its provider's key is not set.
    `loaded` is as for `llm_for`."""
    loaded = loaded or current()
    return _llm(loaded.reconciliation, loaded)


def _llm(entry, loaded):
    if entry is None:
        return None
    provider = loaded.providers[entry.provider]
    key = None
    if provider.key_env:
        key = os.environ.get(provider.key_env, "").strip()
        if not key:
            return None
    adapter = ADAPTERS[provider.kind]
    options = {"base_url": provider.base_url} if adapter.takes_base_url else {}
    return Llm(entry, adapter(key, entry, **options))
