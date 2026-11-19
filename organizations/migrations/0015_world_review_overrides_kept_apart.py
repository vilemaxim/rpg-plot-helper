from django.db import migrations

from organizations import rls

# A scheduled command, with no person and no Organization, has to find the
# Organizations that review their Worlds after each Event (ADR-0013). While a
# transaction says `app.all_organizations` (`tenancy.all_organizations`), it
# may read every Organization's row. Nothing else is opened by it: no other
# table, and no Organization may be written or deleted that way, since this
# policy is for SELECT alone.
LISTED = "pg_catalog.current_setting('app.all_organizations', true) = 'on'"


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0014_world_review_setting"),
    ]

    operations = [
        rls.protect("organizations_worldreviewoverride"),
        rls.same_organization("organizations_worldreviewoverride", "world_id",
                              "organizations_world"),
        migrations.RunSQL(
            sql=f"CREATE POLICY listed_for_scheduled_work ON organizations_organization "
                f"FOR SELECT USING ({LISTED});",
            reverse_sql="DROP POLICY listed_for_scheduled_work ON organizations_organization;"),
    ]
