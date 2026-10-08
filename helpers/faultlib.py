"""Fault recipes: pure plan builders plus an executor-driven engine.

Every database object created here is named ``ath_fault_<n>_<suffix>`` so that
``restore_fault all`` can find it in pg_trigger / pg_constraint / pg_policy /
pg_proc by prefix. State lives in the helper-owned tables ``ath_fault_state``
and ``ath_fault_backup``, which are dropped when no fault remains, so
``list_faults == []`` proves the environment is back to normal.

The owner's rule: backend failures are simulated by rewriting the DB or the
environment; source-code modification is the last resort. Nothing here edits
WEKO code.

All recipes are UNVERIFIED until run against a real WEKO PostgreSQL.
"""

import json
import re

import contract

PREFIX = "ath_fault_"
STATE = "ath_fault_state"
BACKUP = "ath_fault_backup"
FID_RE = re.compile(r"^(ath_fault_\d+)(?:_(?:fn|trg|chk|pol))?$")

# logical name -> physical table (allow-list for every recipe)
TABLES = {
    "users": "accounts_user",
    "roles": "accounts_role",
    "tokens": "oauth2server_token",
    "clients": "oauth2server_client",
    "sword_clients": "sword_clients",
    "records": "records_metadata",
    "items": "item_metadata",
    "pids": "pidstore_pid",
    "activities": "workflow_activity",
    "workflows": "workflow_workflow",
    "flows": "workflow_flow_define",
    "flow_actions": "workflow_flow_action",
    "jsonld_mappings": "jsonld_mappings",
    "item_type_mapping": "item_type_mapping",
}
EVENTS = ("INSERT", "UPDATE", "DELETE")
OPS = ("=", "<>", "IS NULL", "IS NOT NULL")
POLICY_COMMANDS = ("ALL", "SELECT", "UPDATE", "DELETE")
CORRUPT_MODES = ("empty_object", "json_string", "json_array", "null_json", "drop_key")
CORRUPT_TABLES = {
    "records_metadata": ("id", "uuid"),
    "item_metadata": ("id", "uuid"),
}


# ---------------------------------------------------------------- validation


def table_name(params, key="table"):
    """Resolve a logical or physical table name through the allow-list."""
    value = contract.require_str(params, key)
    if value in TABLES:
        return TABLES[value]
    if value in TABLES.values():
        return value
    raise contract.HelperError(
        "InvalidArgument", "%s must be one of: %s" % (key, ", ".join(sorted(TABLES)))
    )


def ident(params, key):
    """A lower-case SQL identifier parameter."""
    return contract.require_str(params, key, contract.IDENT_RE)


def sqlstate(params, key="sqlstate"):
    """A five character SQLSTATE parameter."""
    return contract.require_str(params, key, contract.SQLSTATE_RE)


def scalar(params, key):
    """A str/int/bool scalar parameter (``null`` and floats are rejected)."""
    if key not in params:
        raise contract.HelperError("InvalidArgument", "%s is required" % key)
    value = params[key]
    if isinstance(value, bool) or isinstance(value, (str, int)):
        return value
    raise contract.HelperError("InvalidArgument", "%s must be a string, integer or boolean" % key)


def message(params):
    """Error message text for RAISE (printable, no dollar quoting tricks)."""
    text = contract.optional_str(params, "message", "ath fault injected")
    if len(text) > 200 or "$" in text or "\x00" in text:
        raise contract.HelperError("InvalidArgument", "message must be <= 200 chars without '$'")
    return text


def row_condition(params, event=None):
    """Parse the structured ``row_condition`` or return ``None``."""
    cond = params.get("row_condition")
    if cond is None:
        return None
    if not isinstance(cond, dict):
        raise contract.HelperError("InvalidArgument", "row_condition must be an object")
    out = {"column": ident(cond, "column"), "op": cond.get("op", "=")}
    if out["op"] not in OPS:
        raise contract.HelperError("InvalidArgument", "op must be one of: %s" % ", ".join(OPS))
    if out["op"] in ("=", "<>"):
        out["value"] = scalar(cond, "value")
    default_ref = "OLD" if event == "DELETE" else "NEW"
    out["ref"] = cond.get("ref", default_ref)
    if out["ref"] not in ("NEW", "OLD"):
        raise contract.HelperError("InvalidArgument", "ref must be NEW or OLD")
    if event == "INSERT" and out["ref"] == "OLD":
        raise contract.HelperError("InvalidArgument", "INSERT triggers have no OLD row")
    if event == "DELETE" and out["ref"] == "NEW":
        raise contract.HelperError("InvalidArgument", "DELETE triggers have no NEW row")
    return out


