import uuid
from datetime import datetime, timedelta

from tests.conftest import create_group, login


def submit(client, headers, workflow_id, **overrides):
    body = {"workflow_id": workflow_id, "title": "New laptop", "details": {"amount": 1800}}
    return client.post("/requests", json=body | overrides, headers=headers)


def test_submit_starts_first_step(client, user_headers, purchase_workflow):
    response = submit(client, user_headers, purchase_workflow["id"])

    assert response.status_code == 201
    request = response.json()
    assert request["status"] == "pending"
    assert request["version"] == 1
    assert request["details"] == {"amount": 1800}

    first, second = request["steps"]
    assert (first["name"], first["status"]) == ("Manager review", "active")
    assert (second["name"], second["status"]) == ("Finance review", "waiting")
    activated = datetime.fromisoformat(first["activated_at"])
    assert datetime.fromisoformat(first["due_at"]) - activated == timedelta(hours=24)
    assert second["due_at"] is None


def test_submit_records_audit_event(client, user_headers, purchase_workflow):
    request = submit(client, user_headers, purchase_workflow["id"]).json()

    history = client.get(f"/requests/{request['id']}/history", headers=user_headers).json()

    assert len(history) == 1
    assert history[0]["action"] == "submitted"
    assert history[0]["actor_id"] == request["requester_id"]
    assert history[0]["data"]["workflow_name"] == "Purchase order"


def test_submit_to_unknown_workflow_404(client, user_headers, db):
    assert submit(client, user_headers, str(uuid.uuid4())).status_code == 404


def test_submit_to_inactive_workflow_rejected(
    client, admin_headers, user_headers, purchase_workflow
):
    client.patch(
        f"/workflows/{purchase_workflow['id']}", json={"is_active": False}, headers=admin_headers
    )

    response = submit(client, user_headers, purchase_workflow["id"])

    assert response.status_code == 422


def test_submit_validates_title_and_details_size(client, user_headers, purchase_workflow):
    assert submit(client, user_headers, purchase_workflow["id"], title="   ").status_code == 422
    too_big = {"notes": "x" * 20_000}
    assert submit(client, user_headers, purchase_workflow["id"], details=too_big).status_code == 422


def test_request_visible_to_requester_approvers_and_admins(
    client, admin_headers, user_headers, purchase_workflow
):
    request_id = submit(client, user_headers, purchase_workflow["id"]).json()["id"]

    for headers in (
        user_headers,
        admin_headers,
        purchase_workflow["manager"],
        purchase_workflow["finance_approver"],  # later step, can already see it
    ):
        assert client.get(f"/requests/{request_id}", headers=headers).status_code == 200


def test_request_hidden_from_unrelated_users(client, make_user, user_headers, purchase_workflow):
    request_id = submit(client, user_headers, purchase_workflow["id"]).json()["id"]
    make_user("bystander@example.com")
    bystander = login(client, "bystander@example.com")

    # 404, not 403: an outsider can't tell the request exists.
    assert client.get(f"/requests/{request_id}", headers=bystander).status_code == 404
    assert client.get(f"/requests/{request_id}/history", headers=bystander).status_code == 404


def test_editing_workflow_does_not_change_submitted_requests(
    client, admin_headers, user_headers, purchase_workflow
):
    request_id = submit(client, user_headers, purchase_workflow["id"]).json()["id"]
    legal = create_group(client, admin_headers, "Legal")

    client.put(
        f"/workflows/{purchase_workflow['id']}/steps",
        json={"steps": [{"name": "Legal review", "approver_group_id": legal, "sla_hours": 1}]},
        headers=admin_headers,
    )

    steps = client.get(f"/requests/{request_id}", headers=user_headers).json()["steps"]
    assert [s["name"] for s in steps] == ["Manager review", "Finance review"]
