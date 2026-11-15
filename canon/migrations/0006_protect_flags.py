from django.db import migrations

from organizations import rls


class Migration(migrations.Migration):

    dependencies = [
        ("canon", "0005_flags"),
    ]

    operations = [
        rls.protect("canon_flag"),
        rls.same_organization("canon_flag", "world_id", "organizations_world"),
        rls.same_organization("canon_flag", "mod_id", "canon_document"),
        rls.allow_references_within_organization("canon_canonchange"),
        rls.same_organization("canon_flag", "change_id", "canon_canonchange"),
    ]
