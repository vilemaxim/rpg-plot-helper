from django.conf import settings
from django.db import models

from organizations.models import Organization, World


class Interview(models.Model):
    """One person's Interview in a World, kept so that it survives a reload
    (ADR-0008): its kind and its turns so far, each `{"role", "text"}`, the
    latest file being in the last reply that holds one. It goes when its Mod is
    submitted, when its person starts over, or after `IDLE_FOR` without
    activity. It is not part of the World, so it is never exported (ADR-0001),
    and only its person reads it."""

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="+")
    world = models.ForeignKey(World, on_delete=models.CASCADE, related_name="+")
    person = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                               related_name="+")
    kind = models.CharField(max_length=40)
    turns = models.JSONField(default=list, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    active_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["world", "person", "kind"]),
                   models.Index(fields=["active_at"])]
