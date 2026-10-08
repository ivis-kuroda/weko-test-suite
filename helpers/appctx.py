"""Create the Flask application context inside the ``web`` container.

UNVERIFIED: the default factory is ``invenio_app.factory:create_app`` (the same
module family uwsgi serves via ``invenio_app.wsgi``). Override with the
``ATH_HELPERS_APP_FACTORY`` environment variable (``module:callable``).
"""

import contextlib
import importlib
import os
import sys

DEFAULT_FACTORIES = (
    "invenio_app.factory:create_app",
    "invenio_app.factory:create_ui",
)


def load_factory(spec):
    """Import ``module:callable``."""
    module_name, _, attr = spec.partition(":")
    return getattr(importlib.import_module(module_name), attr)


def build_app():
    """Return a configured WEKO app, trying the documented factories."""
    override = os.environ.get("ATH_HELPERS_APP_FACTORY")
    specs = (override,) if override else DEFAULT_FACTORIES
    last = None
    for spec in specs:
        try:
            return load_factory(spec)()
        except Exception as ex:  # try the next factory
            sys.stderr.write("app factory %s failed: %r\n" % (spec, ex))
            last = ex
    raise last


@contextlib.contextmanager
def app_context(app_factory=None):
    """Yield inside ``app.app_context()``; roll back the session on error."""
    app = (app_factory or build_app)()
    with app.app_context():
        try:
            yield app
        except Exception:
            try:
                from invenio_db import db

                db.session.rollback()
            except Exception:  # pragma: no cover - best effort
                pass
            raise
