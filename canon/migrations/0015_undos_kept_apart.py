from django.db import migrations

from organizations import rls


class Migration(migrations.Migration):

    dependencies = [
        ("canon", "0014_undos"),
    ]

    operations = [
        rls.protect("canon_undo"),
        rls.same_organization("canon_undo", "world_id", "organizations_world"),
        rls.same_organization("canon_undo", "change_id", "canon_canonchange"),
    ]
