from django.core.checks import Error, Tags, register
from django.db import connections


@register(Tags.database)
def database_user_obeys_row_level_security(databases=None, **kwargs):
    """Postgres does not apply row-level security to a superuser or to a role
    marked BYPASSRLS. Connecting as either would silently remove the wall
    between Organizations, so refuse to migrate or run checks that way."""
    errors = []
    for alias in databases or []:
        with connections[alias].cursor() as cursor:
            cursor.execute("SELECT current_user, rolsuper, rolbypassrls FROM pg_roles "
                           "WHERE rolname = current_user")
            name, is_superuser, bypasses = cursor.fetchone()
        if is_superuser or bypasses:
            errors.append(Error(
                f"The database user '{name}' is a superuser or has BYPASSRLS, so "
                "row-level security would not apply to it.",
                hint="Connect as an ordinary user that owns the app's tables. "
                     "Locally, scripts/db.sh creates one.",
                id="organizations.E001",
            ))
    return errors
