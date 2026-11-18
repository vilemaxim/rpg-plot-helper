from django.db import migrations

from organizations import rls


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0012_reconciling_override"),
    ]

    operations = [
        rls.protect("organizations_reconcilingoverride"),
        rls.same_organization("organizations_reconcilingoverride", "world_id",
                              "organizations_world"),
    ]
