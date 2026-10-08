"""Thin SQL executor over ``db.session`` (raw SQL, no model imports).

Fault recipes and snapshot only need table names, so they run through this
interface and can be unit-tested with a fake of the same shape.
"""


def escape_colons(sql):
    """Protect literal colons from SQLAlchemy ``text()`` bind parsing (pure)."""
    return sql.replace(":", "\\:")


class SessionDb(object):
    """query/execute/commit/rollback over the Flask-SQLAlchemy session."""

    def __init__(self):
        from invenio_db import db

        self._db = db

    def _stmt(self, sql, params):
        from sqlalchemy import text

        return text(escape_colons(sql) if params is None else sql), (params or {})

    def query(self, sql, params=None):
        """Run a SELECT and return a list of dicts."""
        stmt, binds = self._stmt(sql, params)
        result = self._db.session.execute(stmt, binds)
        keys = list(result.keys())
        return [dict(zip(keys, row)) for row in result.fetchall()]

    def execute(self, sql, params=None):
        """Run a statement without returning rows."""
        stmt, binds = self._stmt(sql, params)
        self._db.session.execute(stmt, binds)

    def commit(self):
        self._db.session.commit()

    def rollback(self):
        self._db.session.rollback()
