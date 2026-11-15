"""A World's Canon, as the files it is made of.

Each document of a World (an NPC, a Mod, an After-Action Report and so on) is
one row. The file format belongs to the plotcanon package, which decides
what is valid. This app stores what plotcanon parsed and shows it (ADR-0004).
"""

from django.core.serializers.json import DjangoJSONEncoder
from django.db import models

from organizations.models import Organization, World


class Document(models.Model):
    """One file of a World, kept exactly as it was uploaded, with what
    plotcanon parsed out of it alongside.

    `path` is where the file sits in the World, such as `canon/npcs/x.md`.
    `kind` and `slug` are the document's `type` and `id` in the file format.
    `name` is what to call it on a page. `fields` is its frontmatter and `body`
    its markdown. `text` is the whole file, which is what an export writes
    back out.
    """

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="+")
    # The database also requires the World to be in the same Organization as
    # this row; see `rls.same_organization` in the migrations.
    world = models.ForeignKey(World, on_delete=models.CASCADE, related_name="documents")
    path = models.CharField(max_length=500)
    kind = models.CharField(max_length=40)
    slug = models.CharField(max_length=200)
    name = models.CharField(max_length=300)
    fields = models.JSONField(encoder=DjangoJSONEncoder)
    body = models.TextField(blank=True)
    text = models.TextField()

    class Meta:
        ordering = ["name", "slug"]
        constraints = [
            models.UniqueConstraint(fields=["world", "path"], name="one_document_per_path"),
            models.UniqueConstraint(fields=["world", "slug"], name="one_document_per_id"),
        ]
        indexes = [models.Index(fields=["world", "kind"])]

    def __str__(self):
        return self.name
