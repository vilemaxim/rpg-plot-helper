from django.db import migrations

from organizations import rls


class Migration(migrations.Migration):

    dependencies = [
        ("canon", "0018_assignments"),
    ]

    operations = [
        rls.protect("canon_assignment"),
        rls.same_organization("canon_assignment", "world_id", "organizations_world"),
        rls.same_organization("canon_assignment", "mod_id", "canon_document"),
        # Only someone who belongs to the Organization can be assigned.
        # Removing their Membership removes their Assignments, as it does
        # their roles.
        rls.same_organization("canon_assignment", "runner_id", "organizations_membership",
                              target_column="user_id"),
    ]
