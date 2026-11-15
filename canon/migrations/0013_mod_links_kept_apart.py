from django.db import migrations

from organizations import rls

# A request with no Organization set may see one link: the one whose secret's
# hash it presents (`tenancy.present_link`). That is how a Mod Runner with no
# account is told which Organization their link belongs to. Nothing else is
# opened by it. A link cannot be written that way (the check on new rows is
# the Organization alone), nor deleted (a second, restrictive policy).
PRESENTED = ("organization_id = app_organization_id() OR "
             "token_hash = NULLIF(pg_catalog.current_setting('app.mod_link', true), '')")


class Migration(migrations.Migration):

    dependencies = [
        ("canon", "0012_mod_links"),
    ]

    operations = [
        rls.protect("canon_modlink", using=PRESENTED),
        migrations.RunSQL(
            sql="CREATE POLICY deleted_within_organization ON canon_modlink AS RESTRICTIVE "
                "FOR DELETE USING (organization_id = app_organization_id());",
            reverse_sql="DROP POLICY deleted_within_organization ON canon_modlink;"),
        rls.same_organization("canon_modlink", "world_id", "organizations_world"),
        rls.same_organization("canon_modlink", "mod_id", "canon_document"),
        rls.allow_references_within_organization("canon_modlink"),
        rls.same_organization("canon_document", "filed_through_id", "canon_modlink",
                              on_delete="SET NULL (filed_through_id)"),
    ]
