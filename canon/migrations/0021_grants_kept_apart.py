from django.db import migrations

from organizations import rls


class Migration(migrations.Migration):

    dependencies = [
        ("canon", "0020_grants"),
    ]

    operations = [
        rls.protect("canon_grant"),
        rls.same_organization("canon_grant", "world_id", "organizations_world"),
        rls.same_organization("canon_grant", "document_id", "canon_document"),
        # Only someone who belongs to the Organization can hold a Grant.
        # Removing their Membership removes their Grants, as it does their
        # roles and Assignments.
        rls.same_organization("canon_grant", "person_id", "organizations_membership",
                              target_column="user_id"),
        rls.allow_references_within_organization("canon_assignment"),
        rls.same_organization("canon_grant", "assignment_id", "canon_assignment"),
    ]
