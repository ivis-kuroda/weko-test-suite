import pytest

import cmd_baseline as bl
import cmd_register_sword_client as sw
import cmd_workflow as wf
import contract
import registry
from tests.fakes import FakeDb


def responder(sql, params):
    if "FROM accounts_role" in sql:
        return [{"name": "System Administrator"}, {"name": "Contributor"}]
    if "FROM accounts_userrole" in sql:
        assert params == {"u": 7}
        return [{"name": "Contributor"}]
    if "FROM accounts_user " in sql:
        if params["e"] == "a@example.org":
            return [{"id": 7, "active": True, "confirmed_at": None}]
        return []
    if "FROM item_type it" in sql:
        return [{"id": 30001, "name": "simple"}]
    if "FROM jsonld_mappings" in sql:
        return [{"id": 30001, "name": "m", "item_type_id": 30001}]
    if "FROM workflow_flow_define" in sql:
        return [{"id": 1, "flow_name": "Registration Flow", "flow_type": 1}]
    if "FROM workflow_workflow" in sql:
        return [
            {"id": 2, "flows_name": "w", "itemtype_id": 30001, "flow_id": 1, "delete_flow_id": None}
        ]
    if 'FROM "index"' in sql:
        return [{"id": 1623632832836}, {"id": 5}]
    if "FROM files_location" in sql:
        return [{"name": "local", "uri": "/var/tmp", "default": True}]
    if "FROM admin_settings" in sql:
        return [{"id": 1, "name": "x"}]
    if "count(*)" in sql:
        return [{"n": 0}]
    if "FROM pidstore_pid" in sql:
        return [{"status": "R"}] if params["v"] == "900001" else []
    raise AssertionError(sql)


def test_baseline_collects_facts_without_secret_columns():
    db = FakeDb(responder)
    args = bl.parse({"emails": ["a@example.org", "b@example.org"], "recids": [900001, "900009"]})
    facts = bl.collect(db, args, {"WEKO_SWORDSERVER_SERVICEDOCUMENT_ON_BEHALF_OF": True, "X": 1})
    assert facts["users"]["a@example.org"] == {
        "active": True,
        "confirmed": False,
        "roles": ["Contributor"],
    }
    assert facts["users"]["b@example.org"] is None
    assert facts["recids"] == {"900001": "R", "900009": None}
    assert facts["config"]["WEKO_SWORDSERVER_SERVICEDOCUMENT_ON_BEHALF_OF"] is True
    assert "X" not in facts["config"]
    assert facts["locations"][0]["default"] is True
    joined = " ".join(db.sqls()).lower()
    for secret in ("password", "access_token", "client_secret"):
        assert secret not in joined
    assert all(kind == "query" for kind, _, _ in db.statements)


def test_baseline_parse_rejects_bad_input():
    with pytest.raises(contract.HelperError):
        bl.parse({"recids": ["x1"]})
    with pytest.raises(contract.HelperError):
        bl.parse({"recids": "900001"})
    with pytest.raises(contract.HelperError):
        bl.parse({"index_ids": ["a"]})


def test_delete_flow_actions_and_flow_parse():
    assert wf.flow_action_endpoints(False) == ["begin_action", "end_action"]
    assert wf.flow_action_endpoints(True) == ["begin_action", "approval", "end_action"]
    args = wf.parse_flow({"flow_name": "f"})
    assert args["for_delete"] is True and args["repository_id"] == "Root Index"
    with pytest.raises(contract.HelperError):
        wf.parse_flow({})


def test_workflow_defaults_come_from_the_template():
    template = {
        "itemtype_id": 30001,
        "flow_id": 1,
        "index_tree_id": None,
        "location_id": None,
        "open_restricted": False,
        "repository_id": "Root Index",
    }
    args = wf.parse_workflow({"flows_name": "w", "copy_from": 2, "itemtype_id": 30002})
    values = wf.merge_workflow_spec(args, template)
    assert values["itemtype_id"] == 30002 and values["flow_id"] == 1
    assert values["open_restricted"] is False
    with pytest.raises(contract.HelperError):
        wf.merge_workflow_spec(wf.parse_workflow({"flows_name": "w"}), None)
    with pytest.raises(contract.HelperError):
        wf.merge_workflow_spec(
            dict(args, open_restricted="yes"),
            template,
        )


def test_delete_record_parse():
    assert wf.parse_delete_record({"recid": 900003}) == {
        "recid": "900003",
        "method": "soft_delete",
        "restore": False,
    }
    with pytest.raises(contract.HelperError):
        wf.parse_delete_record({"recid": "x"})
    with pytest.raises(contract.HelperError):
        wf.parse_delete_record({"recid": "1", "method": "rm"})


def test_register_by_workflow_name_or_id_but_not_both():
    args = sw.parse(
        {
            "client_id": "c",
            "registration_type": "Workflow",
            "workflow_name": "w",
            "mapping_id": 30001,
        }
    )
    assert args["workflow_name"] == "w" and args["mapping_id"] == 30001
    with pytest.raises(contract.HelperError):
        sw.parse({"client_id": "c", "workflow_id": 2, "workflow_name": "w"})


def test_new_commands_are_registered():
    for name in ("baseline", "create_flow", "create_workflow", "delete_record"):
        assert registry.resolve(name) is not None
