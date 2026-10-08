"""ping: health check (app context OK, DB reachable, WEKO version)."""

import subprocess


def _weko_version():
    info = {}
    try:
        import pkg_resources

        for name in ("weko-swordserver", "weko-deposit", "invenio-app"):
            try:
                info[name] = pkg_resources.get_distribution(name).version
            except Exception:
                info[name] = None
    except Exception:
        pass
    return info


def _git_commit():
    for path in ("/code", "/opt/weko", "/home/invenio/weko"):
        try:
            out = subprocess.check_output(
                ["git", "-C", path, "rev-parse", "HEAD"], stderr=subprocess.DEVNULL
            )
            return out.decode().strip()
        except Exception:
            continue
    return None


def run(params):
    """Return DB connectivity and version information."""
    from flask import current_app
    from invenio_db import db
    from sqlalchemy import text

    row = db.session.execute(text("SELECT version(), current_user")).fetchone()
    return {
        "app": current_app.name,
        "db_ok": True,
        "db_version": row[0],
        "db_user": row[1],
        "packages": _weko_version(),
        "commit": _git_commit(),
    }
