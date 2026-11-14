from django.db import migrations

from organizations import rls

# A person may see every Organization they belong to, and their own place in
# each, before one of them is chosen for the request. Adding or changing a row
# still needs the Organization to be set.
MEMBER_OF = ("id = app_organization_id() OR id IN ("
             "SELECT organization_id FROM organizations_membership "
             "WHERE user_id = app_user_id())")
OWN_MEMBERSHIP = f"{rls.OWN_ORGANIZATION} OR user_id = app_user_id()"


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(rls.FUNCTIONS, rls.DROP_FUNCTIONS),
        rls.protect("organizations_organization",
                    using=MEMBER_OF, with_check="id = app_organization_id()"),
        rls.protect("organizations_membership", using=OWN_MEMBERSHIP),
        rls.protect("organizations_world"),
        rls.protect("organizations_worldrole"),
        rls.allow_references_within_organization("organizations_world"),
        rls.same_organization("organizations_worldrole", "world_id", "organizations_world"),
    ]
