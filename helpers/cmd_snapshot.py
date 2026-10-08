"""snapshot: row counts and per-row content hashes for allow-listed tables.

Never selects secrets: no token values, no password hashes, no client secrets.
Hashes are sha256 over canonical JSON of the selected columns only.
"""

import datetime
import decimal
import hashlib
import json
import uuid

import contract

# logical name -> table, key columns, hashed columns, column linking to a record uuid
SPECS = {
    "items": ("item_metadata", ["id"], ["id", "item_type_id", "json", "version_id"], "id"),
    "records": ("records_metadata", ["id"], ["id", "json", "version_id"], "id"),
    "pids": (
        "pidstore_pid",
        ["pid_type", "pid_value"],
        ["pid_type", "pid_value", "pid_provider", "status", "object_type", "object_uuid"],
        "object_uuid",
    ),
    "activities": (
        "workflow_activity",
        ["activity_id"],
        [
            "activity_id",
            "item_id",
            "workflow_id",
            "flow_id",
            "action_id",
            "action_status",
            "workflow_status",
            "activity_status",
            "activity_login_user",
        ],
        "item_id",
    ),
    "sword_clients": (
        "sword_clients",
        ["client_id"],
        [
            "client_id",
            "active",
            "registration_type_id",
            "mapping_id",
            "workflow_id",
            "duplicate_check",
            "meta_data_api",
        ],
        None,
    ),
    "tokens": (
        "oauth2server_token",
        ["id"],
        [
            "id",
            "client_id",
            "user_id",
            "token_type",
            "expires",
            "_scopes",
            "is_personal",
            "is_internal",
        ],
        None,
    ),
    "clients": (
        "oauth2server_client",
        ["client_id"],
        ["client_id", "name", "user_id", "is_confidential", "is_internal", "_default_scopes"],
        None,
    ),
    "users": ("accounts_user", ["email"], ["id", "email", "active", "confirmed_at"], None),
    "roles": ("accounts_role", ["name"], ["id", "name", "description"], None),
    "user_roles": ("accounts_userrole", ["user_id", "role_id"], ["user_id", "role_id"], None),
    "workflows": (
        "workflow_workflow",
        ["id"],
        [
            "id",
            "flows_id",
            "flows_name",
            "itemtype_id",
            "flow_id",
            "delete_flow_id",
            "index_tree_id",
        ],
        None,
    ),
    "flows": (
        "workflow_flow_define",
        ["id"],
        ["id", "flow_id", "flow_name", "flow_status", "is_deleted", "flow_type"],
        None,
    ),
    "flow_actions": (
        "workflow_flow_action",
        ["id"],
        ["id", "flow_id", "action_id", "action_order", "action_status", "action_condition"],
        None,
    ),
    "jsonld_mappings": (
        "jsonld_mappings",
        ["id"],
        ["id", "name", "item_type_id", "is_deleted", "mapping", "version_id"],
        None,
    ),
}


def parse(params):
    """Validate arguments (pure)."""
    tables = contract.str_list(params, "tables")
    for name in tables:
        if name not in SPECS:
            raise contract.HelperError(
                "InvalidArgument", "unknown table %r; known: %s" % (name, ", ".join(sorted(SPECS)))
            )
    recid = params.get("recid")
    if recid is not None and (isinstance(recid, bool) or not isinstance(recid, (str, int))):
        raise contract.HelperError("InvalidArgument", "recid must be a string or integer")
    return {"tables": tables, "recid": None if recid is None else str(recid)}


def _plain(value):
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, (uuid.UUID, decimal.Decimal)):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return hashlib.sha256(bytes(value)).hexdigest()
    return value


def row_hash(row):
    """sha256 of canonical JSON of a column->value mapping (pure)."""
    canonical = json.dumps(row, sort_keys=True, separators=(",", ":"), default=_plain)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def row_key(spec_keys, row):
    """Stable key of a row built from its key columns (pure)."""
    return ":".join(str(_plain(row[k])) for k in spec_keys)


def build_select(logical, filtered):
    """SELECT for one logical table; ``filtered`` restricts to one record."""
    table, keys, cols, link = SPECS[logical]
    sql = "SELECT %s FROM %s" % (
        ", ".join(contract.quote_ident(c) for c in cols),
        contract.quote_ident(table),
    )
    if filtered:
        sql += " WHERE %s = CAST(:u AS uuid)" % contract.quote_ident(link)
    return sql + " ORDER BY " + ", ".join(contract.quote_ident(k) for k in keys)


def summarize(logical, rows):
    """Turn fetched rows into ``{count, rows: {key: hash}}`` (pure)."""
    keys = SPECS[logical][1]
    hashed = {}
    for row in rows:
        hashed[row_key(keys, row)] = row_hash(row)
    return {"count": len(rows), "rows": hashed}


def diff(before, after):
    """Compare two per-table snapshot dicts: added/removed/changed keys (pure)."""
    out = {}
    for name in sorted(set(before) | set(after)):
        b = (before.get(name) or {}).get("rows", {})
        a = (after.get(name) or {}).get("rows", {})
        out[name] = {
            "added": sorted(set(a) - set(b)),
            "removed": sorted(set(b) - set(a)),
            "changed": sorted(k for k in set(a) & set(b) if a[k] != b[k]),
        }
    return out


def collect(db, args):
    """Run the selects through an executor (testable with a fake)."""
    record_uuid = None
    resolved = None
    if args["recid"] is not None:
        import rowlib

        found = db.query(rowlib.pid_uuid_sql(), {"v": args["recid"]})
        record_uuid = found[0]["u"] if found else None
        resolved = record_uuid is not None
    tables = {}
    for name in args["tables"]:
        link = SPECS[name][3]
        filtered = args["recid"] is not None and link is not None
        if filtered and record_uuid is None:
            tables[name] = {"count": 0, "rows": {}, "recid_filter": True}
            continue
        rows = db.query(build_select(name, filtered), {"u": record_uuid} if filtered else None)
        entry = summarize(name, rows)
        entry["recid_filter"] = filtered
        tables[name] = entry
    return {"recid": args["recid"], "recid_resolved": resolved, "tables": tables}


def run(params):
    """ORM-free part: raw SQL through db.session. UNVERIFIED."""
    from dbx import SessionDb

    return collect(SessionDb(), parse(params))
