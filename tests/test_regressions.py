import asyncio
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi import HTTPException
from sqlalchemy.engine import make_url

from app.api.v1 import users
from app.core import settings
from app.core.security import decode_token, get_token_user
from app.core.settings import Settings
from app.db.models import ConversationMember, Message
from scripts import seed_demo
from sqlalchemy import select


def test_database_url_escapes_credentials():
    config = Settings(
        _env_file=None,
        postgres_host="localhost",
        postgres_user="user@name",
        postgres_password="pass:/@%word",
        postgres_db="test",
        jwt_secret_key="test",
    )
    url = make_url(config.database_url)
    assert url.username == "user@name"
    assert url.password == "pass:/@%word"
    assert url.host == "localhost"


def test_tokens_require_expiry():
    token = jwt.encode(
        {"sub": str(uuid4()), "jti": str(uuid4()), "type": "access"},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(HTTPException) as exc:
        decode_token(token)
    assert exc.value.status_code == 401


@pytest.mark.parametrize(
    "subject,jti", [(42, "token"), ([], "token"), (str(uuid4()), [])]
)
def test_malformed_claims_return_401(db, subject, jti):
    with pytest.raises(HTTPException) as exc:
        get_token_user(db, {"sub": subject, "jti": jti, "type": "access"}, "access")
    assert exc.value.status_code == 401


@pytest.mark.parametrize("limit,offset", [(-1, 0), (10, -1), (0, 0)])
def test_negative_pagination_rejected(client, register, limit, offset):
    register()
    response = client.get(
        f"/api/v1/conversations/{uuid4()}/messages",
        params={"limit": limit, "offset": offset},
    )
    assert response.status_code == 422


@pytest.mark.parametrize("value", ["null", "[]", '"string"', "true", "123", "{bad"])
def test_malformed_user_cache_is_skipped(value):
    redis = AsyncMock()
    redis.mget.return_value = [value]
    result = asyncio.run(users._get_cached_users(redis, ["user"]))
    assert result == {}


def test_malformed_report_cache_is_removed():
    redis = AsyncMock()
    redis.georadius.return_value = ["reports:1", "reports:2", "reports:3"]
    redis.mget.return_value = ["null", "[]", '{"id": "3"}']
    result = asyncio.run(
        users._get_nearby_reports(redis, users.LocationMessage(lat=32, lng=34))
    )
    assert result == [{"id": "3"}]
    redis.zrem.assert_awaited_once_with(
        users.REPORTS_LOCATIONS_KEY, "reports:1", "reports:2"
    )


def test_seed_read_marker_points_to_last_message(db):
    demo_users = seed_demo.seed_users(db)
    seed_demo.seed_conversations(db, demo_users)
    db.commit()
    members = db.scalars(select(ConversationMember)).all()
    read_members = [
        member for member in members if member.last_read_message_id is not None
    ]
    assert len(read_members) == len(seed_demo.DEMO_CONVERSATIONS)
    for member in read_members:
        message = db.get(Message, member.last_read_message_id)
        assert message.conversation_id == member.conversation_id


def test_websocket_bad_json_and_shape_keep_connection_open(
    client, register, monkeypatch
):
    data = register()
    user = users.UserRead.model_validate(data["user"])
    monkeypatch.setattr(users, "get_websocket_user", lambda _: user)
    redis = AsyncMock()
    redis.georadius.return_value = []
    monkeypatch.setattr(users, "create_redis_client", lambda: redis)
    with client.websocket_connect("/api/v1/location/ws") as websocket:
        websocket.send_text("{bad")
        assert websocket.receive_json()["type"] == "validation_error"
        websocket.send_json({"lat": [], "lng": 34})
        assert websocket.receive_json()["type"] == "validation_error"
        websocket.send_json({"lat": 32, "lng": 34})
        assert websocket.receive_json()["type"] == "nearby_map_data"
    redis.aclose.assert_awaited_once()


def test_websocket_refreshes_privacy_settings(client, register, monkeypatch):
    data = register()
    visible = users.UserRead.model_validate(data["user"])
    hidden = visible.model_copy(update={"hide_me": True})
    monkeypatch.setattr(
        users,
        "get_websocket_user",
        Mock(side_effect=[visible, hidden]),
    )
    redis = AsyncMock()
    redis.georadius.return_value = []
    monkeypatch.setattr(users, "create_redis_client", lambda: redis)
    with client.websocket_connect("/api/v1/location/ws") as websocket:
        websocket.send_json({"lat": 32, "lng": 34})
        assert websocket.receive_json()["me"]["hide_me"] is True
    redis.geoadd.assert_not_awaited()


def test_logout_conflict_preserves_other_revocations(client, register, db, monkeypatch):
    from app.api.v1 import auth
    from app.db.models import TokenBlocklist
    from datetime import datetime, timezone

    data = register()
    token = data["tokens"]["access_token"]
    payload = decode_token(token)
    original_get_token_user = auth.get_token_user
    simulated = False

    def concurrent_revocation(db, claims, token_type):
        nonlocal simulated
        user = original_get_token_user(db, claims, token_type)
        if not simulated and claims["jti"] == payload["jti"]:
            simulated = True
            # Another logout commits after this request's revocation check.
            db.add(
                TokenBlocklist(
                    jti=claims["jti"],
                    token_type="access",
                    user_id=str(user.id),
                    expires_at=datetime.fromtimestamp(claims["exp"], tz=timezone.utc),
                )
            )
            db.commit()
        return user

    monkeypatch.setattr(auth, "get_token_user", concurrent_revocation)
    response = client.post("/api/v1/auth/logout")
    assert response.status_code == 200
    assert response.json()["revoked_tokens"] == 1
    refresh = data["tokens"]["refresh_token"]
    assert (
        client.post(
            "/api/v1/auth/refresh", headers={"Authorization": f"Bearer {refresh}"}
        ).status_code
        == 401
    )


def test_websocket_rejects_untrusted_origin(client, register):
    register()
    from fastapi import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(
            "/api/v1/location/ws", headers={"origin": "https://untrusted.example"}
        ):
            pass
    assert exc.value.code == 1008


def test_websocket_rejects_coordinates_outside_redis_range(
    client, register, monkeypatch
):
    data = register()
    user = users.UserRead.model_validate(data["user"])
    monkeypatch.setattr(users, "get_websocket_user", lambda _: user)
    redis = AsyncMock()
    redis.georadius.return_value = []
    monkeypatch.setattr(users, "create_redis_client", lambda: redis)
    with client.websocket_connect("/api/v1/location/ws") as websocket:
        websocket.send_json({"lat": 89, "lng": 34})
        assert websocket.receive_json()["type"] == "validation_error"
    redis.geoadd.assert_not_awaited()


def test_websocket_nonfinite_coordinates_return_serializable_errors(
    client, register, monkeypatch
):
    data = register()
    user = users.UserRead.model_validate(data["user"])
    monkeypatch.setattr(users, "get_websocket_user", lambda _: user)
    redis = AsyncMock()
    monkeypatch.setattr(users, "create_redis_client", lambda: redis)
    with client.websocket_connect("/api/v1/location/ws") as websocket:
        websocket.send_text('{"lat": NaN, "lng": 34}')
        assert websocket.receive_json()["type"] == "validation_error"


def test_concurrent_settings_creation_reuses_existing_row(db, register, monkeypatch):
    from app.core.user_cache import get_or_create_user_settings
    from app.db.models import User, UserSetting

    data = register()
    user = db.get(User, UUID(data["user"]["id"]))
    setting = db.scalar(select(UserSetting).where(UserSetting.user_id == user.id))
    original_scalar = db.scalar
    stale_lookup = True

    def lookup(statement, *args, **kwargs):
        nonlocal stale_lookup
        if stale_lookup:
            # Simulate the initial lookup occurring before a competing insert commits.
            stale_lookup = False
            return None
        return original_scalar(statement, *args, **kwargs)

    monkeypatch.setattr(db, "scalar", lookup)
    result = get_or_create_user_settings(db, user)
    assert result.id == setting.id
    assert result.hide_me is False
    # The session remains usable after the unique-constraint collision.
    assert db.scalar(select(User).where(User.id == user.id)) is user