def cond_sql(cond, with_ref=True):
    """SQL boolean expression for a parsed condition."""
    col = contract.quote_ident(cond["column"])
    if with_ref:
        col = "%s.%s" % (cond["ref"], col)
    if cond["op"] in ("IS NULL", "IS NOT NULL"):
        return "%s %s" % (col, cond["op"])
    return "%s %s %s" % (col, cond["op"], contract.quote_literal(cond["value"]))


def raise_body(state, text):
    """plpgsql body raising the given SQLSTATE."""
    return "BEGIN RAISE EXCEPTION '%%', %s USING ERRCODE = %s; END;" % (
        contract.quote_literal(text),
        contract.quote_literal(state),
    )


# ------------------------------------------------------------------- recipes


def plan_trigger_raise(params, fid, q):
    """BEFORE ROW trigger raising a chosen SQLSTATE."""
    table = table_name(params)
    event = contract.require_str(params, "event").upper()
    if event not in EVENTS:
        raise contract.HelperError("InvalidArgument", "event must be insert|update|delete")
    state = sqlstate(params)
    text = message(params)
    cond = row_condition(params, event)
    fn, trg = fid + "_fn", fid + "_trg"
    when = " WHEN (%s)" % cond_sql(cond) if cond else ""
    return {
        "create": [
            "CREATE FUNCTION %s() RETURNS trigger LANGUAGE plpgsql AS $ath$ %s $ath$"
            % (fn, raise_body(state, text)),
            "CREATE TRIGGER %s BEFORE %s ON %s FOR EACH ROW%s EXECUTE PROCEDURE %s()"
            % (trg, event, contract.quote_ident(table), when, fn),
        ],
        "restore": [
            "DROP TRIGGER IF EXISTS %s ON %s" % (trg, contract.quote_ident(table)),
            "DROP FUNCTION IF EXISTS %s()" % fn,
        ],
        "info": {"table": table, "event": event, "sqlstate": state},
    }


def plan_check_violation_new_rows(params, fid, q):
    """NOT VALID CHECK constraint: every new/updated row (or matching rows) fails."""
    table = table_name(params)
    cond = row_condition(params)
    expr = "false"
    if cond:
        expr = "NOT (%s)" % cond_sql(cond, with_ref=False)
    chk = fid + "_chk"
    quoted = contract.quote_ident(table)
    return {
        "create": ["ALTER TABLE %s ADD CONSTRAINT %s CHECK (%s) NOT VALID" % (quoted, chk, expr)],
        "restore": ["ALTER TABLE %s DROP CONSTRAINT IF EXISTS %s" % (quoted, chk)],
        "info": {"table": table, "sqlstate": "23514"},
    }


def plan_rls_raise_on_row(params, fid, q):
    """RLS policy whose USING clause raises for one row (FORCE so the owner is bound)."""
    table = table_name(params)
    column = ident(params, "column")
    value = scalar(params, "value")
    state = sqlstate(params)
    text = message(params)
    command = contract.optional_str(params, "command", "SELECT").upper()
    if command not in POLICY_COMMANDS:
        raise contract.HelperError(
            "InvalidArgument", "command must be one of: %s" % ", ".join(POLICY_COMMANDS)
        )
    quoted = contract.quote_ident(table)
    bypass = q(
        "SELECT (rolsuper OR rolbypassrls) AS bypass FROM pg_roles WHERE rolname = current_user"
    )
    if bypass and bypass[0]["bypass"] and not params.get("allow_bypass"):
        raise contract.HelperError(
            "RlsBypassed",
            "the DB role is superuser/BYPASSRLS, so RLS would never fire; "
            "use trigger_raise, or pass allow_bypass=true to inject anyway",
        )
    prior = q(
        "SELECT relrowsecurity AS en, relforcerowsecurity AS fo FROM pg_class "
        "WHERE oid = CAST(:t AS regclass)",
        {"t": table},
    )
    if not prior:
        raise contract.HelperError("TableNotFound", "table %s not found" % table)
    was_enabled, was_forced = bool(prior[0]["en"]), bool(prior[0]["fo"])
    fn, pol = fid + "_fn", fid + "_pol"
    restore = ["DROP POLICY IF EXISTS %s ON %s" % (pol, quoted)]
    if not was_forced:
        restore.append("ALTER TABLE %s NO FORCE ROW LEVEL SECURITY" % quoted)
    if not was_enabled:
        restore.append("ALTER TABLE %s DISABLE ROW LEVEL SECURITY" % quoted)
    restore.append("DROP FUNCTION IF EXISTS %s()" % fn)
    using = "CASE WHEN %s = %s THEN %s() ELSE true END" % (
        contract.quote_ident(column),
        contract.quote_literal(value),
        fn,
    )
    return {
        "create": [
            "CREATE FUNCTION %s() RETURNS boolean LANGUAGE plpgsql AS $ath$ "
            "BEGIN RAISE EXCEPTION '%%', %s USING ERRCODE = %s; RETURN true; END; $ath$"
            % (fn, contract.quote_literal(text), contract.quote_literal(state)),
            "ALTER TABLE %s ENABLE ROW LEVEL SECURITY" % quoted,
            "ALTER TABLE %s FORCE ROW LEVEL SECURITY" % quoted,
            "CREATE POLICY %s ON %s FOR %s USING (%s)" % (pol, quoted, command, using),
        ],
        "restore": restore,
        "info": {
            "table": table,
            "prior_rls_enabled": was_enabled,
            "prior_rls_forced": was_forced,
            "sqlstate": state,
        },
    }


