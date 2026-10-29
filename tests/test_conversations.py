from uuid import UUID, uuid4

from app.db.models import UserSetting
from sqlalchemy import select


def auth(data):
    return {"Authorization": f"Bearer {data['tokens']['access_token']}"}


def test_direct_messages_membership_and_read(client, register, db):
    first = register("first")
    second = register("second")
    outsider = register("outsider")
    response = client.post(
        "/api/v1/conversations/direct",
        headers=auth(first),
        json={"user_id": second["user"]["id"]},
    )
    assert response.status_code == 201
    conversation = response.json()
    cid = conversation["id"]
    assert len(conversation["members"]) == 2
    assert conversation["last_message"] is None
    again = client.post(
        "/api/v1/conversations/direct",
        headers=auth(second),
        json={"user_id": first["user"]["id"]},
    )
    assert again.json()["id"] == cid
    assert (
        client.get(f"/api/v1/conversations/{cid}", headers=auth(outsider)).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v1/conversations/{cid}/messages", headers=auth(outsider)
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/conversations/{cid}/messages",
            headers=auth(outsider),
            json={"body": "no"},
        ).status_code
        == 404
    )
    messages = []
    for text in ["Hello", "How is the road?"]:
        response = client.post(
            f"/api/v1/conversations/{cid}/messages",
            headers=auth(first),
            json={"body": text},
        )
        assert response.status_code == 201
        messages.append(response.json())
    from app.db.models import Message
    from datetime import datetime, timedelta, timezone

    # Keep ordering deterministic despite SQLite's second-precision server clock.
    for index, message in enumerate(messages):
        db.get(Message, UUID(message["id"])).created_at = datetime(
            2026, 1, 1, tzinfo=timezone.utc
        ) + timedelta(seconds=index)
    db.commit()
    response = client.get(
        f"/api/v1/conversations/{cid}/messages",
        headers=auth(second),
        params={"limit": 1, "offset": 1},
    )
    assert [message["body"] for message in response.json()] == ["How is the road?"]
    detail = client.get(f"/api/v1/conversations/{cid}", headers=auth(second)).json()
    assert detail["last_message"]["id"] == messages[-1]["id"]
    assert len(client.get("/api/v1/conversations", headers=auth(first)).json()) == 1
    assert client.get("/api/v1/conversations", headers=auth(outsider)).json() == []
    assert (
        client.post(
            f"/api/v1/conversations/{cid}/read",
            headers=auth(second),
            json={"message_id": messages[-1]["id"]},
        ).status_code
        == 200
    )
    detail = client.get(f"/api/v1/conversations/{cid}", headers=auth(second)).json()
    member = next(
        member
        for member in detail["members"]
        if member["user_id"] == second["user"]["id"]
    )
    assert member["last_read_message_id"] == messages[-1]["id"]
    assert (
        client.post(
            f"/api/v1/conversations/{cid}/read",
            headers=auth(second),
            json={"message_id": str(uuid4())},
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/conversations/{cid}/messages",
            headers=auth(first),
            json={"body": ""},
        ).status_code
        == 422
    )


def test_direct_validation_and_recipient_privacy(client, register, db):
    first = register("first")
    second = register("second")
    assert (
        client.post(
            "/api/v1/conversations/direct", json={"user_id": second["user"]["id"]}
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/v1/conversations/direct", json={"user_id": str(uuid4())}
        ).status_code
        == 404
    )
    client.patch("/api/v1/users/settings", json={"allow_incoming_messages": False})
    assert (
        client.post(
            "/api/v1/conversations/direct",
            headers=auth(first),
            json={"user_id": second["user"]["id"]},
        ).status_code
        == 403
    )
    setting = db.scalar(
        select(UserSetting).where(UserSetting.user_id == UUID(second["user"]["id"]))
    )
    setting.allow_incoming_messages = True
    db.commit()
    cid = client.post(
        "/api/v1/conversations/direct",
        headers=auth(first),
        json={"user_id": second["user"]["id"]},
    ).json()["id"]
    setting.allow_incoming_messages = False
    db.commit()
    assert (
        client.post(
            f"/api/v1/conversations/{cid}/messages",
            headers=auth(first),
            json={"body": "blocked"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/conversations/{cid}/messages",
            headers=auth(second),
            json={"body": "outgoing allowed"},
        ).status_code
        == 201
    )


def test_report_conversation_and_cross_conversation_read(client, register):
    register()
    report = client.post(
        "/api/v1/reports", json={"latitude": 32, "longitude": 34}
    ).json()
    response = client.post(
        "/api/v1/conversations/reports",
        json={"report_id": report["id"], "title": "Road danger"},
    )
    assert response.status_code == 201
    conversation = response.json()
    assert conversation["conversation_type"] == "report"
    assert conversation["title"] == "Road danger"
    cid = conversation["id"]
    message = client.post(
        f"/api/v1/conversations/{cid}/messages", json={"body": "Report update"}
    ).json()
    other = client.post(
        "/api/v1/conversations/reports", json={"report_id": report["id"]}
    ).json()
    assert (
        client.post(
            f"/api/v1/conversations/{other['id']}/read",
            json={"message_id": message["id"]},
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/v1/conversations/reports", json={"report_id": str(uuid4())}
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/v1/reports/deleteReport", json={"report_id": report["id"]}
        ).status_code
        == 200
    )
    assert client.get(f"/api/v1/conversations/{cid}").json()["report_id"] is None
