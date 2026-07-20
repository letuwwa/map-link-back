import json
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from fastapi import (
    status,
    Cookie,
    Query,
    APIRouter,
    WebSocket,
    HTTPException,
    WebSocketDisconnect,
)

from app.core import settings
from app.db.session import SessionLocal
from app.core.redis import create_redis_client
from app.core.user_cache import try_cache_user, user_cache_key
from app.core.security import decode_token, get_token_user
from app.api.v1.schemas import UserRead


router = APIRouter(prefix="/location", tags=["location"])
USERS_LOCATIONS_KEY = "users_locations"
REPORTS_LOCATIONS_KEY = "reports_locations"
NEARBY_RADIUS_KM = 5


class LocationMessage(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


def get_websocket_user(token: str | None) -> UserRead | None:
    if token is None:
        return None

    db = SessionLocal()
    try:
        payload = decode_token(token)
        user = get_token_user(db, payload, token_type="access")
        return try_cache_user(db, user)
    except HTTPException, ValueError:
        return None
    finally:
        db.close()


@router.websocket("/ws")
async def websocket_location_endpoint(
    websocket: WebSocket,
    access_token: str | None = Cookie(
        default=None,
        alias=settings.access_token_cookie_name,
    ),
    token: str | None = Query(default=None),
) -> None:
    await websocket.accept()

    user = get_websocket_user(access_token or token)
    if user is None:
        await websocket.send_json(
            {
                "type": "auth_error",
                "message": "Unauthorized",
            }
        )
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Unauthorized",
        )
        return

    user_id = str(user.id)
    redis_client = create_redis_client()

    try:
        while True:
            data = await websocket.receive_json()

            try:
                location = LocationMessage.model_validate(data)
            except ValidationError as exc:
                await websocket.send_json(
                    {
                        "type": "validation_error",
                        "errors": exc.errors(),
                    }
                )
                continue

            if user.hide_me:
                await redis_client.zrem(USERS_LOCATIONS_KEY, user_id)
            else:
                await redis_client.geoadd(
                    USERS_LOCATIONS_KEY,
                    (location.lng, location.lat, user_id),
                )

            users = await _get_nearby_users(
                redis_client=redis_client,
                user_id=user_id,
                location=location,
            )
            reports = await _get_nearby_reports(
                redis_client=redis_client,
                location=location,
            )

            await websocket.send_json(
                {
                    "type": "nearby_map_data",
                    "me": {
                        "user_id": user_id,
                        "lat": location.lat,
                        "lng": location.lng,
                        "allow_incoming_messages": user.allow_incoming_messages,
                        "hide_me": user.hide_me,
                    },
                    "users": users,
                    "reports": reports,
                }
            )

    except WebSocketDisconnect:
        return
    finally:
        await redis_client.zrem(USERS_LOCATIONS_KEY, user_id)
        await redis_client.aclose()


async def _get_nearby_users(
    redis_client: Any,
    user_id: str,
    location: LocationMessage,
) -> list[dict[str, Any]]:
    raw_locations = await redis_client.georadius(
        name=USERS_LOCATIONS_KEY,
        longitude=location.lng,
        latitude=location.lat,
        radius=NEARBY_RADIUS_KM,
        unit="km",
        withcoord=True,
    )

    users = []
    for member, coord in raw_locations:
        other_user_id = str(member)
        if other_user_id == user_id:
            continue

        users.append(
            {
                "user_id": other_user_id,
                "lng": coord[0],
                "lat": coord[1],
            }
        )

    cached_users = await _get_cached_users(
        redis_client, [user["user_id"] for user in users]
    )
    active_users = []
    for user in users:
        cached_user = cached_users.get(user["user_id"], {})
        if (
            "allow_incoming_messages" not in cached_user
            or "hide_me" not in cached_user
            or cached_user["hide_me"]
        ):
            await redis_client.zrem(USERS_LOCATIONS_KEY, user["user_id"])
            continue

        user["allow_incoming_messages"] = cached_user["allow_incoming_messages"]
        user["hide_me"] = cached_user["hide_me"]
        active_users.append(user)

    return active_users


async def _get_cached_users(
    redis_client: Any,
    user_ids: list[str],
) -> dict[str, dict[str, Any]]:
    if not user_ids:
        return {}

    raw_users = await redis_client.mget(
        [user_cache_key(user_id) for user_id in user_ids]
    )
    cached_users = {}
    for raw_user in raw_users:
        if raw_user is None:
            continue

        try:
            user = json.loads(raw_user)
        except json.JSONDecodeError:
            continue

        cached_user_id = user.get("id")
        if cached_user_id is not None:
            cached_users[str(cached_user_id)] = user

    return cached_users


async def _get_nearby_reports(
    redis_client: Any,
    location: LocationMessage,
) -> list[dict[str, Any]]:
    raw_locations = await redis_client.georadius(
        name=REPORTS_LOCATIONS_KEY,
        longitude=location.lng,
        latitude=location.lat,
        radius=NEARBY_RADIUS_KM,
        unit="km",
    )
    if not raw_locations:
        return []

    report_values = await redis_client.mget(raw_locations)
    reports = []
    stale_report_keys = []
    for report_key, report_value in zip(raw_locations, report_values, strict=True):
        if report_value is None:
            stale_report_keys.append(report_key)
            continue

        try:
            reports.append(json.loads(report_value))
        except json.JSONDecodeError:
            stale_report_keys.append(report_key)

    if stale_report_keys:
        await redis_client.zrem(REPORTS_LOCATIONS_KEY, *stale_report_keys)

    return reports
