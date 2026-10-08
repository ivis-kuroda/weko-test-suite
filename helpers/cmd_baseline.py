"""baseline: read-only facts about what the install.sh demo data provides.

Raw SQL only (no WEKO model imports), so the query set is unit-testable with
a fake executor. The host side (``seeds/bootstrap.py baseline-check``) decides
what is missing; this command only reports what exists. Secrets are never
selected: no password hashes, token values or client secrets.
"""

import contract

# Config keys reported verbatim (all are non-secret).
CONFIG_KEYS = (
    "WEKO_ITEMS_UI_SHARED_USER_EXCLUDED_ROLE_NAME_LIST",
    "WEKO_SWORDSERVER_SERVICEDOCUMENT_ON_BEHALF_OF",
    "WEKO_SWORDSERVER_DEPOSIT_ROLE_ENABLE",
    "SESSION_COOKIE_SECURE",
    "SERVER_NAME",
)


def parse(params):
    """Validate baseline arguments (pure)."""
    recids = params.get("recids")
    recid_list = []
    if recids is not None:
        if not isinstance(recids, list):
            raise contract.HelperError("InvalidArgument", "recids must be a list")
        for value in recids:
            if isinstance(value, bool) or not isinstance(value, (str, int)):
                raise contract.HelperError("InvalidArgument", "recids must be strings or integers")
            if not str(value).isdigit():
                raise contract.HelperError("InvalidArgument", "recids must be decimal")
            recid_list.append(str(value))
    ids = params.get("index_ids")
    index_ids = []
    if ids is not None:
        if not isinstance(ids, list) or any(
            isinstance(i, bool) or not isinstance(i, int) for i in ids
        ):
            raise contract.HelperError("InvalidArgument", "index_ids must be a list of integers")
        index_ids = list(ids)
    return {
        "emails": contract.str_list(params, "emails", default=[]),
        "recids": recid_list,
        "index_ids": index_ids,
    }


def collect(db, args, config=None):
    """Run the lookups through ``db`` (query(sql, params) -> list of dicts)."""
    facts = {}
    facts["roles"] = sorted(r["name"] for r in db.query("SELECT name FROM accounts_role"))

    users = {}
    for email in args["emails"]:
        rows = db.query(
            "SELECT id, active, confirmed_at FROM accounts_user WHERE email = :e", {"e": email}
        )
        if not rows:
            users[email] = None
            continue
        role_rows = db.query(
            "SELECT r.name AS name FROM accounts_userrole ur "
            "JOIN accounts_role r ON r.id = ur.role_id WHERE ur.user_id = :u",
            {"u": rows[0]["id"]},
        )
        confirmed = rows[0]["confirmed_at"]
        users[email] = {
            "active": bool(rows[0]["active"]),
            "confirmed": confirmed is not None,
            "roles": sorted(r["name"] for r in role_rows),
        }
    facts["users"] = users

    facts["item_types"] = [
        {"id": r["id"], "name": r["name"]}
        for r in db.query(
            "SELECT it.id AS id, itn.name AS name FROM item_type it "
            "LEFT JOIN item_type_name itn ON itn.id = it.name_id "
            "WHERE it.is_deleted = false ORDER BY it.id"
        )
    ]
    facts["jsonld_mappings"] = [
        {"id": r["id"], "name": r["name"], "item_type_id": r["item_type_id"]}
        for r in db.query(
            "SELECT id, name, item_type_id FROM jsonld_mappings "
            "WHERE is_deleted = false ORDER BY id"
        )
    ]
    facts["flows"] = [
        {"id": r["id"], "name": r["flow_name"], "flow_type": r["flow_type"]}
        for r in db.query(
            "SELECT id, flow_name, flow_type FROM workflow_flow_define "
            "WHERE is_deleted = false ORDER BY id"
        )
    ]
    facts["workflows"] = [
        {
            "id": r["id"],
            "name": r["flows_name"],
            "itemtype_id": r["itemtype_id"],
            "flow_id": r["flow_id"],
            "delete_flow_id": r["delete_flow_id"],
        }
        for r in db.query(
            "SELECT id, flows_name, itemtype_id, flow_id, delete_flow_id "
            "FROM workflow_workflow WHERE is_deleted = false ORDER BY id"
        )
    ]
    facts["indexes"] = [
        r["id"]
        for r in db.query('SELECT id FROM "index" ORDER BY id LIMIT 50')
        if not args["index_ids"] or r["id"] in args["index_ids"]
    ]
    facts["locations"] = [
        {"name": r["name"], "uri": r["uri"], "default": bool(r["default"])}
        for r in db.query('SELECT name, uri, "default" FROM files_location ORDER BY id')
    ]
    facts["admin_settings"] = [
        {"id": r["id"], "name": r["name"]}
        for r in db.query("SELECT id, name FROM admin_settings ORDER BY id")
    ]
    facts["counts"] = {
        "sword_clients": db.query("SELECT count(*) AS n FROM sword_clients")[0]["n"],
        "oauth_clients": db.query("SELECT count(*) AS n FROM oauth2server_client")[0]["n"],
        "oauth_tokens": db.query("SELECT count(*) AS n FROM oauth2server_token")[0]["n"],
        "communities": db.query("SELECT count(*) AS n FROM communities_community")[0]["n"],
    }
    recids = {}
    for recid in args["recids"]:
        rows = db.query(
            "SELECT status FROM pidstore_pid WHERE pid_type = 'recid' AND pid_value = :v",
            {"v": recid},
        )
        recids[recid] = rows[0]["status"] if rows else None
    facts["recids"] = recids
    facts["config"] = {key: (config or {}).get(key) for key in CONFIG_KEYS}
    return facts


def run(params):
    """Report the baseline facts. UNVERIFIED until run in a real container."""
    from flask import current_app

    from dbx import SessionDb

    args = parse(params)
    return collect(SessionDb(), args, dict(current_app.config))
