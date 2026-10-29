import os
from unittest.mock import MagicMock

# Explicit test configuration: never load developer credentials or services.
os.environ.update(
    POSTGRES_HOST="localhost",
    POSTGRES_USER="test",
    POSTGRES_PASSWORD="test",
    POSTGRES_DB="test",
    JWT_SECRET_KEY="test-only-secret-with-at-least-32-bytes",
)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core import user_cache
from app.db.deps import get_db
from app.db.models.base_model import BaseModel
from app.main import app


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    BaseModel.metadata.create_all(engine)
    with Session(engine, autoflush=False) as session:
        yield session
    engine.dispose()


@pytest.fixture
def redis_client(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(user_cache, "create_sync_redis_client", lambda: client)
    from app.api.v1 import reports

    monkeypatch.setattr(reports, "create_sync_redis_client", lambda: client)
    return client


@pytest.fixture
def client(db, redis_client, monkeypatch):
    from app.api.v1 import users

    monkeypatch.setattr(
        users, "SessionLocal", lambda: Session(db.bind, autoflush=False)
    )
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def register(client):
    def create(username="driver"):
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": f"{username}@example.com",
                "username": username,
                "first_name": "Test",
                "last_name": "Driver",
                "password": "password123",
            },
        )
        assert response.status_code == 201, response.text
        return response.json()

    return create
