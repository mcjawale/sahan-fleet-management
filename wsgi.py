"""WSGI entry point for PythonAnywhere and other hosts.

PythonAnywhere: set the WSGI config file to this file and the source to this
directory. Make sure SECRET_KEY is set in the environment.
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app import create_app, init_db  # noqa: E402

application = create_app()

with application.app_context():
    init_db(application)

# PythonAnywhere serves this object as "application".
app = application