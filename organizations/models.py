"""Organizations, the Worlds they run, and who may do what in them.

Every table here except the plain list of people is protected by row-level
security in Postgres (see `rls.py`): a query sees only the rows of the
Organization set for the current request. That is why every row carries its
Organization, even where it could be worked out from another column.
"""

import uuid

import plotcanon
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

# A World's Dry Run structure (ADR-0007) is a setting in its settings file,
# whose format is plotcanon's (ADR-0004): plotcanon says what it may be, what
# each value means and which is the default, and the app keeps no list of its
# own.

def dry_run_structures():
    """The values a Dry Run structure may have, each with what it means, in
    plotcanon's words."""
    return plotcanon.vocabularies()["vocabularies"]["dry_run_structure"]


def default_dry_run_structure():
    return plotcanon.vocabularies()["dry_run_structure_default"]


def a_dry_run_structure(value):
    """Refuse a value plotcanon does not have."""
    if value not in dry_run_structures():
        raise ValidationError(f"`{value}` is not a Dry Run structure. It is one of "
                              f"{', '.join(dry_run_structures())}.")


def settings_file_for(structure):
    """The whole text of a World's settings file giving this Dry Run
    structure."""
    return plotcanon.WorldSettings(dry_run_structure=structure).text()


class Organization(models.Model):
    """A group that runs one or more Worlds. Its data is kept entirely
    separate from every other Organization's."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    # The Dry Run structure each new World is given (ADR-0007), which an
    # Organization Admin may change. It lives only in the app (ADR-0001): a
    # World's own setting is in its settings file, written when it is created.
    # It is checked as it is saved, since a value plotcanon does not have
    # would leave every World created after with a settings file it refuses.
    dry_run_structure = models.CharField(max_length=20, default=default_dry_run_structure,
                                         validators=[a_dry_run_structure])
    # Whether each draft Mod is reconciled when it is submitted or revised,
    # in every World that does not say otherwise (see `reconciling.py`). Off
    # until an Organization Admin turns it on, since each run is paid for in
    # LLM tokens. Kept in the database, not in any World's settings file.
    reconciles_on_submission = models.BooleanField(default=False)
    # Whether each World is reviewed by the app's LLM after each Event, by the
    # scheduled `run_world_reviews` command, in every World that does not say
    # otherwise (see `world_reviewing.py`). Off until an Organization Admin
    # turns it on, for the same reason.
    reviews_after_events = models.BooleanField(default=False)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        a_dry_run_structure(self.dry_run_structure)
        super().save(*args, **kwargs)


class Membership(models.Model):
    """A person's place in an Organization. `is_admin` makes them an
    Organization Admin, the only role held across a whole Organization."""

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE,
                                     related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="memberships")
    is_admin = models.BooleanField(default=False)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "user"],
                                    name="one_membership_per_person"),
        ]


class World(models.Model):
    """A setting whose Canon is shared by everyone who plays in it."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE,
                                     related_name="worlds")
    name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    # The World's settings file, `world.yml`, exactly as it stands, or empty
    # for a World that has none (plotcanon then uses its defaults). It is one
    # of the World's files, and `canon.storing.files_of` gives it with the
    # rest, so plotcanon checks every change against it and an export writes
    # it out. It is kept here rather than as a `canon.Document` row because it
    # is not a document: it has no id, type or name, and the app takes "the
    # World has Canon" to mean "the World has a document", which a new
    # World's settings file must not make true. A World is created with its
    # Organization's default Dry Run structure in it, however it is created.
    settings_file = models.TextField(blank=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self._state.adding and not self.settings_file:
            # Read as the row is written, so an Organization this request may
            # not see gives nothing, and the database refuses the World.
            structure = (Organization.objects.filter(pk=self.organization_id)
                         .values_list("dry_run_structure", flat=True).first())
            if structure:
                self.settings_file = settings_file_for(structure)
        super().save(*args, **kwargs)


class Role(models.TextChoices):
    """The roles a person can hold in one World."""

    PLOT_MASTER = "plot-master", "Plot Master"
    MOD_WRITER = "mod-writer", "Mod Writer"
    MOD_RUNNER = "mod-runner", "Mod Runner"


# Who may write Mods in a World: its Mod Writers, and its Plot Masters, who
# may do anything a Mod Writer may.
# Role rows only: an Admin who holds neither role is not counted. Open question.
WRITES_MODS = (Role.MOD_WRITER, Role.PLOT_MASTER)  # noqa: TID251


class WorldRole(models.Model):
    """One role held by one person in one World. A person can hold several."""

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE,
                                     related_name="+")
    # The database also requires the World to be in the same Organization as
    # this row; see `rls.same_organization` in the migrations.
    # Likewise the person must belong to this Organization.
    world = models.ForeignKey(World, on_delete=models.CASCADE, related_name="roles")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="world_roles")
    role = models.CharField(max_length=20, choices=Role)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["world", "user", "role"],
                                    name="one_of_each_role_per_person"),
        ]


class WorldOverride(models.Model):
    """An Organization Admin's say on one of the settings in `llm_runs.py`
    for one World, over the Organization's setting. A World with no row
    follows the Organization."""

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE,
                                     related_name="+")
    on = models.BooleanField()

    class Meta:
        abstract = True


class ReconcilingOverride(WorldOverride):
    """Whether one World's drafts are reconciled when they are submitted
    (see `reconciling.py`)."""

    # The database also requires the World to be in the same Organization as
    # this row; see `rls.same_organization` in the migrations.
    world = models.OneToOneField(World, on_delete=models.CASCADE,
                                 related_name="reconciling_override")


class WorldReviewOverride(WorldOverride):
    """Whether one World is reviewed after each Event (see
    `world_reviewing.py`)."""

    # The database also requires the World to be in the same Organization as
    # this row; see `rls.same_organization` in the migrations.
    world = models.OneToOneField(World, on_delete=models.CASCADE,
                                 related_name="world_review_override")


class InvitationQuerySet(models.QuerySet):
    def waiting(self):
        """Neither accepted nor declined yet."""
        return self.filter(accepted_at__isnull=True, declined_at__isnull=True)

    def declined(self):
        return self.filter(declined_at__isnull=False)

    def waiting_for(self, user):
        """The invitations sent to this person's address that they have not
        answered yet."""
        return self.filter(email=user.email).waiting()


class Invitation(models.Model):
    """An email address an Organization Admin has asked to join. The person is
    shown it when they sign in with that address, and accepts or declines.
    Until they do, it is waiting."""

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE,
                                     related_name="invitations")
    email = models.EmailField()
    invited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                   related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    declined_at = models.DateTimeField(null=True, blank=True)

    objects = InvitationQuerySet.as_manager()

    class Meta:
        ordering = ["email"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "email"],
                                    name="one_invitation_per_address"),
        ]
