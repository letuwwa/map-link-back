from uuid import UUID, uuid4

import jwt
import pytest
from redis.exceptions import ConnectionError
from sqlalchemy import select

from app.core import settings
from app.core.security import create_access_token
from app.db.models import User, UserRole, UserSetting


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_root_and_auth_lifecycle(client, register):
    assert client.get("/").json()["status"] == "ok"
    data = register()
    assert data["user"]["allow_incoming_messages"] is True
    assert data["user"]["hide_me"] is False
    assert (
        "HttpOnly"
        in client.post(
            "/api/v1/auth/login", data={"username": "driver", "password": "password123"}
        ).headers["set-cookie"]
    )
    assert client.get("/api/v1/auth/me").json()["id"] == data["user"]["id"]
    assert client.get("/api/v1/auth/admin-only").status_code == 403
    assert client.post("/api/v1/auth/refresh").status_code == 200
    token_response = client.post(
        "/api/v1/auth/token",
        data={"username": "driver@example.com", "password": "password123"},
    )
    assert token_response.status_code == 200
    tokens = token_response.json()
    response = client.post("/api/v1/auth/logout")
    assert response.json()["revoked_tokens"] == 2
    assert not client.cookies
    assert client.get("/api/v1/auth/me").status_code == 401
    assert (
        client.get(
            "/api/v1/auth/me", headers=bearer(tokens["access_token"])
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/auth/refresh", headers=bearer(tokens["refresh_token"])
        ).status_code
        == 401
    )
    assert client.post("/api/v1/auth/logout").json()["revoked_tokens"] == 0


def test_auth_errors_and_admin(client, register, db):
    data = register()
    duplicate = client.post(
        "/api/v1/auth/register",
        json={
            "email": "driver@example.com",
            "username": "other",
            "first_name": "A",
            "last_name": "B",
            "password": "password123",
        },
    )
    assert duplicate.status_code == 409
    for username, password in [("missing", "password123"), ("driver", "wrong")]:
        assert (
            client.post(
                "/api/v1/auth/login", data={"username": username, "password": password}
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/api/v1/auth/refresh", headers=bearer(data["tokens"]["access_token"])
        ).status_code
        == 401
    )
    assert client.get("/api/v1/auth/me", headers=bearer("invalid")).status_code == 401
    user = db.get(User, UUID(data["user"]["id"]))
    user.role = UserRole.ADMIN
    db.commit()
    assert client.get("/api/v1/auth/admin-only").json()["user_id"] == str(user.id)
    user.is_active = False
    db.commit()
    assert client.get("/api/v1/auth/me").status_code == 401
    assert (
        client.post(
            "/api/v1/auth/login", data={"username": "driver", "password": "password123"}
        ).status_code
        == 403
    )


def test_bearer_overrides_cookie_and_logout_deduplicates(client, register):
    data = register()
    access = data["tokens"]["access_token"]
    assert client.get("/api/v1/auth/me", headers=bearer("bad")).status_code == 401
    assert (
        client.post("/api/v1/auth/logout", headers=bearer(access)).json()[
            "revoked_tokens"
        ]
        == 2
    )
    assert (
        client.post("/api/v1/auth/logout", headers=bearer(access)).json()[
            "revoked_tokens"
        ]
        == 0
    )
    assert (
        client.post("/api/v1/auth/logout", headers=bearer("invalid")).status_code == 200
    )


def test_missing_and_expired_token(client):
    assert client.post("/api/v1/auth/refresh").status_code == 401
    payload = {"sub": str(uuid4()), "jti": str(uuid4()), "type": "access", "exp": 1}
    expired = jwt.encode(
        payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )
    assert client.get("/api/v1/auth/me", headers=bearer(expired)).status_code == 401


def test_settings_create_patch_and_cache_failure(client, register, db, redis_client):
    data = register()
    assert client.get("/api/v1/users/settings").json() == {
        "allow_incoming_messages": True,
        "hide_me": False,
    }
    response = client.patch(
        "/api/v1/users/settings",
        json={"hide_me": True, "allow_incoming_messages": False},
    )
    assert response.json() == {"allow_incoming_messages": False, "hide_me": True}
    assert (
        client.patch("/api/v1/users/settings", json={"hide_me": None}).json()
        == response.json()
    )
    assert client.get("/api/v1/auth/me").json()["hide_me"] is True
    redis_client.set.side_effect = ConnectionError("offline")
    assert (
        client.patch("/api/v1/users/settings", json={"hide_me": False}).status_code
        == 200
    )
    assert client.get("/api/v1/auth/me").status_code == 200
    setting = db.scalar(
        select(UserSetting).where(UserSetting.user_id == UUID(data["user"]["id"]))
    )
    db.delete(setting)
    db.commit()
    assert client.get("/api/v1/users/settings").json()["hide_me"] is False


def test_report_create_permissions_and_delete(client, register, redis_client):
    owner = register()
    body = {"report_type": "TRAFFIC_JAM", "latitude": 32.0853, "longitude": 34.7818}
    response = client.post("/api/v1/reports", json=body)
    assert response.status_code == 201
    report = response.json()
    assert report["user_id"] == owner["user"]["id"]
    assert report["report_type"] == "TRAFFIC_JAM"
    redis_client.geoadd.assert_called_once()
    assert redis_client.set.call_args.kwargs["ex"] == 10800
    register("other")
    assert (
        client.post(
            "/api/v1/reports/deleteReport", json={"report_id": report["id"]}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/reports/deleteReport",
            headers=bearer(owner["tokens"]["access_token"]),
            json={"report_id": report["id"]},
        ).status_code
        == 200
    )
    redis_client.zrem.assert_called_once_with(
        "reports_locations", f"reports:{report['id']}"
    )
    assert (
        client.post(
            "/api/v1/reports/deleteReport", json={"report_id": report["id"]}
        ).status_code
        == 404
    )


def test_reports_survive_cache_outage(client, register, redis_client):
    register()
    redis_client.set.side_effect = ConnectionError("offline")
    report = client.post("/api/v1/reports", json={"latitude": 32, "longitude": 34})
    assert report.status_code == 201
    redis_client.delete.side_effect = ConnectionError("offline")
    assert (
        client.post(
            "/api/v1/reports/deleteReport", json={"report_id": report.json()["id"]}
        ).status_code
        == 200
    )
    assert redis_client.close.call_count >= 3


@pytest.mark.parametrize(
    "body",
    [
        {"latitude": 91, "longitude": 34},
        {"latitude": 32, "longitude": -181},
        {"latitude": 32, "longitude": 34, "report_type": "INVALID"},
    ],
)
def test_report_validation(client, register, body):
    register()
    assert client.post("/api/v1/reports", json=body).status_code == 422


def test_unknown_user_token_rejected(client):
    user = User(id=uuid4(), role=UserRole.REGULAR)
    assert (
        client.get(
            "/api/v1/auth/me", headers=bearer(create_access_token(user))
        ).status_code
        == 401
    )
