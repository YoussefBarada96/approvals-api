import uuid

from tests.conftest import create_group


def workflow_body(group_id, name="Travel", steps=1):
    return {
        "name": name,
        "steps": [
            {"name": f"Step {i}", "approver_group_id": group_id, "sla_hours": 8}
            for i in range(1, steps + 1)
        ],
    }


def test_admin_creates_workflow_with_ordered_steps(client, admin_headers):
    group = create_group(client, admin_headers, "Managers")

    response = client.post("/workflows", json=workflow_body(group, steps=3), headers=admin_headers)

    assert response.status_code == 201
    body = response.json()
    assert body["is_active"] is True
    assert [(s["position"], s["name"]) for s in body["steps"]] == [
        (1, "Step 1"),
        (2, "Step 2"),
        (3, "Step 3"),
    ]


def test_non_admin_cannot_create_workflow(client, admin_headers, user_headers):
    group = create_group(client, admin_headers, "Managers")

    response = client.post("/workflows", json=workflow_body(group), headers=user_headers)

    assert response.status_code == 403


def test_workflow_needs_at_least_one_step(client, admin_headers):
    response = client.post("/workflows", json={"name": "Empty", "steps": []}, headers=admin_headers)

    assert response.status_code == 422


def test_workflow_with_unknown_group_rejected(client, admin_headers):
    unknown = str(uuid.uuid4())

    response = client.post("/workflows", json=workflow_body(unknown), headers=admin_headers)

    assert response.status_code == 422
    assert unknown in response.json()["detail"]


def test_duplicate_workflow_name_conflicts(client, admin_headers):
    group = create_group(client, admin_headers, "Managers")
    client.post("/workflows", json=workflow_body(group), headers=admin_headers)

    response = client.post("/workflows", json=workflow_body(group), headers=admin_headers)

    assert response.status_code == 409


def test_inactive_workflows_hidden_from_users(client, admin_headers, user_headers):
    group = create_group(client, admin_headers, "Managers")
    client.post("/workflows", json=workflow_body(group, name="Active"), headers=admin_headers)
    retired = client.post(
        "/workflows", json=workflow_body(group, name="Retired"), headers=admin_headers
    ).json()["id"]
    client.patch(f"/workflows/{retired}", json={"is_active": False}, headers=admin_headers)

    def names(headers, **params):
        return [w["name"] for w in client.get("/workflows", headers=headers, params=params).json()]

    assert names(user_headers) == ["Active"]
    assert names(user_headers, include_inactive=True) == ["Active"]  # ignored for non-admins
    assert names(admin_headers, include_inactive=True) == ["Active", "Retired"]


def test_patch_only_changes_sent_fields(client, admin_headers):
    group = create_group(client, admin_headers, "Managers")
    created = client.post(
        "/workflows",
        json={**workflow_body(group), "description": "Original"},
        headers=admin_headers,
    ).json()

    response = client.patch(
        f"/workflows/{created['id']}", json={"name": "Business travel"}, headers=admin_headers
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Business travel"
    assert response.json()["description"] == "Original"


def test_replace_steps(client, admin_headers):
    managers = create_group(client, admin_headers, "Managers")
    finance = create_group(client, admin_headers, "Finance")
    created = client.post(
        "/workflows", json=workflow_body(managers, steps=2), headers=admin_headers
    ).json()

    response = client.put(
        f"/workflows/{created['id']}/steps",
        json={"steps": [{"name": "Finance only", "approver_group_id": finance, "sla_hours": 4}]},
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert [(s["position"], s["name"]) for s in response.json()["steps"]] == [(1, "Finance only")]


def test_unknown_workflow_404(client, user_headers):
    assert client.get(f"/workflows/{uuid.uuid4()}", headers=user_headers).status_code == 404
