from sqlalchemy.orm import Session
from collections.abc import Generator
from app.db.session import SessionLocal


def get_db() -> Generator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
