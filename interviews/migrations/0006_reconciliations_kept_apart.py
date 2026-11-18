from django.db import migrations

from organizations import rls


class Migration(migrations.Migration):

    dependencies = [
        ("interviews", "0005_reconciliations"),
    ]

    operations = [
        rls.protect("interviews_reconciliation"),
        rls.same_organization("interviews_reconciliation", "world_id", "organizations_world"),
        rls.same_organization("interviews_reconciliation", "mod_id", "canon_document"),
    ]
