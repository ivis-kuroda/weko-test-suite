"""create_user: ensure a confirmed, active user with the given roles exists."""

import contract


def parse(params):
    """Validate arguments (pure)."""
    return {
        "email": contract.require_email(params, "email"),
        "password": contract.require_str(params, "password"),
        "roles": contract.str_list(params, "roles", default=[]),
        "reset_password": contract.optional_bool(params, "reset_password", False),
    }


def missing_roles(have, wanted):
    """Roles in ``wanted`` that the user does not have yet, order kept (pure)."""
    return [r for r in wanted if r not in set(have)]


def run(params):
    """ORM part. UNVERIFIED until run in a real WEKO container."""
    import datetime

    from flask import current_app
    from flask_security.utils import hash_password
    from invenio_accounts.models import Role, User
    from invenio_db import db

    args = parse(params)
    ds = current_app.extensions["invenio-accounts"].datastore

    created_roles = []
    role_objs = []
    for name in args["roles"]:
        role = Role.query.filter_by(name=name).one_or_none()
        if role is None:
            role = ds.create_role(name=name)
            created_roles.append(name)
        role_objs.append(role)
    db.session.flush()

    user = User.query.filter_by(email=args["email"]).one_or_none()
    created = user is None
    previous = None
    if created:
        user = ds.create_user(
            email=args["email"],
            password=hash_password(args["password"]),
            active=True,
            confirmed_at=datetime.datetime.utcnow(),
        )
    else:
        previous = {
            "active": user.active,
            "confirmed_at": user.confirmed_at.isoformat() if user.confirmed_at else None,
        }
        user.active = True
        if user.confirmed_at is None:
            user.confirmed_at = datetime.datetime.utcnow()
        if args["reset_password"]:
            user.password = hash_password(args["password"])
    db.session.flush()

    have = [r.name for r in user.roles]
    added = missing_roles(have, args["roles"])
    for role in role_objs:
        if role.name in added:
            ds.add_role_to_user(user, role)
    db.session.commit()
    return {
        "id": user.id,
        "email": user.email,
        "created": created,
        "created_roles": created_roles,
        "roles_added": added,
        "previous": previous,
    }
