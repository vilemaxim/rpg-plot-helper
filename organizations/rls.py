"""Row-level security: the database's own check that one Organization never
sees another's rows, beneath the app's own checks.

It guards against a mistake in the app's queries, such as a view that forgets
to filter by Organization. It is not a guard against the app running arbitrary
SQL: the app's database user owns these tables, and an owner can switch the
policies off. The database also trusts the Organization it is told; choosing it
correctly is `tenancy.activate`'s job.

Each request tells Postgres who is asking and for which Organization (see
`tenancy.py`). Every protected table has a policy that shows only the rows for
that Organization. With nothing set, a query returns no rows at all.

`FORCE` matters: the app's database user owns these tables, and without it
Postgres would not apply the policies to the owner.
"""

from django.db import migrations

# What the current request has told the database. Empty means "not set".
FUNCTIONS = """
CREATE FUNCTION app_organization_id() RETURNS uuid LANGUAGE sql STABLE AS
$$ SELECT NULLIF(pg_catalog.current_setting('app.organization_id', true), '')::uuid $$;

CREATE FUNCTION app_user_id() RETURNS bigint LANGUAGE sql STABLE AS
$$ SELECT NULLIF(pg_catalog.current_setting('app.user_id', true), '')::bigint $$;
"""

DROP_FUNCTIONS = """
DROP FUNCTION app_user_id();
DROP FUNCTION app_organization_id();
"""

# Rows that belong to one Organization: visible and writable only when that
# Organization is the one set.
OWN_ORGANIZATION = "organization_id = app_organization_id()"


def protect(table, *, using=OWN_ORGANIZATION, with_check=OWN_ORGANIZATION):
    """Turn on row-level security for a table.

    `using` decides which existing rows can be seen, changed or deleted.
    `with_check` decides which rows may be written.
    """
    return migrations.RunSQL(
        sql=f"""
            ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
            ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
            CREATE POLICY organization_isolation ON {table}
                USING ({using}) WITH CHECK ({with_check});
        """,
        reverse_sql=f"""
            DROP POLICY organization_isolation ON {table};
            ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;
            ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;
        """,
    )


def allow_references_within_organization(table):
    """Let other tables point at this one in a way that also pins the
    Organization. Needed once per table that `same_organization` refers to."""
    return migrations.RunSQL(
        sql=f"ALTER TABLE {table} ADD CONSTRAINT {table}_organization_and_id "
            f"UNIQUE (organization_id, id);",
        reverse_sql=f"ALTER TABLE {table} DROP CONSTRAINT {table}_organization_and_id;",
    )


def same_organization(table, column, target, target_column="id", on_delete="CASCADE"):
    """Require that the row `column` points at belongs to the same Organization
    as the row itself. `target` needs a unique constraint on
    `(organization_id, target_column)`.

    Postgres does not apply row-level security to its own foreign-key checks,
    so without this a row in one Organization could point at another's.

    Adding the constraint is different: Postgres checks the rows already there
    with an ordinary query, which row-level security would hide, so every
    existing row would pass unchecked. Row-level security is lifted from both
    tables while the constraint is added, so that a row that breaks it stops
    the migration.

    `on_delete` is what happens to this row when the row it points at goes.
    To keep the row and empty the reference, it is `SET NULL ({column})`: the
    Organization column stays, as it is part of the row's own identity.
    """
    name = f"{table}_{column}_same_organization"
    return migrations.RunSQL(
        sql=f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY; "
            f"ALTER TABLE {target} NO FORCE ROW LEVEL SECURITY; "
            f"ALTER TABLE {table} ADD CONSTRAINT {name} "
            f"FOREIGN KEY (organization_id, {column}) "
            f"REFERENCES {target} (organization_id, {target_column}) ON DELETE {on_delete}; "
            f"ALTER TABLE {target} FORCE ROW LEVEL SECURITY; "
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;",
        reverse_sql=f"ALTER TABLE {table} DROP CONSTRAINT {name};",
    )
