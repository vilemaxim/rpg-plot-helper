from django.db import migrations

from organizations import rls


class Migration(migrations.Migration):

    dependencies = [
        ("canon", "0001_initial"),
        ("organizations", "0008_invited_people_see_the_organization"),
    ]

    operations = [
        rls.protect("canon_document"),
        rls.same_organization("canon_document", "world_id", "organizations_world"),
    ]
