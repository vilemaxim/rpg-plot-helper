from django.db import migrations

from organizations import rls

# An invited person may see their own invitation before they belong to the
# Organization, which is how signing in finds it. The list of people is not
# under row-level security, so it can be read here.
OWN_INVITATION = (f"{rls.OWN_ORGANIZATION} OR email = ("
                  "SELECT email FROM accounts_user WHERE id = app_user_id())")


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0003_invitation"),
    ]

    operations = [
        rls.protect("organizations_invitation", using=OWN_INVITATION),
        # A role can only be held by someone who belongs to the Organization.
        # Removing their Membership removes their roles.
        rls.same_organization("organizations_worldrole", "user_id",
                              "organizations_membership", target_column="user_id"),
    ]
