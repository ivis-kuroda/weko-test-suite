"""JSON contract and argument validation shared by every helper command.

Pure logic: this module must never import WEKO or any third party package.
"""

import json
import re

IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+$")
SQLSTATE_RE = re.compile(r"^[0-9A-Z]{5}$")


class HelperError(Exception):
    """An expected failure that is reported as ``ok: false``."""

    def __init__(self, type_, message, **extra):
        super(HelperError, self).__init__(message)
        self.type = type_
        self.message = message
        self.extra = extra


def ok(result):
    """Build the success envelope."""
    return {"ok": True, "result": result}


def fail(type_, message, **extra):
    """Build the failure envelope."""
    error = {"type": type_, "message": message}
    error.update(extra)
    return {"ok": False, "error": error}


def error_from_exception(ex):
    """Convert any exception into a failure envelope, keeping the SQLSTATE."""
    if isinstance(ex, HelperError):
        return fail(ex.type, ex.message, **ex.extra)
    extra = {}
    orig = getattr(ex, "orig", None)
    code = getattr(orig, "pgcode", None) or getattr(ex, "pgcode", None)
    if code:
        extra["sqlstate"] = code
    return fail(ex.__class__.__name__, str(ex), **extra)


def parse_request(text):
    """Parse the stdin payload; an empty payload means ``{}``."""
    if text is None or not text.strip():
        return {}
    try:
        data = json.loads(text)
    except ValueError as ex:
        raise HelperError("InvalidJson", "stdin is not valid JSON: %s" % ex) from ex
    if not isinstance(data, dict):
        raise HelperError("InvalidArgument", "stdin must be a JSON object")
    return data


def dumps(envelope):
    """Serialise an envelope on a single line."""
    return json.dumps(envelope, ensure_ascii=False, sort_keys=True, default=str)


def _bad(name, expected):
    return HelperError("InvalidArgument", "%s must be %s" % (name, expected))


def require_str(params, name, pattern=None):
    """Return a non-empty string parameter."""
    value = params.get(name)
    if not isinstance(value, str) or not value:
        raise _bad(name, "a non-empty string")
    if pattern is not None and not pattern.match(value):
        raise _bad(name, "a string matching %s" % pattern.pattern)
    return value


def optional_str(params, name, default=None):
    """Return a string parameter or the default when absent or null."""
    if params.get(name) is None:
        return default
    return require_str(params, name)


def optional_bool(params, name, default=False):
    """Return a boolean parameter."""
    value = params.get(name)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise _bad(name, "a boolean")
    return value


def optional_int(params, name, default=None):
    """Return an integer parameter (bool is rejected)."""
    value = params.get(name)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise _bad(name, "an integer")
    return value


def str_list(params, name, default=None):
    """Return a list of non-empty strings (order kept, duplicates removed)."""
    value = params.get(name)
    if value is None:
        if default is None:
            raise _bad(name, "a list of strings")
        return list(default)
    if not isinstance(value, list):
        raise _bad(name, "a list of strings")
    out = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise _bad(name, "a list of non-empty strings")
        if item not in out:
            out.append(item)
    return out


def require_email(params, name):
    """Return an email-looking string."""
    return require_str(params, name, EMAIL_RE)


def quote_literal(value):
    """Quote a scalar as a PostgreSQL literal (for DDL, which takes no binds)."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        if "\x00" in value:
            raise HelperError("InvalidArgument", "NUL is not allowed in values")
        return "'" + value.replace("'", "''") + "'"
    raise HelperError("InvalidArgument", "unsupported literal type: %s" % type(value).__name__)


def quote_ident(name):
    """Quote an identifier."""
    return '"' + str(name).replace('"', '""') + '"'
