import json
import re

import pytest

import cmd_inject_fault as cmd
import contract
import faultlib
from tests.fakes import FakeDb

UUID = "11111111-2222-3333-4444-555555555555"
FLOW = "99999999-2222-3333-4444-555555555555"


class PgSim(FakeDb):
    """Minimal PostgreSQL stand-in: state table, catalog sweeps, canned lookups."""

    def __init__(self, bypass=False, rls=(False, False), orphans=None):
        FakeDb.__init__(self, self.respond)
        self.rows = {}
        self.next_id = 1
        self.table_exists = False
        self.bypass = bypass
        self.rls = rls
        self.orphans = orphans or {}

    def respond(self, sql, params):
        if "to_regclass" in sql:
            return [{"ex": self.table_exists}]
        if sql.startswith("INSERT INTO ath_fault_state"):
            rid = self.next_id
            self.next_id += 1
            self.rows[rid] = {"id": rid, "kind": params["k"], "params": params["p"],
                              "restore_sql": "[]", "info": None, "created_at": "now"}  # fmt: skip
            return [{"id": rid}]
        if sql.startswith("SELECT id, kind"):
            return [self.rows[k] for k in sorted(self.rows)]
        if sql.startswith("SELECT 1 AS x FROM ath_fault_state"):
            return [{"x": 1}] if self.rows else []
        if "rolsuper" in sql:
            return [{"bypass": self.bypass}]
        if "relrowsecurity" in sql:
            return [{"en": self.rls[0], "fo": self.rls[1]}]
        if "pidstore_pid" in sql:
            return [{"u": UUID}]
        if "FROM workflow_workflow w" in sql:
            return [{"pk": 4, "flow_uuid": FLOW}]
        if "FROM jsonld_mappings" in sql or re.search(r"FROM \"?\w+\"? WHERE id = CAST", sql):
            return [{"x": 1}]
        for obj_type, sweep_sql in faultlib.SWEEP:
            if sql == sweep_sql:
                return self.orphans.get(obj_type, [])
        return []

    def execute(self, sql, params=None):
        FakeDb.execute(self, sql, params)
        if sql.startswith("CREATE TABLE IF NOT EXISTS ath_fault_state"):
            self.table_exists = True
        if sql.startswith("UPDATE ath_fault_state SET restore_sql"):
            self.rows[params["n"]]["restore_sql"] = params["r"]
            self.rows[params["n"]]["info"] = params["i"]
        if sql.startswith("DELETE FROM ath_fault_state"):
            del self.rows[params["n"]]
        if sql.startswith("DROP TABLE IF EXISTS ath_fault_state"):
            self.table_exists = False


def names_created(sqls):
    out = []
    for s in sqls:
        m = re.search(r"CREATE (?:FUNCTION|TRIGGER|POLICY) (\S+?)(?:\(| )", s) or re.search(
            r"ADD CONSTRAINT (\S+)", s
        )
        if m:
            out.append(m.group(1))
    return out


def test_trigger_raise_plan():
    db = PgSim()
    res = faultlib.inject(
        db,
        "trigger_raise",
        {
            "table": "sword_clients",
            "event": "update",
            "sqlstate": "08006",
            "message": "it's down",
            "row_condition": {"column": "client_id", "value": "abc"},
        },
    )
    assert res["fault_id"] == "ath_fault_1"
    sqls = db.sqls()
    create_fn = [s for s in sqls if s.startswith("CREATE FUNCTION")][0]
    assert "ERRCODE = '08006'" in create_fn and "'it''s down'" in create_fn
    trg = [s for s in sqls if s.startswith("CREATE TRIGGER")][0]
    assert 'BEFORE UPDATE ON "sword_clients" FOR EACH ROW WHEN (NEW."client_id" = \'abc\')' in trg
    assert all(n.startswith("ath_fault_") for n in names_created(sqls))
    assert db.commits == 1


