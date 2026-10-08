"""create_flow / create_workflow / delete_record.

The demo data of install.sh has one registration flow and no deletion flow.
SWORD EP5 takes the Workflow path only when the SwordClient's workflow has a
``delete_flow_id`` (``weko_swordserver.utils.check_deletion_type``), so a test
environment needs a deletion flow (``workflow_flow_define.flow_type = 2``) and
a workflow that points at it. These commands create both without touching the
demo workflows, and are idempotent by name.
"""

import contract

DELETE_FLOW_TYPE = 2
REGISTER_FLOW_TYPE = 1
ROOT_REPOSITORY = "Root Index"

# Endpoints of the actions a deletion flow may hold (config
# WEKO_WORKFLOW_DELETION_ACTIONS: Start, End, Approval).
ACTION_START = "begin_action"
ACTION_END = "end_action"
ACTION_APPROVAL = "approval"


def flow_action_endpoints(with_approval):
    """Ordered action endpoints of a deletion flow (pure)."""
    endpoints = [ACTION_START]
    if with_approval:
        endpoints.append(ACTION_APPROVAL)
    endpoints.append(ACTION_END)
    return endpoints


def parse_flow(params):
    """Validate create_flow arguments (pure)."""
    return {
        "flow_name": contract.require_str(params, "flow_name"),
        "for_delete": contract.optional_bool(params, "for_delete", True),
        "with_approval": contract.optional_bool(params, "with_approval", False),
        "repository_id": contract.optional_str(params, "repository_id", ROOT_REPOSITORY),
    }


def parse_workflow(params):
    """Validate create_workflow arguments (pure)."""
    return {
        "flows_name": contract.require_str(params, "flows_name"),
        "copy_from": contract.optional_int(params, "copy_from"),
        "itemtype_id": contract.optional_int(params, "itemtype_id"),
        "flow_id": contract.optional_int(params, "flow_id"),
        "delete_flow_id": contract.optional_int(params, "delete_flow_id"),
        "delete_flow_name": contract.optional_str(params, "delete_flow_name"),
        "repository_id": contract.optional_str(params, "repository_id"),
        "index_tree_id": contract.optional_int(params, "index_tree_id"),
        "location_id": contract.optional_int(params, "location_id"),
        "open_restricted": params.get("open_restricted"),
    }


def merge_workflow_spec(args, template):
    """Fill unset workflow columns from a template row (pure).

    ``template`` is a dict of an existing workflow (or ``None``); explicit
    arguments win. Returns the column values for the new row.
    """
    template = template or {}
    out = {}
    for key, default in (
        ("itemtype_id", None),
        ("flow_id", None),
        ("index_tree_id", None),
        ("location_id", None),
        ("repository_id", ROOT_REPOSITORY),
    ):
        value = args.get(key)
        if value is None:
            value = template.get(key, default)
        out[key] = value
    open_restricted = args.get("open_restricted")
    if open_restricted is None:
        open_restricted = template.get("open_restricted", False)
    if not isinstance(open_restricted, bool):
        raise contract.HelperError("InvalidArgument", "open_restricted must be a boolean")
    out["open_restricted"] = open_restricted
    for key in ("itemtype_id", "flow_id"):
        if out[key] is None:
            raise contract.HelperError(
                "InvalidArgument", "%s is required (or give copy_from)" % key
            )
    return out


def run_create_flow(params):
    """Create a (deletion) flow with its actions; idempotent by name. UNVERIFIED."""
    import uuid

    from invenio_db import db
    from weko_workflow.models import Action, FlowAction, FlowDefine, FlowStatusPolicy

    args = parse_flow(params)
    wanted_type = DELETE_FLOW_TYPE if args["for_delete"] else REGISTER_FLOW_TYPE
    existing = FlowDefine.query.filter_by(flow_name=args["flow_name"]).one_or_none()
    if existing is not None:
        if existing.flow_type != wanted_type:
            raise contract.HelperError(
                "FlowTypeMismatch",
                "flow %r exists with flow_type %s" % (args["flow_name"], existing.flow_type),
            )
        return {"id": existing.id, "flow_id": str(existing.flow_id), "created": False}

    actions = []
    for endpoint in flow_action_endpoints(args["with_approval"]):
        action = Action.query.filter_by(action_endpoint=endpoint).order_by(Action.id).first()
        if action is None:
            raise contract.HelperError("ActionNotFound", "no workflow action %r" % endpoint)
        actions.append(action)

    flow = FlowDefine(
        flow_id=uuid.uuid4(),
        flow_name=args["flow_name"],
        flow_user=None,
        flow_status=FlowStatusPolicy.AVAILABLE,
        repository_id=args["repository_id"],
        flow_type=wanted_type,
    )
    with db.session.begin_nested():
        db.session.add(flow)
        db.session.flush()
        for order, action in enumerate(actions, start=1):
            db.session.add(
                FlowAction(
                    flow_id=flow.flow_id,
                    action_id=action.id,
                    action_version=action.action_version,
                    action_order=order,
                )
            )
    db.session.commit()
    return {
        "id": flow.id,
        "flow_id": str(flow.flow_id),
        "created": True,
        "actions": flow_action_endpoints(args["with_approval"]),
    }