def json_update_expr(mode, key=None, column="json"):
    """SQL expression for the corrupted jsonb value."""
    if mode == "empty_object":
        return "CAST('{}' AS jsonb)"
    if mode == "json_string":
        return "CAST('\"ath_corrupt\"' AS jsonb)"
    if mode == "json_array":
        return "CAST('[]' AS jsonb)"
    if mode == "null_json":
        return "NULL"
    if mode == "drop_key":
        return "%s - %s" % (contract.quote_ident(column), contract.quote_literal(key))
    raise contract.HelperError(
        "InvalidArgument", "mode must be one of: %s" % ", ".join(CORRUPT_MODES)
    )


def corrupt_plan(table, key_col, key_sql, column, mode, key, fid, info):
    """Shared backup/update/restore plan for a jsonb column."""
    quoted = contract.quote_ident(table)
    col = contract.quote_ident(column)
    kc = contract.quote_ident(key_col)
    fid_lit = contract.quote_literal(fid)
    tbl_lit = contract.quote_literal(table)
    key_cast = "CAST(b.row_key AS %s)" % key_sql[1]
    return {
        "create": [
            "INSERT INTO %s (fault_id, table_name, row_key, original) "
            "SELECT %s, %s, t.%s::text, row_to_json(t)::text FROM %s t WHERE t.%s = %s"
            % (BACKUP, fid_lit, tbl_lit, kc, quoted, kc, key_sql[0]),
            "UPDATE %s SET %s = %s WHERE %s = %s"
            % (quoted, col, json_update_expr(mode, key, column), kc, key_sql[0]),
        ],
        "restore": [
            "UPDATE %s r SET %s = CAST(CAST(b.original AS json) ->> %s AS jsonb) "
            "FROM %s b WHERE b.fault_id = %s AND b.table_name = %s AND r.%s = %s"
            % (quoted, col, contract.quote_literal(column), BACKUP, fid_lit, tbl_lit, kc, key_cast)
        ],
        "info": info,
    }


def _mode(params):
    mode = contract.require_str(params, "mode")
    if mode not in CORRUPT_MODES:
        raise contract.HelperError(
            "InvalidArgument", "mode must be one of: %s" % ", ".join(CORRUPT_MODES)
        )
    key = contract.require_str(params, "key") if mode == "drop_key" else None
    return mode, key


