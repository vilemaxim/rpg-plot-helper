from django.conf import settings
from django.db import models

from organizations.models import Organization, World


class TokenUsage(models.Model):
    """The tokens an Organization's Interviews used in one calendar month
    (UTC), as the LLM provider reported them: every turn and every fix
    attempt. Read against `tokens_per_organization_per_month` in
    `interviews.toml`; see `interviews.spending`."""

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="+")
    # The first day of the month.
    month = models.DateField()
    tokens = models.BigIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "month"],
                                               name="one_token_usage_a_month")]


class Interview(models.Model):
    """One person's Interview in a World, kept so that it survives a reload
    (ADR-0008): its kind, the draft it revises or the Mod it reports on, the
    Path walked for a report and the Event and Group it is for, and its
    turns so far,
    each `{"role", "text"}`, the latest file being in the last reply that
    holds one. It goes when its Mod is
    submitted, when its person starts over, or after `IDLE_FOR` without
    activity. It is not part of the World, so it is never exported (ADR-0001),
    and only its person reads it."""

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="+")
    world = models.ForeignKey(World, on_delete=models.CASCADE, related_name="+")
    person = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                               related_name="+")
    kind = models.CharField(max_length=40)
    # The draft a revise Interview (#47) is about, or the Mod a report
    # Interview (#43) reports on; None for a new Mod.
    mod = models.ForeignKey("canon.Document", null=True, blank=True, on_delete=models.CASCADE,
                            related_name="+")
    turns = models.JSONField(default=list, blank=True)
    # A report Interview's walk (#43): the Path walked through its Mod's Dry
    # Run, as plotcanon's `path` steps, and where play had stopped before it,
    # `{"path": [...], "last_stop": {"passage": ..., "known": ...}}`. None
    # when no Path was walked.
    walk = models.JSONField(null=True, blank=True)
    # A report Interview's Event and Group (#67, ADR-0011), asked for only
    # when its Mod has more than one live Assignment at an Event: the
    # Event's id, or "" when it was not asked, and the Group's label, or ""
    # for the whole Mod. Not linked to any Assignment.
    event = models.CharField(max_length=200, blank=True, default="")
    group = models.CharField(max_length=60, blank=True, default="")
    started_at = models.DateTimeField(auto_now_add=True)
    active_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["world", "person", "kind"]),
                   models.Index(fields=["active_at"])]


class Reconciliation(models.Model):
    """One Reconciliation of a draft Mod (#59): the report the app's LLM
    wrote on checking it against the World's Canon and the other drafts
    waiting for approval, for the plot team alone (`interviews.reconciling`).

    One is kept for each run, so a draft's earlier Reconciliations stay as
    its history across revisions: `draft` is the Mod's text as it was
    reconciled. `ran_by` is the Plot Master who pressed Reconcile, or None
    for one run `on_submission`. `text` is what the LLM wrote, and the rest
    is plotcanon's reading of it (`plotcanon.read_reconciliation`):
    `sections`, each `{"heading", "text", "findings": [{"ids", "text"}]}`,
    the `verdict`, the `problems` with its shape, and `other_drafts`, the id
    of each other draft it says may conflict with this one.

    It is never written into the World's files, so it is never exported
    (ADR-0001)."""

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="+")
    world = models.ForeignKey(World, on_delete=models.CASCADE, related_name="+")
    mod = models.ForeignKey("canon.Document", on_delete=models.CASCADE, related_name="+")
    draft = models.TextField()
    ran_at = models.DateTimeField(auto_now_add=True)
    ran_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                               on_delete=models.SET_NULL, related_name="+")
    on_submission = models.BooleanField(default=False)
    # The model the deployment's config named for it, as it ran.
    model = models.CharField(max_length=200)
    text = models.TextField()
    verdict = models.CharField(max_length=100, blank=True)
    sections = models.JSONField(default=list, blank=True)
    problems = models.JSONField(default=list, blank=True)
    other_drafts = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["-ran_at", "-pk"]
        indexes = [models.Index(fields=["world", "mod"])]


class WorldReview(models.Model):
    """One World review (#61): the report the app's LLM wrote on looking
    across the whole World for drift, dormant Plots and chances to bring
    NPCs and Plots back, for the plot team alone (`interviews.world_reviewing`).

    One is kept for each run, so earlier reviews stay as the World's
    history. `ran_by` is the person who ran it, or None for one the
    scheduled command ran (`scheduled`). `event` is the id of the latest
    Event that had ended when it ran, or "" for none: a review after an
    Event is one with its id. `text` is what the LLM wrote, and `sections`
    and `problems` are plotcanon's reading of it (`plotcanon.read_world_review`),
    as for a `Reconciliation`.

    It is never written into the World's files, so it is never exported
    (ADR-0001)."""

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="+")
    world = models.ForeignKey(World, on_delete=models.CASCADE, related_name="+")
    ran_at = models.DateTimeField(auto_now_add=True)
    ran_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                               on_delete=models.SET_NULL, related_name="+")
    scheduled = models.BooleanField(default=False)
    event = models.CharField(max_length=200, blank=True, default="")
    # The model the deployment's config named for it, as it ran.
    model = models.CharField(max_length=200)
    text = models.TextField()
    sections = models.JSONField(default=list, blank=True)
    problems = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["-ran_at", "-pk"]
        indexes = [models.Index(fields=["world", "event"])]
        constraints = [
            # The scheduled command reviews a World once per Event, even if
            # two of its runs overlap.
            models.UniqueConstraint(fields=["world", "event"],
                                    condition=models.Q(scheduled=True),
                                    name="one_scheduled_world_review_an_event"),
        ]


class WorldReviewDismissal(models.Model):
    """The plot team dismissed the suggestion to run a World review after
    this Event (its id), so it is not suggested again for it."""

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="+")
    world = models.ForeignKey(World, on_delete=models.CASCADE, related_name="+")
    event = models.CharField(max_length=200)
    dismissed_at = models.DateTimeField(auto_now_add=True)
    dismissed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name="+")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["world", "event"],
                                               name="one_dismissal_an_event")]
