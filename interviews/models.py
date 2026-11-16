from django.db import models

from organizations.models import Organization


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
