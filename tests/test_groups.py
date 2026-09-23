import uuid

from tests.conftest import login


def create_group(client, headers, name="Finance"):
    return client.post("/groups", json={"name": name}, headers=headers)


def test_admin_creates_group(client, admin_headers):
    response = create_group(client, admin_headers, name="  Finance  ")

    assert response.status_code == 201
    assert response.json()["name"] == "Finance"


def test_non_admin_cannot_create_group(client, user_headers):
    response = create_group(client, user_headers)

    assert response.status_code == 403


def test_duplicate_group_name_conflicts(client, admin_headers):
    create_group(client, admin_headers)

    response = create_group(client, admin_headers)

    assert response.status_code == 409


def test_any_user_can_list_groups(client, admin_headers, user_headers):
    create_group(client, admin_headers, "Managers")
    create_group(client, admin_headers, "Finance")

    response = client.get("/groups", headers=user_headers)

    assert response.status_code == 200
    assert [g["name"] for g in response.json()] == ["Finance", "Managers"]


def test_listing_groups_requires_login(client, db):
    assert client.get("/groups").status_code == 401


def test_add_and_remove_member(client, admin_headers, make_user):
    user_id = make_user("approver@example.com")
    group_id = create_group(client, admin_headers).json()["id"]
    member_path = f"/groups/{group_id}/members/{user_id}"
    approver = login(client, "approver@example.com")

    assert client.put(member_path, headers=admin_headers).status_code == 204
    # Idempotent: adding an existing member again is fine.
    assert client.put(member_path, headers=admin_headers).status_code == 204
    groups = client.get("/users/me", headers=approver).json()["groups"]
    assert [g["name"] for g in groups] == ["Finance"]

    assert client.delete(member_path, headers=admin_headers).status_code == 204
    assert client.get("/users/me", headers=approver).json()["groups"] == []


def test_membership_changes_need_admin(client, admin_headers, user_headers, make_user):
    user_id = make_user("other@example.com")
    group_id = create_group(client, admin_headers).json()["id"]

    response = client.put(f"/groups/{group_id}/members/{user_id}", headers=user_headers)

    assert response.status_code == 403


def test_membership_404s_for_unknown_group_or_user(client, admin_headers, make_user):
    user_id = make_user("real@example.com")
    group_id = create_group(client, admin_headers).json()["id"]

    unknown_group = client.put(f"/groups/{uuid.uuid4()}/members/{user_id}", headers=admin_headers)
    unknown_user = client.put(f"/groups/{group_id}/members/{uuid.uuid4()}", headers=admin_headers)

    assert unknown_group.status_code == 404
    assert unknown_user.status_code == 404
