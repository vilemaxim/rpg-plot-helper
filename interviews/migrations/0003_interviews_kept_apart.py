from django.db import migrations

from organizations import rls


class Migration(migrations.Migration):

    dependencies = [
        ("interviews", "0002_interviews"),
    ]

    operations = [
        rls.protect("interviews_interview"),
        rls.same_organization("interviews_interview", "world_id", "organizations_world"),
        rls.same_organization("interviews_interview", "mod_id", "canon_document"),
    ]