def test_trigger_raise_delete_uses_old_and_validates():
    db = PgSim()
    faultlib.inject(
        db,
        "trigger_raise",
        {"table": "records", "event": "delete", "sqlstate": "23503",
         "row_condition": {"column": "id", "op": "IS NOT NULL"}},
    )  # fmt: skip
    assert 'WHEN (OLD."id" IS NOT NULL)' in " ".join(db.sqls())
    bad = [
        {"table": "evil; drop", "event": "insert", "sqlstate": "23503"},
        {"table": "records", "event": "truncate", "sqlstate": "23503"},
        {"table": "records", "event": "insert", "sqlstate": "2350"},
        {"table": "records", "event": "insert", "sqlstate": "23503", "message": "$ath$"},
        {"table": "records", "event": "insert", "sqlstate": "23503",
         "row_condition": {"column": "id", "ref": "OLD", "value": 1}},
        {"table": "records", "event": "insert", "sqlstate": "23503",
         "row_condition": {"column": "id; x", "value": 1}},
    ]  # fmt: skip
    for params in bad:
        d = PgSim()
        with pytest.raises(contract.HelperError):
            faultlib.inject(d, "trigger_raise", params)
        assert d.rollbacks == 1 and d.commits == 0


def test_check_violation():
    db = PgSim()
    faultlib.inject(db, "check_violation_new_rows", {"table": "item_metadata"})
    assert any(
        s == 'ALTER TABLE "item_metadata" ADD CONSTRAINT ath_fault_1_chk CHECK (false) NOT VALID'
        for s in db.sqls()
    )


def test_rls_records_prior_state_and_restores_it():
    for prior in ((False, False), (True, False), (True, True)):
        db = PgSim(rls=prior)
        faultlib.inject(
            db,
            "rls_raise_on_row",
            {"table": "users", "column": "email", "value": "x@y.z", "sqlstate": "42501"},
        )
        sqls = db.sqls()
        assert 'ALTER TABLE "accounts_user" FORCE ROW LEVEL SECURITY' in sqls
        pol = [s for s in sqls if s.startswith("CREATE POLICY")][0]
        assert (
            "FOR SELECT USING (CASE WHEN \"email\" = 'x@y.z' THEN ath_fault_1_fn() ELSE true END)"
            in pol
        )
        restore = json.loads(db.rows[1]["restore_sql"])
        assert (restore.count('ALTER TABLE "accounts_user" NO FORCE ROW LEVEL SECURITY') == 1) == (
            not prior[1]
        )
        assert (restore.count('ALTER TABLE "accounts_user" DISABLE ROW LEVEL SECURITY') == 1) == (
            not prior[0]
        )


def test_rls_refused_for_bypass_roles():
    db = PgSim(bypass=True)
    params = {"table": "users", "column": "email", "value": "x", "sqlstate": "42501"}
    with pytest.raises(contract.HelperError) as ei:
        faultlib.inject(db, "rls_raise_on_row", params)
    assert ei.value.type == "RlsBypassed"
    faultlib.inject(PgSim(bypass=True), "rls_raise_on_row", dict(params, allow_bypass=True))


def test_corrupt_record_json_and_modes():
    db = PgSim()
    faultlib.inject(db, "corrupt_record_json", {"recid": 7, "mode": "drop_key", "key": "_deposit"})
    sqls = db.sqls()
    assert any("INSERT INTO ath_fault_backup" in s and "records_metadata" in s for s in sqls)
    assert any(
        s.startswith('UPDATE "records_metadata" SET "json" = "json" - \'_deposit\'') for s in sqls
    )
    restore = json.loads(db.rows[1]["restore_sql"])
    assert "->> 'json'" in restore[0] and "ath_fault_1" in restore[0]
    for mode in ("empty_object", "json_string", "json_array", "null_json"):
        faultlib.inject(
            PgSim(), "corrupt_record_json", {"recid": "7", "mode": mode, "table": "item_metadata"}
        )
    bad_params = [
        {"recid": "x", "mode": "empty_object"},
        {"recid": 1, "mode": "nope"},
        {"recid": 1, "mode": "drop_key"},
        {"recid": 1, "mode": "empty_object", "table": "users"},
    ]
    for bad in bad_params:
        with pytest.raises(contract.HelperError):
            faultlib.inject(PgSim(), "corrupt_record_json", bad)


def test_corrupt_mapping_json():
    db = PgSim()
    faultlib.inject(db, "corrupt_mapping_json", {"mapping_id": 3, "mode": "empty_object"})
    assert any(s.startswith('UPDATE "jsonld_mappings" SET "mapping" =') for s in db.sqls())


