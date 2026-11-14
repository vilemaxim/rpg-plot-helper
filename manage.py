#!/usr/bin/env python
"""Django's command-line utility. Uses the local-development settings unless
DJANGO_SETTINGS_MODULE says otherwise."""
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "plothelper.settings.local")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
