from tests.conftest import add_member, login


def submit(client, headers, workflow_id, title):
    response = client.post(
        "/requests", json={"workflow_id": workflow_id, "title": title}, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


def titles(client, headers, **params):
    response = client.get("/requests", headers=headers, params=params)
    assert response.status_code == 200, response.text
    return [item["title"] for item in response.json()["items"]]


def all_pages(client, headers, **params):
    seen, cursor = [], None
    while True:
        page = client.get(
            "/requests",
            headers=headers,
            params={**params, **({"cursor": cursor} if cursor else {})},
        ).json()
        seen.extend(item["title"] for item in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            return seen


def test_pages_newest_first_without_gaps_or_duplicates(client, user_headers, purchase_workflow):
    for i in range(5):
        submit(client, user_headers, purchase_workflow["id"], f"Request {i}")

    first = client.get("/requests", headers=user_headers, params={"limit": 2}).json()

    assert [i["title"] for i in first["items"]] == ["Request 4", "Request 3"]
    assert first["next_cursor"] is not None
    assert all_pages(client, user_headers, limit=2) == [f"Request {i}" for i in range(4, -1, -1)]


def test_new_requests_while_paging_do_not_shift_pages(client, user_headers, purchase_workflow):
    for i in range(4):
        submit(client, user_headers, purchase_workflow["id"], f"Request {i}")
    first = client.get("/requests", headers=user_headers, params={"limit": 2}).json()

    # With OFFSET, this new row would push "Request 2" onto page two as well.
    submit(client, user_headers, purchase_workflow["id"], "Arrived mid-scroll")
    second = client.get(
        "/requests", headers=user_headers, params={"limit": 2, "cursor": first["next_cursor"]}
    ).json()

    assert [i["title"] for i in second["items"]] == ["Request 1", "Request 0"]


def test_summary_shows_current_step(client, user_headers, purchase_workflow):
    submit(client, user_headers, purchase_workflow["id"], "Laptop")

    item = client.get("/requests", headers=user_headers).json()["items"][0]

    assert item["status"] == "pending"
    assert item["current_step"]["name"] == "Manager review"
    assert "steps" not in item


def test_listing_respects_visibility(
    client, admin_headers, user_headers, make_user, purchase_workflow
):
    submit(client, user_headers, purchase_workflow["id"], "Laptop")
    make_user("bystander@example.com")

    assert titles(client, login(client, "bystander@example.com")) == []
    assert titles(client, purchase_workflow["finance_approver"]) == ["Laptop"]  # has a later step
    assert titles(client, admin_headers) == ["Laptop"]


def test_mine_filter(client, admin_headers, user_headers, make_user, purchase_workflow):
    colleague_id = make_user("colleague@example.com")
    add_member(client, admin_headers, purchase_workflow["managers"], colleague_id)
    colleague = login(client, "colleague@example.com")
    submit(client, user_headers, purchase_workflow["id"], "Theirs")
    submit(client, colleague, purchase_workflow["id"], "Mine")

    # The colleague can see both (one as an approver) but only submitted one.
    assert titles(client, colleague) == ["Mine", "Theirs"]
    assert titles(client, colleague, mine=True) == ["Mine"]


def test_assigned_to_me_follows_the_active_step(client, user_headers, purchase_workflow):
    request = submit(client, user_headers, purchase_workflow["id"], "Laptop")
    manager, finance = purchase_workflow["manager"], purchase_workflow["finance_approver"]

    assert titles(client, manager, assigned_to_me=True) == ["Laptop"]
    assert titles(client, finance, assigned_to_me=True) == []

    client.post(
        f"/requests/{request['id']}/approve", json={"version": request["version"]}, headers=manager
    )

    assert titles(client, manager, assigned_to_me=True) == []
    assert titles(client, finance, assigned_to_me=True) == ["Laptop"]


def test_assigned_to_me_excludes_own_requests(client, admin_headers, make_user, purchase_workflow):
    approver_id = make_user("approver@example.com")
    add_member(client, admin_headers, purchase_workflow["managers"], approver_id)
    approver = login(client, "approver@example.com")
    submit(client, approver, purchase_workflow["id"], "My own")

    assert titles(client, approver, assigned_to_me=True) == []


def test_status_filter(client, user_headers, purchase_workflow):
    keep = submit(client, user_headers, purchase_workflow["id"], "Still pending")
    gone = submit(client, user_headers, purchase_workflow["id"], "Withdrawn")
    client.post(
        f"/requests/{gone['id']}/withdraw", json={"version": gone["version"]}, headers=user_headers
    )

    assert titles(client, user_headers, status="pending") == [keep["title"]]
    assert titles(client, user_headers, status="withdrawn") == [gone["title"]]


def test_workflow_filter(client, admin_headers, user_headers, purchase_workflow):
    other = client.post(
        "/workflows",
        json={
            "name": "Travel",
            "steps": [
                {"name": "OK", "approver_group_id": purchase_workflow["managers"], "sla_hours": 8}
            ],
        },
        headers=admin_headers,
    ).json()
    submit(client, user_headers, purchase_workflow["id"], "Laptop")
    submit(client, user_headers, other["id"], "Flight")

    assert titles(client, user_headers, workflow_id=other["id"]) == ["Flight"]


def test_bad_parameters_rejected(client, user_headers):
    assert (
        client.get("/requests", headers=user_headers, params={"cursor": "junk"}).status_code == 422
    )
    assert client.get("/requests", headers=user_headers, params={"limit": 101}).status_code == 422
    assert (
        client.get("/requests", headers=user_headers, params={"status": "lost"}).status_code == 422
    )
