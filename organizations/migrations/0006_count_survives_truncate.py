from django.db import migrations

# Emptying the table with TRUNCATE (which `manage.py flush` does) removes rows
# without firing the per-row trigger, so the count of Organizations would stay
# where it was. With sign-up closed that would tell the next person an
# Organization already exists, and lock everyone out.
RESET = """
CREATE FUNCTION organizations_total_reset() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    UPDATE organizations_total SET total = 0;
    RETURN NULL;
END
$$;

CREATE TRIGGER organizations_total_reset
    AFTER TRUNCATE ON organizations_organization
    FOR EACH STATEMENT EXECUTE FUNCTION organizations_total_reset();
"""

UNDO = """
DROP TRIGGER organizations_total_reset ON organizations_organization;
DROP FUNCTION organizations_total_reset();
"""


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0005_count_organizations"),
    ]

    operations = [
        migrations.RunSQL(RESET, UNDO),
    ]
