import json

import pytest

import cmd_create_record as rec
import cmd_snapshot as snap
import contract
import rowlib
from tests.fakes import FakeDb


def test_record_builders_are_consistent():
    data = rec.build_record_data("900001", "T", 7, "a@b.c", 3, "bucket", "ath-test/900001")
    item = rec.build_item_data("900001", "T", 7, "a@b.c", 3)
    assert data["_deposit"]["owners"] == [7] and data["owner"] == "7"
    assert data["item_type_id"] == "3" and item["$schema"] == "/items/jsonschema/3"
    assert data["item_1617186819068"]["attribute_value_mlt"][0]["subitem_identifier_reg_text"] == (
        "ath-test/900001"
    )
    assert "item_1617186819068" not in rec.build_record_data("1", "T", 1, "a@b.c", 1, "b")
    json.dumps(data)


def test_record_parse():
    assert rec.parse({"recid": 12, "title": "t", "owner_email": "a@b.c"})["recid"] == "12"
    for bad in ({"recid": "x1"}, {"recid": True}, {}):
        with pytest.raises(contract.HelperError):
            rec.parse(dict({"title": "t", "owner_email": "a@b.c"}, **bad) if bad else {})


def test_doi_default():
    assert rec.doi_value_for(5) == "https://doi.org/ath-test/5"


def test_delete_and_restore_rows():
    def responder(sql, params):
        if "pidstore_pid" in sql:
            return [{"u": "11111111-1111-1111-1111-111111111111"}]
        if "row_to_json" in sql:
            return [{"row": json.dumps({"id": "11111111-1111-1111-1111-111111111111"})}]
        return []

    db = FakeDb(responder)
    out = rowlib.delete_rows(db, 5, ["records_metadata"])
    assert out["backup"][0]["table"] == "records_metadata"
    assert any(s.startswith('DELETE FROM "records_metadata"') for s in db.sqls())
    assert db.commits == 1
    db2 = FakeDb()
    assert rowlib.restore_rows(db2, out["backup"]) == {"restored_tables": ["records_metadata"]}
    assert any("json_populate_record" in s for s in db2.sqls())


def test_delete_rows_rejects_unknown_table_and_missing_record():
    with pytest.raises(contract.HelperError):
        rowlib.delete_rows(FakeDb(), 1, ["accounts_user"])
    with pytest.raises(contract.HelperError) as ei:
        rowlib.delete_rows(FakeDb(), 1, ["records_metadata"])
    assert ei.value.type == "RecordNotFound"


def test_snapshot_never_selects_secrets():
    for name, (_t, _k, cols, _l) in snap.SPECS.items():
        for secret in ("access_token", "refresh_token", "password", "client_secret"):
            assert secret not in cols, (name, secret)


def test_snapshot_parse():
    with pytest.raises(contract.HelperError):
        snap.parse({"tables": ["accounts_user"]})
    assert snap.parse({"tables": ["items"], "recid": 3})["recid"] == "3"


def test_row_hash_is_canonical():
    a = snap.row_hash({"b": 1, "a": {"y": 1, "x": 2}})
    b = snap.row_hash({"a": {"x": 2, "y": 1}, "b": 1})
    assert a == b and len(a) == 64
    assert snap.row_hash({"a": 1}) != snap.row_hash({"a": 2})


def test_collect_and_diff():
    rows = [{"id": 1, "email": "a@b.c", "active": True, "confirmed_at": None}]
    db = FakeDb(lambda sql, params: rows)
    out = snap.collect(db, snap.parse({"tables": ["users", "items"]}))
    assert out["tables"]["users"]["count"] == 1
    assert list(out["tables"]["users"]["rows"]) == ["a@b.c"]
    assert out["recid_resolved"] is None
    after = {"users": {"rows": {"a@b.c": "x", "n": "y"}}}
    d = snap.diff({"users": out["tables"]["users"]}, after)
    assert d["users"]["added"] == ["n"] and d["users"]["changed"] == ["a@b.c"]


def test_collect_with_recid_filter():
    def responder(sql, params):
        if "pidstore_pid" in sql and "object_uuid::text" in sql:
            return [{"u": "u-1"}]
        return []

    db = FakeDb(responder)
    out = snap.collect(db, snap.parse({"tables": ["records", "users"], "recid": "5"}))
    assert out["recid_resolved"] is True
    assert out["tables"]["records"]["recid_filter"] is True
    assert out["tables"]["users"]["recid_filter"] is False
    assert any("WHERE" in s and "records_metadata" in s for s in db.sqls())


def test_collect_with_unknown_recid():
    db = FakeDb()
    out = snap.collect(db, snap.parse({"tables": ["records"], "recid": "5"}))
    assert out["recid_resolved"] is False and out["tables"]["records"]["count"] == 0