def plan_corrupt_record_json(params, fid, q):
    """Overwrite a record's JSON (M9); original row JSON saved in ath_fault_backup."""
    recid = params.get("recid")
    if isinstance(recid, bool) or not isinstance(recid, (str, int)) or not str(recid).isdigit():
        raise contract.HelperError("InvalidArgument", "recid must be a decimal string or integer")
    recid = str(recid)
    table = contract.optional_str(params, "table", "records_metadata")
    if table not in CORRUPT_TABLES:
        raise contract.HelperError(
            "InvalidArgument", "table must be one of: %s" % ", ".join(sorted(CORRUPT_TABLES))
        )
    mode, key = _mode(params)
    found = q(
        "SELECT object_uuid::text AS u FROM pidstore_pid "
        "WHERE pid_type = 'recid' AND pid_value = :v LIMIT 1",
        {"v": recid},
    )
    if not found:
        raise contract.HelperError("RecordNotFound", "no recid pid for %s" % recid)
    uuid_ = found[0]["u"]
    if not re.match(r"^[0-9a-f-]{36}$", uuid_):
        raise contract.HelperError("InvalidArgument", "unexpected uuid from pidstore: %r" % uuid_)
    exists = q(
        "SELECT 1 AS x FROM %s WHERE id = CAST(:u AS uuid)" % contract.quote_ident(table),
        {"u": uuid_},
    )
    if not exists:
        raise contract.HelperError("RecordRowMissing", "no %s row for recid %s" % (table, recid))
    key_sql = ("CAST(%s AS uuid)" % contract.quote_literal(uuid_), "uuid")
    return corrupt_plan(
        table, "id", key_sql, "json", mode, key, fid,
        {"table": table, "recid": recid, "uuid": uuid_, "mode": mode},
    )  # fmt: skip


def plan_corrupt_mapping_json(params, fid, q):
    """Overwrite a JSON-LD mapping (M7); original saved in ath_fault_backup."""
    mapping_id = contract.optional_int(params, "mapping_id")
    if mapping_id is None:
        raise contract.HelperError("InvalidArgument", "mapping_id is required")
    mode, key = _mode(params)
    found = q("SELECT 1 AS x FROM jsonld_mappings WHERE id = :i", {"i": mapping_id})
    if not found:
        raise contract.HelperError("MappingNotFound", "no jsonld_mappings row %d" % mapping_id)
    key_sql = (str(mapping_id), "integer")
    return corrupt_plan(
        "jsonld_mappings", "id", key_sql, "mapping", mode, key, fid,
        {"table": "jsonld_mappings", "mapping_id": mapping_id, "mode": mode},
    )  # fmt: skip


def plan_break_workflow_flow(params, fid, q):
    """Break the flow behind a workflow (M11/M6); rows backed up for restore."""
    workflow_id = contract.optional_int(params, "workflow_id")
    if workflow_id is None:
        raise contract.HelperError("InvalidArgument", "workflow_id is required")
    mode = contract.optional_str(params, "mode", "delete_flow_actions")
    found = q(
        "SELECT f.id AS pk, f.flow_id::text AS flow_uuid FROM workflow_workflow w "
        "JOIN workflow_flow_define f ON f.id = w.flow_id WHERE w.id = :w",
        {"w": workflow_id},
    )
    if not found:
        raise contract.HelperError("WorkflowNotFound", "no workflow %d with a flow" % workflow_id)
    pk, flow_uuid = int(found[0]["pk"]), found[0]["flow_uuid"]
    if not re.match(r"^[0-9a-f-]{36}$", flow_uuid):
        raise contract.HelperError("InvalidArgument", "unexpected flow uuid: %r" % flow_uuid)
    fid_lit = contract.quote_literal(fid)
    info = {"workflow_id": workflow_id, "flow_pk": pk, "mode": mode}
    if mode == "delete_flow_actions":
        where = "flow_id = CAST(%s AS uuid)" % contract.quote_literal(flow_uuid)
        return {
            "create": [
                "INSERT INTO %s (fault_id, table_name, row_key, original) "
                "SELECT %s, 'workflow_flow_action', t.id::text, row_to_json(t)::text "
                "FROM workflow_flow_action t WHERE t.%s" % (BACKUP, fid_lit, where),
                "DELETE FROM workflow_flow_action WHERE %s" % where,
            ],
            "restore": [
                "INSERT INTO workflow_flow_action SELECT "
                "(json_populate_record(CAST(NULL AS workflow_flow_action), "
                "CAST(b.original AS json))).* "
                "FROM %s b WHERE b.fault_id = %s AND b.table_name = 'workflow_flow_action'"
                % (BACKUP, fid_lit)
            ],
            "info": info,
        }
    if mode in ("flow_status", "mark_deleted"):
        column = "flow_status" if mode == "flow_status" else "is_deleted"
        if mode == "flow_status":
            value = contract.require_str(params, "value")
            if len(value) != 1:
                raise contract.HelperError("InvalidArgument", "flow_status value must be 1 char")
            new, cast = contract.quote_literal(value), "text"
        else:
            new, cast = "true", "boolean"
        return {
            "create": [
                "INSERT INTO %s (fault_id, table_name, row_key, original) "
                "SELECT %s, 'workflow_flow_define', t.id::text, row_to_json(t)::text "
                "FROM workflow_flow_define t WHERE t.id = %d" % (BACKUP, fid_lit, pk),
                "UPDATE workflow_flow_define SET %s = %s WHERE id = %d" % (column, new, pk),
            ],
            "restore": [
                "UPDATE workflow_flow_define r SET %s = "
                "CAST(CAST(b.original AS json) ->> '%s' AS %s) "
                "FROM %s b WHERE b.fault_id = %s AND b.table_name = 'workflow_flow_define' "
                "AND r.id = %d" % (column, column, cast, BACKUP, fid_lit, pk)
            ],
            "info": info,
        }
    raise contract.HelperError(
        "InvalidArgument", "mode must be delete_flow_actions|flow_status|mark_deleted"
    )