def _workflow_row(obj):
    return {
        "id": obj.id,
        "itemtype_id": obj.itemtype_id,
        "flow_id": obj.flow_id,
        "delete_flow_id": obj.delete_flow_id,
        "index_tree_id": obj.index_tree_id,
        "location_id": obj.location_id,
        "open_restricted": obj.open_restricted,
        "repository_id": obj.repository_id,
    }


def run_create_workflow(params):
    """Create a workflow (optionally copied from another); idempotent by name. UNVERIFIED.

    An existing workflow of that name only gets its ``delete_flow_id`` aligned
    (the previous value is returned so the host can restore it).
    """
    import uuid

    from invenio_db import db
    from weko_workflow.models import FlowDefine, WorkFlow

    args = parse_workflow(params)
    delete_flow_id = args["delete_flow_id"]
    if args["delete_flow_name"]:
        flow = FlowDefine.query.filter_by(flow_name=args["delete_flow_name"]).one_or_none()
        if flow is None:
            raise contract.HelperError(
                "FlowNotFound", "no flow named %r" % args["delete_flow_name"]
            )
        delete_flow_id = flow.id
    if delete_flow_id is not None:
        flow = FlowDefine.query.filter_by(id=delete_flow_id).one_or_none()
        if flow is None:
            raise contract.HelperError("FlowNotFound", "no flow %s" % delete_flow_id)
        if flow.flow_type != DELETE_FLOW_TYPE:
            raise contract.HelperError(
                "FlowTypeMismatch", "flow %s is not a deletion flow" % delete_flow_id
            )

    existing = WorkFlow.query.filter_by(flows_name=args["flows_name"]).first()
    if existing is not None:
        previous = existing.delete_flow_id
        existing.delete_flow_id = delete_flow_id
        db.session.commit()
        return {
            "id": existing.id,
            "created": False,
            "delete_flow_id": existing.delete_flow_id,
            "previous_delete_flow_id": previous,
        }

    template = None
    if args["copy_from"] is not None:
        source = WorkFlow.query.filter_by(id=args["copy_from"]).one_or_none()
        if source is None:
            raise contract.HelperError("WorkflowNotFound", "no workflow %s" % args["copy_from"])
        template = _workflow_row(source)
    values = merge_workflow_spec(args, template)
    if FlowDefine.query.filter_by(id=values["flow_id"]).one_or_none() is None:
        raise contract.HelperError("FlowNotFound", "no flow %s" % values["flow_id"])
    workflow = WorkFlow(
        flows_id=uuid.uuid4(),
        flows_name=args["flows_name"],
        delete_flow_id=delete_flow_id,
        is_deleted=False,
        is_gakuninrdm=False,
        **values
    )
    db.session.add(workflow)
    db.session.commit()
    return {
        "id": workflow.id,
        "created": True,
        "itemtype_id": workflow.itemtype_id,
        "flow_id": workflow.flow_id,
        "delete_flow_id": workflow.delete_flow_id,
        "previous_delete_flow_id": None,
    }


def parse_delete_record(params):
    """Validate delete_record arguments (pure)."""
    recid = params.get("recid")
    if isinstance(recid, bool) or not isinstance(recid, (str, int)) or not str(recid).isdigit():
        raise contract.HelperError("InvalidArgument", "recid must be a decimal string or integer")
    method = contract.optional_str(params, "method", "soft_delete")
    if method not in ("soft_delete", "pid_only"):
        raise contract.HelperError("InvalidArgument", "method must be soft_delete or pid_only")
    return {
        "recid": str(recid),
        "method": method,
        "restore": contract.optional_bool(params, "restore", False),
    }


def run_delete_record(params):
    """Make a record a deleted recid (PID status DELETED); idempotent. UNVERIFIED.

    ``soft_delete`` (default) calls the application's own
    ``weko_records_ui.utils.soft_delete`` (what the UI and SWORD EP5 use);
    ``pid_only`` just flips the PID rows and returns their previous statuses.
    ``restore: true`` reverses either (``weko_records_ui.utils.restore``).
    """
    from flask import current_app
    from invenio_db import db
    from invenio_pidstore.models import PersistentIdentifier, PIDStatus

    args = parse_delete_record(params)
    pid = PersistentIdentifier.query.filter_by(pid_type="recid", pid_value=args["recid"]).first()
    if pid is None:
        raise contract.HelperError("RecordNotFound", "no recid pid for %s" % args["recid"])
    previous = str(pid.status)
    if args["restore"]:
        if args["method"] == "soft_delete":
            from weko_records_ui.utils import restore

            with current_app.test_request_context():
                restore(args["recid"])
        else:
            for row in PersistentIdentifier.query.filter_by(object_uuid=pid.object_uuid):
                row.status = PIDStatus.REGISTERED
            db.session.commit()
        return {"recid": args["recid"], "previous": previous, "restored": True}
    if pid.status == PIDStatus.DELETED:
        return {"recid": args["recid"], "previous": previous, "deleted": False}
    if args["method"] == "soft_delete":
        from weko_records_ui.utils import soft_delete

        with current_app.test_request_context():
            soft_delete(args["recid"])
        db.session.commit()
    else:
        for row in PersistentIdentifier.query.filter_by(object_uuid=pid.object_uuid):
            row.status = PIDStatus.DELETED
        db.session.commit()
    return {"recid": args["recid"], "previous": previous, "deleted": True}
