"""create_token / revoke_token: personal OAuth2 tokens with exact scopes.

``access_token`` is returned by create_token only; no other command, and no
snapshot, ever returns a token value.

The library does not forbid an empty scope list: ``Token.create_personal``
stores ``""`` for it. Scope validation exists only in the CLI
(``process_scopes``), so unknown scopes are accepted by the model; this helper
validates against the registered scopes unless ``allow_unknown_scopes`` is set.
"""

import re

import contract

SCOPE_RE = re.compile(r"^[A-Za-z0-9:_.\-]+$")
CLIENT_NAME_MAX = 40  # oauth2server_client.name is String(40)
DEFAULT_TOKEN_PREFIX = "WEKO_TEST_TOKEN_"  # matches the redact pattern in plugin.yaml
PREFIX_RE = re.compile(r"^[A-Za-z0-9_]{0,32}$")


def parse(params):
    """Validate create_token arguments (pure)."""
    name = contract.require_str(params, "name")
    client_name = contract.optional_str(params, "client_name", name)
    if len(client_name) > CLIENT_NAME_MAX:
        raise contract.HelperError(
            "InvalidArgument", "client_name must be at most %d chars" % CLIENT_NAME_MAX
        )
    scopes = contract.str_list(params, "scopes", default=[])
    for scope in scopes:
        if not SCOPE_RE.match(scope):
            raise contract.HelperError("InvalidArgument", "malformed scope: %r" % scope)
    prefix = params.get("token_prefix", DEFAULT_TOKEN_PREFIX)
    if not isinstance(prefix, str) or not PREFIX_RE.match(prefix):
        raise contract.HelperError(
            "InvalidArgument", "token_prefix must match %s" % PREFIX_RE.pattern
        )
    return {
        "user_email": contract.require_email(params, "user_email"),
        "name": name,
        "client_name": client_name,
        "scopes": scopes,
        "token_prefix": prefix,
        "allow_unknown_scopes": contract.optional_bool(params, "allow_unknown_scopes", False),
    }


def mint_token_value(prefix, random_part):
    """Token string: redactable prefix plus a random tail (pure)."""
    return prefix + random_part


def parse_revoke(params):
    """Validate revoke_token arguments (pure): access_token xor name."""
    token = params.get("access_token")
    name = params.get("name")
    if bool(token) == bool(name):
        raise contract.HelperError("InvalidArgument", "give exactly one of access_token or name")
    if token is not None and not isinstance(token, str):
        raise contract.HelperError("InvalidArgument", "access_token must be a string")
    if name is not None and not isinstance(name, str):
        raise contract.HelperError("InvalidArgument", "name must be a string")
    return {
        "access_token": token or None,
        "name": name or None,
        "user_email": contract.optional_str(params, "user_email"),
    }


def scope_string(scopes):
    """Join scopes the way oauth2server stores them (pure)."""
    return " ".join(scopes) if scopes else ""


def _known_scopes():
    from invenio_oauth2server import current_oauth2server

    return set(current_oauth2server.scopes.keys())


def run(params):
    """ORM part. UNVERIFIED until run in a real WEKO container."""
    from invenio_accounts.models import User
    from invenio_db import db
    from invenio_oauth2server.models import Client, Token

    args = parse(params)
    if args["scopes"] and not args["allow_unknown_scopes"]:
        unknown = sorted(set(args["scopes"]) - _known_scopes())
        if unknown:
            raise contract.HelperError(
                "UnknownScope", "unregistered scopes: %s" % ", ".join(unknown), scopes=unknown
            )
    user = User.query.filter_by(email=args["user_email"]).one_or_none()
    if user is None:
        raise contract.HelperError("UserNotFound", "no such user: %s" % args["user_email"])

    client = Client.query.filter_by(
        name=args["client_name"], user_id=user.id, is_internal=True
    ).first()
    token = None
    if client is not None:
        token = Token.query.filter_by(
            client_id=client.client_id, user_id=user.id, is_personal=True
        ).first()

    reused = token is not None
    previous_scopes = None
    wanted = scope_string(args["scopes"])
    if token is None and not args["token_prefix"]:
        token = Token.create_personal(args["client_name"], user.id, scopes=args["scopes"])
    elif token is None:
        # Same rows as Token.create_personal, but with a prefixed access token so that
        # evidence redaction (plugin.yaml redact.patterns) can recognise it.
        from flask import current_app
        from werkzeug.security import gen_salt

        with db.session.begin_nested():
            client = Client(
                name=args["client_name"],
                user_id=user.id,
                is_internal=True,
                is_confidential=False,
                _default_scopes=wanted,
            )
            client.gen_salt()
            tail = gen_salt(current_app.config.get("OAUTH2SERVER_TOKEN_PERSONAL_SALT_LEN", 60))
            token = Token(
                client_id=client.client_id,
                user_id=user.id,
                access_token=mint_token_value(args["token_prefix"], tail),
                expires=None,
                _scopes=wanted,
                is_personal=True,
                is_internal=False,
            )
            db.session.add(client)
            db.session.add(token)
    elif (token._scopes or "") != wanted:
        previous_scopes = (token._scopes or "").split()
        token._scopes = wanted
        client._default_scopes = wanted
    db.session.commit()
    return {
        "access_token": token.access_token,
        "token_id": token.id,
        "client_id": token.client_id,
        "user_id": user.id,
        "scopes": wanted.split(),
        "reused": reused,
        "previous_scopes": previous_scopes,
    }


def run_revoke(params):
    """Delete a personal token (and its personal client). UNVERIFIED."""
    from invenio_accounts.models import User
    from invenio_db import db
    from invenio_oauth2server.models import Client, Token

    args = parse_revoke(params)
    if args["access_token"]:
        tokens = Token.query.filter(Token.access_token == args["access_token"]).all()
    else:
        query = Client.query.filter_by(name=args["name"], is_internal=True)
        if args["user_email"]:
            user = User.query.filter_by(email=args["user_email"]).one_or_none()
            if user is None:
                raise contract.HelperError("UserNotFound", "no such user: %s" % args["user_email"])
            query = query.filter_by(user_id=user.id)
        client_ids = [c.client_id for c in query.all()]
        tokens = (
            Token.query.filter(Token.client_id.in_(client_ids), Token.is_personal.is_(True)).all()
            if client_ids
            else []
        )
    deleted = []
    client_ids = set()
    for token in tokens:
        deleted.append(
            {
                "token_id": token.id,
                "client_id": token.client_id,
                "user_id": token.user_id,
                "scopes": token.scopes,
            }
        )
        client_ids.add(token.client_id)
        db.session.delete(token)
    db.session.flush()
    deleted_clients = []
    for client_id in sorted(client_ids):
        client = Client.query.filter_by(client_id=client_id).one_or_none()
        if client is not None and client.is_internal and not client.sword_client.count():
            deleted_clients.append(client_id)
            db.session.delete(client)
    db.session.commit()
    return {"deleted_tokens": deleted, "deleted_clients": deleted_clients}
