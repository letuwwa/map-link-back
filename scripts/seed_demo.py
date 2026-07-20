# ruff: noqa: E402
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.redis import create_sync_redis_client
from app.core.security import hash_password
from app.core.user_cache import try_cache_user
from app.db.session import SessionLocal
from app.api.v1.reports import REPORTS_LOCATIONS_KEY, _cache_report
from app.api.v1.schemas import ReportRead
from app.api.v1.users import USERS_LOCATIONS_KEY
from app.db.models import (
    User,
    Report,
    Message,
    UserRole,
    ReportType,
    UserSetting,
    Conversation,
    MessageType,
    ConversationType,
    ConversationMember,
)


DEMO_PASSWORD = "password123456"


@dataclass(frozen=True)
class DemoUser:
    username: str
    email: str
    first_name: str
    last_name: str
    allow_incoming_messages: bool = True
    hide_me: bool = False


DEMO_USERS = [
    DemoUser(
        username="driver1",
        email="driver1@example.com",
        first_name="Demo",
        last_name="Driver One",
    ),
    DemoUser(
        username="driver2",
        email="driver2@example.com",
        first_name="Demo",
        last_name="Driver Two",
    ),
    DemoUser(
        username="reporter",
        email="reporter@example.com",
        first_name="Road",
        last_name="Reporter",
    ),
    DemoUser(
        username="no_messages_user",
        email="no-messages@example.com",
        first_name="No",
        last_name="Messages",
        allow_incoming_messages=False,
    ),
    DemoUser(
        username="hidden_user",
        email="hidden@example.com",
        first_name="Hidden",
        last_name="User",
        hide_me=True,
    ),
]

DEMO_REPORTS = [
    (ReportType.ROAD_DANGER, 32.08530, 34.78180, "driver1"),
    (ReportType.TRAFFIC_JAM, 32.08565, 34.78210, "driver2"),
    (ReportType.CAR_ACCIDENT, 32.08495, 34.78145, "reporter"),
    (ReportType.POLICE, 32.08510, 34.78255, "driver1"),
    (ReportType.CONSTRUCTION, 32.08585, 34.78125, "reporter"),
    (ReportType.SPEED_CAMERA, 32.08470, 34.78200, "driver2"),
]

DEMO_LOCATIONS = {
    "driver1": (32.08530, 34.78180),
    "driver2": (32.08565, 34.78210),
    "reporter": (32.08495, 34.78145),
    "no_messages_user": (32.08545, 34.78155),
    "hidden_user": (32.08575, 34.78235),
}

DEMO_CONVERSATIONS = [
    (
        "driver1",
        "driver2",
        [
            ("driver1", "I see traffic building near the junction."),
            ("driver2", "Thanks, I will take the side road."),
            ("driver1", "Road danger report is already on the map."),
        ],
    ),
    (
        "driver1",
        "reporter",
        [
            ("reporter", "Construction crew is blocking the right lane."),
            ("driver1", "Got it. I am nearby and slowing down."),
        ],
    ),
]


def main() -> None:
    db = SessionLocal()
    try:
        users = seed_users(db)
        clear_demo_data(db, users)
        reports = seed_reports(db, users)
        seed_conversations(db, users)
        db.commit()
        clear_demo_map_cache()
        cache_demo_users(db, users)
        cache_demo_reports(reports)
        cache_demo_user_locations(users)
        print_summary()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def seed_users(db: Session) -> dict[str, User]:
    users = {}
    for demo_user in DEMO_USERS:
        user = db.scalar(select(User).where(User.username == demo_user.username))
        if user is None:
            user = User(
                email=demo_user.email,
                username=demo_user.username,
                first_name=demo_user.first_name,
                last_name=demo_user.last_name,
                hashed_password=hash_password(DEMO_PASSWORD),
                role=UserRole.REGULAR,
                is_active=True,
            )
            db.add(user)
            db.flush()
        else:
            user.email = demo_user.email
            user.first_name = demo_user.first_name
            user.last_name = demo_user.last_name
            user.hashed_password = hash_password(DEMO_PASSWORD)
            user.is_active = True

        user_settings = db.scalar(
            select(UserSetting).where(UserSetting.user_id == user.id)
        )
        if user_settings is None:
            user_settings = UserSetting(user_id=user.id)
            db.add(user_settings)

        user_settings.allow_incoming_messages = demo_user.allow_incoming_messages
        user_settings.hide_me = demo_user.hide_me
        users[demo_user.username] = user

    db.flush()
    return users


