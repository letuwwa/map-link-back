import asyncio
import json
from unittest.mock import AsyncMock, Mock

import pytest

from app.api.v1 import users


def test_nearby_users_filter_self_hidden_missing_and_invalid_cache():
    redis = AsyncMock()
    redis.georadius.return_value = [
        ("self", (34, 32)),
        ("visible", (34.1, 32.1)),
        ("hidden", (34.2, 32.2)),
        ("missing", (34.3, 32.3)),
    ]
    redis.mget.return_value = [
        json.dumps(
            {"id": "visible", "allow_incoming_messages": False, "hide_me": False}
        ),
        json.dumps({"id": "hidden", "allow_incoming_messages": True, "hide_me": True}),
        None,
    ]
    result = asyncio.run(
        users._get_nearby_users(redis, "self", users.LocationMessage(lat=32, lng=34))
    )
    assert result == [
        {
            "user_id": "visible",
            "lng": 34.1,
            "lat": 32.1,
            "allow_incoming_messages": False,
            "hide_me": False,
        }
    ]
    assert redis.zrem.await_count == 2
    assert asyncio.run(users._get_cached_users(redis, [])) == {}


def test_report_cache_missing_invalid_and_empty():
    redis = AsyncMock()
    redis.georadius.return_value = ["missing", "invalid", "good"]
    redis.mget.return_value = [None, "{bad", '{"id": "good"}']
    assert asyncio.run(
        users._get_nearby_reports(redis, users.LocationMessage(lat=32, lng=34))
    ) == [{"id": "good"}]
    redis.zrem.assert_awaited_once_with(
        users.REPORTS_LOCATIONS_KEY, "missing", "invalid"
    )
    redis.georadius.return_value = []
    assert (
        asyncio.run(
            users._get_nearby_reports(redis, users.LocationMessage(lat=32, lng=34))
        )
        == []
    )


def test_websocket_authentication_closes_session(db, register, monkeypatch):
    data = register()
    session = Mock(wraps=db)
    # Avoid closing the shared test session, but assert application cleanup.
    session.close = Mock()
    monkeypatch.setattr(users, "SessionLocal", lambda: session)
    user = users.get_websocket_user(data["tokens"]["access_token"])
    assert str(user.id) == data["user"]["id"]
    assert users.get_websocket_user(None) is None
    assert users.get_websocket_user("invalid") is None
    assert session.close.call_count == 2


def test_websocket_unauthorized(client, monkeypatch):
    monkeypatch.setattr(users, "get_websocket_user", lambda _: None)
    with client.websocket_connect("/api/v1/location/ws") as websocket:
        assert websocket.receive_json()["type"] == "auth_error"
        event = websocket.receive()
        assert event["type"] == "websocket.close"
        assert event["code"] == 1008


def test_websocket_rechecks_revocation(client, register, monkeypatch):
    data = register()
    user = users.UserRead.model_validate(data["user"])
    monkeypatch.setattr(users, "get_websocket_user", Mock(side_effect=[user, None]))
    redis = AsyncMock()
    monkeypatch.setattr(users, "create_redis_client", lambda: redis)
    with client.websocket_connect("/api/v1/location/ws") as websocket:
        websocket.send_json({"lat": 32, "lng": 34})
        assert websocket.receive_json()["type"] == "auth_error"
        assert websocket.receive()["code"] == 1008
    redis.geoadd.assert_not_awaited()
    redis.aclose.assert_awaited_once()


def test_websocket_validation_context_is_serializable(client, register, monkeypatch):
    data = register()
    user = users.UserRead.model_validate(data["user"])
    monkeypatch.setattr(users, "get_websocket_user", lambda _: user)
    redis = AsyncMock()
    redis.georadius.return_value = []
    monkeypatch.setattr(users, "create_redis_client", lambda: redis)
    with client.websocket_connect("/api/v1/location/ws") as websocket:
        for body in [{"lat": 91, "lng": 34}, None, {"lat": 32, "lng": []}]:
            websocket.send_json(body)
            assert websocket.receive_json()["type"] == "validation_error"


def test_redis_connection_closed_when_cleanup_fails(register, monkeypatch):
    data = register()
    user = users.UserRead.model_validate(data["user"])
    monkeypatch.setattr(users, "get_websocket_user", lambda _: user)
    redis = AsyncMock()
    redis.zrem.side_effect = RuntimeError("cleanup failed")
    monkeypatch.setattr(users, "create_redis_client", lambda: redis)
    websocket = AsyncMock()
    websocket.headers = {}
    from fastapi import WebSocketDisconnect

    websocket.receive_json.side_effect = WebSocketDisconnect()
    with pytest.raises(RuntimeError, match="cleanup failed"):
        asyncio.run(
            users.websocket_location_endpoint(
                websocket, access_token="token", token=None
            )
        )
    redis.aclose.assert_awaited_once()
