from django.db import migrations

# How many Organizations exist, kept in a table that row-level security does
# not cover. A request can see only its own Organization, so it cannot count
# them; with sign-up closed the app still has to know whether there is one yet
# (ADR-0005). Triggers keep the number right however a row comes or goes.
#
# The first count has to see every Organization, so row-level security is
# lifted from the table for the length of that one statement.
COUNT = """
CREATE TABLE organizations_total (
    only_row boolean PRIMARY KEY DEFAULT true CHECK (only_row),
    total integer NOT NULL
);

ALTER TABLE organizations_organization NO FORCE ROW LEVEL SECURITY;
INSERT INTO organizations_total (total) SELECT count(*) FROM organizations_organization;
ALTER TABLE organizations_organization FORCE ROW LEVEL SECURITY;

CREATE FUNCTION organizations_total_changed() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        UPDATE organizations_total SET total = total + 1;
    ELSE
        UPDATE organizations_total SET total = total - 1;
    END IF;
    RETURN NULL;
END
$$;

CREATE TRIGGER organizations_total_changed
    AFTER INSERT OR DELETE ON organizations_organization
    FOR EACH ROW EXECUTE FUNCTION organizations_total_changed();
"""

UNDO = """
DROP TRIGGER organizations_total_changed ON organizations_organization;
DROP FUNCTION organizations_total_changed();
DROP TABLE organizations_total;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0004_protect_invitations_and_roles"),
    ]

    operations = [
        migrations.RunSQL(COUNT, UNDO),
    ]
