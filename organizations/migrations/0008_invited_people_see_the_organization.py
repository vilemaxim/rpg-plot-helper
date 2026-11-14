from django.db import migrations

# A person deciding on an invitation needs to see which Organization it is
# from, before they belong to it. So an Organization is also visible to
# someone it has invited and who has not yet answered. The invitation itself
# is already visible to them (migration 0004).
INVITED = ("id IN (SELECT organization_id FROM organizations_invitation "
           "WHERE email = (SELECT email FROM accounts_user WHERE id = app_user_id()) "
           "AND accepted_at IS NULL AND declined_at IS NULL)")

MEMBER_OF = ("id = app_organization_id() OR id IN ("
             "SELECT organization_id FROM organizations_membership "
             "WHERE user_id = app_user_id())")

POLICY = """
DROP POLICY organization_isolation ON organizations_organization;
CREATE POLICY organization_isolation ON organizations_organization
    USING ({using}) WITH CHECK (id = app_organization_id());
"""


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0007_invitation_declined_at"),
    ]

    operations = [
        migrations.RunSQL(POLICY.format(using=f"{MEMBER_OF} OR {INVITED}"),
                          POLICY.format(using=MEMBER_OF)),
    ]
