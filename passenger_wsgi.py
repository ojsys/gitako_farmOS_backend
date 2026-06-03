"""Passenger entrypoint for cPanel "Setup Python App".

cPanel runs the app under Phusion Passenger and looks for a module-level
`application` callable in this file at the app root. We force the production
settings module and reuse the project's WSGI app.

App root in cPanel must be this `backend/` directory.
"""
import os
import sys

# Make sure this directory (containing the `gitako` package) is importable.
sys.path.insert(0, os.path.dirname(__file__))

# Force production settings (overrides the dev default in gitako/wsgi.py).
os.environ["DJANGO_SETTINGS_MODULE"] = "gitako.settings.prod"

from gitako.wsgi import application  # noqa: E402  (import after env is set)