def test_break_workflow_flow_modes():
    db = PgSim()
    faultlib.inject(db, "break_workflow_flow", {"workflow_id": 2})
    sqls = db.sqls()
    assert any(
        s.startswith("DELETE FROM workflow_flow_action WHERE flow_id = CAST('%s'" % FLOW)
        for s in sqls
    )
    assert "json_populate_record" in db.rows[1]["restore_sql"]
    d2 = PgSim()
    faultlib.inject(
        d2, "break_workflow_flow", {"workflow_id": 2, "mode": "flow_status", "value": "M"}
    )
    assert "UPDATE workflow_flow_define SET flow_status = 'M' WHERE id = 4" in d2.sqls()
    d3 = PgSim()
    faultlib.inject(d3, "break_workflow_flow", {"workflow_id": 2, "mode": "mark_deleted"})
    assert "AS boolean" in d3.rows[1]["restore_sql"]
    with pytest.raises(contract.HelperError):
        faultlib.inject(PgSim(), "break_workflow_flow", {"workflow_id": 2, "mode": "x"})


def test_unknown_kind():
    with pytest.raises(contract.HelperError) as ei:
        faultlib.inject(PgSim(), "chmod_path", {})
    assert ei.value.type == "UnknownFault"


def test_inject_list_restore_roundtrip_is_lifo_and_drops_helper_tables():
    db = PgSim()
    assert faultlib.list_faults(db) == []
    faultlib.inject(db, "check_violation_new_rows", {"table": "records"})
    faultlib.inject(
        db, "trigger_raise", {"table": "records", "event": "insert", "sqlstate": "23505"}
    )
    listed = faultlib.list_faults(db)
    assert [f["fault_id"] for f in listed] == ["ath_fault_1", "ath_fault_2"]
    assert listed[1]["params"]["event"] == "insert"
    start = len(db.statements)
    out = faultlib.restore(db, "all")
    assert out["restored"] == ["ath_fault_2", "ath_fault_1"]
    assert out["helper_tables_dropped"] is True and db.table_exists is False
    executed = [s[1] for s in db.statements[start:] if s[0] == "execute"]
    assert executed.index(
        'DROP TRIGGER IF EXISTS ath_fault_2_trg ON "records_metadata"'
    ) < executed.index('ALTER TABLE "records_metadata" DROP CONSTRAINT IF EXISTS ath_fault_1_chk')
    assert faultlib.list_faults(db) == []
    assert faultlib.restore(db, "all")["restored"] == []  # idempotent


def test_restore_one_kind_keeps_the_rest():
    db = PgSim()
    faultlib.inject(db, "check_violation_new_rows", {"table": "records"})
    faultlib.inject(
        db, "trigger_raise", {"table": "records", "event": "insert", "sqlstate": "23505"}
    )
    out = faultlib.restore(db, "trigger_raise")
    assert out["restored"] == ["ath_fault_2"] and out["helper_tables_dropped"] is False
    assert [f["fault_id"] for f in faultlib.list_faults(db)] == ["ath_fault_1"]
    assert faultlib.restore(db, fault_id="ath_fault_1")["restored"] == ["ath_fault_1"]


def test_orphans_are_listed_and_swept():
    orphans = {
        "trigger": [{"name": "ath_fault_9_trg", "rel": "records_metadata"}],
        "policy": [{"name": "ath_fault_9_pol", "rel": "accounts_user"}],
        "function": [{"name": "ath_fault_9_fn", "rel": "ath_fault_9_fn()"}],
        "constraint": [{"name": "ath_fault_chk", "rel": "item_metadata"}],
    }
    db = PgSim(orphans=orphans)
    listed = faultlib.list_faults(db)
    assert len(listed) == 4 and all(f["kind"] == "orphan" for f in listed)
    out = faultlib.restore(db, "all")
    assert len(out["swept"]) == 4 and out["warnings"]
    executed = db.sqls()
    assert 'DROP TRIGGER IF EXISTS "ath_fault_9_trg" ON records_metadata' in executed
    assert "DROP FUNCTION IF EXISTS ath_fault_9_fn()" in executed
    assert 'ALTER TABLE item_metadata DROP CONSTRAINT IF EXISTS "ath_fault_chk"' in executed


def test_catalog_and_commands():
    kinds = [c["kind"] for c in faultlib.catalog()]
    assert set(kinds) == set(faultlib.RECIPES)
    assert cmd.run_list({"catalog": True}) == faultlib.catalog()
    with pytest.raises(contract.HelperError):
        cmd.run_inject({"kind": "trigger_raise", "params": []})


def test_failed_inject_rolls_back_everything():
    db = PgSim()
    with pytest.raises(contract.HelperError):
        faultlib.inject(db, "trigger_raise", {"table": "records"})
    assert db.rollbacks == 1 and db.commits == 0
