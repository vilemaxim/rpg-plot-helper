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
    (ADR-0008): its kind, the draft it revises if any, and its turns so far,
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
    # The draft a revise Interview (#47) is about; None for a new Mod.
    mod = models.ForeignKey("canon.Document", null=True, blank=True, on_delete=models.CASCADE,
                            related_name="+")
    turns = models.JSONField(default=list, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    active_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["world", "person", "kind"]),
                   models.Index(fields=["active_at"])]
