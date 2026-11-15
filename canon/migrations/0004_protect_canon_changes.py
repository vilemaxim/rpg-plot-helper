from django.db import migrations

from organizations import rls


class Migration(migrations.Migration):

    dependencies = [
        ("canon", "0003_reports_and_canon_changes"),
    ]

    operations = [
        rls.protect("canon_canonchange"),
        rls.same_organization("canon_canonchange", "world_id", "organizations_world"),
        # A Canon Change belongs to the same Organization as its report.
        rls.allow_references_within_organization("canon_document"),
        rls.same_organization("canon_canonchange", "report_id", "canon_document"),
    ]