def clear_demo_data(db: Session, users: dict[str, User]) -> None:
    user_ids = [user.id for user in users.values()]
    conversation_ids = db.scalars(
        select(ConversationMember.conversation_id).where(
            ConversationMember.user_id.in_(user_ids)
        )
    ).all()

    if conversation_ids:
        db.execute(delete(Conversation).where(Conversation.id.in_(conversation_ids)))

    db.execute(delete(Report).where(Report.user_id.in_(user_ids)))
    db.flush()


def seed_reports(db: Session, users: dict[str, User]) -> list[Report]:
    reports = []
    for report_type, latitude, longitude, username in DEMO_REPORTS:
        report = Report(
            user_id=users[username].id,
            report_type=report_type,
            latitude=latitude,
            longitude=longitude,
        )
        db.add(report)
        reports.append(report)

    db.flush()
    return reports


def seed_conversations(db: Session, users: dict[str, User]) -> None:
    for username, other_username, message_specs in DEMO_CONVERSATIONS:
        conversation = Conversation(conversation_type=ConversationType.DIRECT)
        db.add(conversation)
        db.flush()

        members = [
            ConversationMember(
                conversation_id=conversation.id,
                user_id=users[username].id,
            ),
            ConversationMember(
                conversation_id=conversation.id,
                user_id=users[other_username].id,
            ),
        ]
        db.add_all(members)
        db.flush()

        last_message = None
        for sender_username, body in message_specs:
            last_message = Message(
                conversation_id=conversation.id,
                sender_id=users[sender_username].id,
                message_type=MessageType.TEXT,
                body=body,
            )
            db.add(last_message)

        conversation.updated_at = datetime.now(timezone.utc)
        if last_message is not None:
            members[0].last_read_message_id = last_message.id

    db.flush()


def cache_demo_users(db: Session, users: dict[str, User]) -> None:
    for user in users.values():
        try_cache_user(db, user)


def cache_demo_reports(reports: list[Report]) -> None:
    for report in reports:
        _cache_report(ReportRead.model_validate(report))


def clear_demo_map_cache() -> None:
    redis_client = create_sync_redis_client()
    try:
        report_keys = list(redis_client.scan_iter("reports:*"))
        if report_keys:
            redis_client.delete(*report_keys)

        redis_client.delete(REPORTS_LOCATIONS_KEY)
        redis_client.delete(USERS_LOCATIONS_KEY)
    finally:
        redis_client.close()


def cache_demo_user_locations(users: dict[str, User]) -> None:
    redis_client = create_sync_redis_client()
    try:
        for demo_user in DEMO_USERS:
            if demo_user.hide_me:
                continue

            latitude, longitude = DEMO_LOCATIONS[demo_user.username]
            redis_client.geoadd(
                USERS_LOCATIONS_KEY,
                (longitude, latitude, str(users[demo_user.username].id)),
            )
    finally:
        redis_client.close()


def print_summary() -> None:
    print("Demo data created.")
    print("")
    print("Accounts:")
    for demo_user in DEMO_USERS:
        flags = []
        if not demo_user.allow_incoming_messages:
            flags.append("messages disabled")
        if demo_user.hide_me:
            flags.append("hidden on map")
        suffix = f" ({', '.join(flags)})" if flags else ""
        print(f"- {demo_user.username} / {DEMO_PASSWORD}{suffix}")

    print("")
    print("Suggested browser geolocation overrides:")
    for username, (latitude, longitude) in DEMO_LOCATIONS.items():
        print(f"- {username}: {latitude:.5f}, {longitude:.5f}")


if __name__ == "__main__":
    main()