# kind -> (planner, hypothesis, mock ids)
RECIPES = {
    "trigger_raise": (
        plan_trigger_raise,
        "A BEFORE ROW trigger makes one write path raise a chosen SQLSTATE",
        ["M3", "M4", "M5", "M13-DB"],
    ),
    "check_violation_new_rows": (
        plan_check_violation_new_rows,
        "A NOT VALID CHECK (false) rejects new/updated rows with SQLSTATE 23514",
        ["M3", "M4", "M5"],
    ),
    "rls_raise_on_row": (
        plan_rls_raise_on_row,
        "A forced RLS policy raises when a specific row is read (user lookup, read paths)",
        ["M1", "M8", "M10"],
    ),
    "corrupt_record_json": (
        plan_corrupt_record_json,
        "The record's stored JSON is structurally corrupted but the row exists",
        ["M9"],
    ),
    "corrupt_mapping_json": (
        plan_corrupt_mapping_json,
        "The JSON-LD mapping row used by the import holds a broken document",
        ["M7"],
    ),
    "break_workflow_flow": (
        plan_break_workflow_flow,
        "The workflow's flow loses its actions (or status) so the workflow cannot run",
        ["M11", "M6"],
    ),
}


def catalog():
    """Machine-readable recipe catalog (pure)."""
    return [
        {"kind": k, "hypothesis": h, "mocks": list(m)} for k, (_f, h, m) in sorted(RECIPES.items())
    ]


# -------------------------------------------------------------------- engine

ENSURE_SQL = [
    "CREATE TABLE IF NOT EXISTS %s (id serial PRIMARY KEY, kind text NOT NULL, "
    "params text NOT NULL, restore_sql text NOT NULL, info text, "
    "created_at timestamptz NOT NULL DEFAULT now())" % STATE,
    "CREATE TABLE IF NOT EXISTS %s (fault_id text NOT NULL, table_name text NOT NULL, "
    "row_key text NOT NULL, original text)" % BACKUP,
]

LIKE = "'ath\\_fault\\_%'"
SWEEP = [
    (
        "trigger",
        "SELECT t.tgname AS name, t.tgrelid::regclass::text AS rel FROM pg_trigger t "
        "WHERE NOT t.tgisinternal AND t.tgname LIKE " + LIKE,
    ),
    (
        "constraint",
        "SELECT conname AS name, conrelid::regclass::text AS rel FROM pg_constraint "
        "WHERE conrelid <> 0 AND conname LIKE " + LIKE,
    ),
    (
        "policy",
        "SELECT polname AS name, polrelid::regclass::text AS rel FROM pg_policy "
        "WHERE polname LIKE " + LIKE,
    ),
    (
        "function",
        "SELECT proname AS name, oid::regprocedure::text AS rel FROM pg_proc "
        "WHERE proname LIKE " + LIKE,
    ),
]
DROP_ORPHAN = {
    "trigger": "DROP TRIGGER IF EXISTS %(name)s ON %(rel)s",
    "constraint": "ALTER TABLE %(rel)s DROP CONSTRAINT IF EXISTS %(name)s",
    "policy": "DROP POLICY IF EXISTS %(name)s ON %(rel)s",
    "function": "DROP FUNCTION IF EXISTS %(rel)s",
}


