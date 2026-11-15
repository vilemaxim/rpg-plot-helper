from django.db import migrations

from organizations import rls


class Migration(migrations.Migration):

    dependencies = [
        ("canon", "0010_mod_writers"),
    ]

    operations = [
        rls.protect("canon_writerhandle"),
        rls.same_organization("canon_writerhandle", "world_id", "organizations_world"),
    ]
