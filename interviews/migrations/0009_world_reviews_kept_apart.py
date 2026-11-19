from django.db import migrations

from organizations import rls


class Migration(migrations.Migration):

    dependencies = [
        ("interviews", "0008_world_reviews"),
    ]

    operations = [
        rls.protect("interviews_worldreview"),
        rls.same_organization("interviews_worldreview", "world_id", "organizations_world"),
        rls.protect("interviews_worldreviewdismissal"),
        rls.same_organization("interviews_worldreviewdismissal", "world_id",
                              "organizations_world"),
    ]