def state_exists(db):
    """Whether the helper-owned state table exists."""
    rows = db.query("SELECT to_regclass('ath_fault_state') IS NOT NULL AS ex")
    return bool(rows and rows[0]["ex"])


def inject(db, kind, params):
    """Create a fault from a named recipe; returns what the host needs to know."""
    if kind not in RECIPES:
        raise contract.HelperError("UnknownFault", "unknown fault kind %r" % kind)
    planner = RECIPES[kind][0]
    try:
        for sql in ENSURE_SQL:
            db.execute(sql)
        row = db.query(
            "INSERT INTO %s (kind, params, restore_sql) VALUES (:k, :p, '[]') RETURNING id" % STATE,
            {"k": kind, "p": json.dumps(params, sort_keys=True)},
        )
        fid = PREFIX + str(row[0]["id"])
        plan = planner(params, fid, db.query)
        for sql in plan["create"]:
            db.execute(sql)
        db.execute(
            "UPDATE %s SET restore_sql = :r, info = :i WHERE id = :n" % STATE,
            {
                "r": json.dumps(plan["restore"]),
                "i": json.dumps(plan["info"], sort_keys=True),
                "n": row[0]["id"],
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"fault_id": fid, "kind": kind, "info": plan["info"], "statements": len(plan["create"])}


def find_orphans(db, known_ids):
    """Prefixed catalog objects that no state row owns."""
    orphans = []
    for obj_type, sql in SWEEP:
        for row in db.query(sql):
            match = FID_RE.match(row["name"])
            if match is None or match.group(1) not in known_ids:
                orphans.append({"object_type": obj_type, "name": row["name"], "rel": row["rel"]})
    return orphans


def _state_rows(db):
    if not state_exists(db):
        return []
    return db.query(
        "SELECT id, kind, params, restore_sql, info, created_at FROM %s ORDER BY id" % STATE
    )


def list_faults(db):
    """Active faults plus unowned ``ath_fault_`` objects; ``[]`` means clean."""
    rows = _state_rows(db)
    out = [
        {
            "fault_id": PREFIX + str(r["id"]),
            "kind": r["kind"],
            "params": json.loads(r["params"]),
            "info": json.loads(r["info"]) if r["info"] else {},
            "created_at": str(r["created_at"]),
        }
        for r in rows
    ]
    known = set(PREFIX + str(r["id"]) for r in rows)
    for orphan in find_orphans(db, known):
        entry = {"fault_id": None, "kind": "orphan"}
        entry.update(orphan)
        out.append(entry)
    return out


def restore(db, kind="all", fault_id=None):
    """Undo faults (newest first). ``all`` also sweeps unowned prefixed objects."""
    if kind != "all" and kind not in RECIPES:
        raise contract.HelperError("UnknownFault", "unknown fault kind %r" % kind)
    restored, swept, warnings = [], [], []
    try:
        rows = list(reversed(_state_rows(db)))
        for r in rows:
            fid = PREFIX + str(r["id"])
            if fault_id is not None and fid != fault_id:
                continue
            if kind != "all" and r["kind"] != kind:
                continue
            for sql in json.loads(r["restore_sql"]):
                db.execute(sql)
            db.execute("DELETE FROM %s WHERE fault_id = :f" % BACKUP, {"f": fid})
            db.execute("DELETE FROM %s WHERE id = :n" % STATE, {"n": r["id"]})
            restored.append(fid)
        remaining = _state_rows(db) if state_exists(db) else []
        if kind == "all" and fault_id is None:
            known = set(PREFIX + str(r["id"]) for r in remaining)
            for orphan in find_orphans(db, known):
                db.execute(DROP_ORPHAN[orphan["object_type"]] % {
                    "name": contract.quote_ident(orphan["name"]),
                    "rel": orphan["rel"],
                })  # fmt: skip
                swept.append(orphan)
                if orphan["object_type"] == "policy":
                    warnings.append(
                        "policy %s dropped without state; RLS on %s may still be enabled"
                        % (orphan["name"], orphan["rel"])
                    )
        dropped = False
        if state_exists(db) and not db.query("SELECT 1 AS x FROM %s LIMIT 1" % STATE):
            db.execute("DROP TABLE IF EXISTS %s" % BACKUP)
            db.execute("DROP TABLE IF EXISTS %s" % STATE)
            dropped = True
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {
        "restored": restored,
        "swept": swept,
        "helper_tables_dropped": dropped,
        "warnings": warnings,
    }
