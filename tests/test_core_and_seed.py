import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from redis.exceptions import ConnectionError
from sqlalchemy import func, select

from app.core import redis, security, user_cache
from app.db import deps
from app.db.models import (
    Conversation,
    ConversationMember,
    Message,
    Report,
    User,
    UserSetting,
)
from scripts import seed_demo


def test_password_hashing():
    hashed = security.hash_password("password123")
    assert hashed != "password123"
    assert security.verify_password("password123", hashed)
    assert not security.verify_password("wrong", hashed)


def test_cache_user_creates_defaults_and_closes_connection(db, register, redis_client):
    register()
    user = db.scalar(select(User))
    db.delete(db.scalar(select(UserSetting)))
    db.commit()
    result = user_cache.cache_user(db, user)
    assert result.hide_me is False
    assert result.allow_incoming_messages is True
    assert redis_client.set.call_args.args[0] == f"users:{user.id}"
    redis_client.set.side_effect = ConnectionError("offline")
    user_cache.try_cache_user_read(result)
    assert redis_client.close.call_count >= 3


def test_db_dependency_closes_on_error(monkeypatch):
    session = Mock()
    monkeypatch.setattr(deps, "SessionLocal", lambda: session)
    generator = deps.get_db()
    assert next(generator) is session
    with pytest.raises(RuntimeError):
        generator.throw(RuntimeError("failure"))
    session.close.assert_called_once()


def test_redis_factories_and_dependency_cleanup(monkeypatch):
    sync_type = Mock()
    async_type = Mock()
    client = AsyncMock()
    async_type.from_url.return_value = client
    monkeypatch.setattr(redis, "SyncRedis", sync_type)
    monkeypatch.setattr(redis, "Redis", async_type)
    assert redis.create_sync_redis_client() is sync_type.from_url.return_value
    assert redis.create_redis_client() is client
    assert async_type.from_url.call_args.kwargs["decode_responses"] is True
    for factory in (sync_type.from_url, async_type.from_url):
        assert factory.call_args.kwargs["socket_connect_timeout"] == 2
        assert factory.call_args.kwargs["socket_timeout"] == 2

    async def exercise():
        generator = redis.get_redis_client()
        assert await anext(generator) is client
        with pytest.raises(RuntimeError):
            await generator.athrow(RuntimeError("failure"))

    asyncio.run(exercise())
    client.aclose.assert_awaited_once()


def test_seed_repeatable_and_cascades(db, monkeypatch, redis_client, capsys):
    monkeypatch.setattr(seed_demo, "SessionLocal", lambda: db)
    monkeypatch.setattr(seed_demo, "create_sync_redis_client", lambda: redis_client)
    redis_client.scan_iter.return_value = ["reports:old"]
    seed_demo.main()
    first_ids = set(db.scalars(select(User.id)))
    seed_demo.main()
    assert set(db.scalars(select(User.id))) == first_ids
    assert db.scalar(select(func.count()).select_from(User)) == 5
    assert db.scalar(select(func.count()).select_from(Report)) == len(
        seed_demo.DEMO_REPORTS
    )
    assert db.scalar(select(func.count()).select_from(Conversation)) == len(
        seed_demo.DEMO_CONVERSATIONS
    )
    assert db.scalar(select(func.count()).select_from(Message)) == sum(
        len(specs) for _, _, specs in seed_demo.DEMO_CONVERSATIONS
    )
    assert db.scalar(select(func.count()).select_from(ConversationMember)) == 4
    output = capsys.readouterr().out
    assert "Demo data created." in output
    assert "hidden on map" in output
    assert "messages disabled" in output
    hidden = db.scalar(select(User).where(User.username == "hidden_user"))
    for call in redis_client.geoadd.call_args_list:
        if call.args[0] == "users_locations":
            assert call.args[1][2] != str(hidden.id)


def test_seed_failure_rolls_back_and_closes(monkeypatch):
    session = Mock()
    monkeypatch.setattr(seed_demo, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        seed_demo, "seed_users", Mock(side_effect=RuntimeError("seed failed"))
    )
    with pytest.raises(RuntimeError, match="seed failed"):
        seed_demo.main()
    session.rollback.assert_called_once()
    session.close.assert_called_once()


def test_cache_helpers_do_not_hide_programming_errors(db, register, redis_client):
    from app.api.v1 import reports
    from app.api.v1.schemas import ReportRead
    from datetime import datetime, timezone
    from uuid import uuid4
    from app.db.models import ReportType

    register()
    user = db.scalar(select(User))
    redis_client.set.side_effect = ValueError("programming error")
    with pytest.raises(ValueError, match="programming error"):
        user_cache.try_cache_user(db, user)
    report = ReportRead(
        id=uuid4(),
        user_id=user.id,
        report_type=ReportType.ROAD_DANGER,
        latitude=32,
        longitude=34,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    with pytest.raises(ValueError, match="programming error"):
        reports._try_cache_report(report)
    redis_client.delete.side_effect = ValueError("programming error")
    with pytest.raises(ValueError, match="programming error"):
        reports._try_delete_cached_report(report.id)
