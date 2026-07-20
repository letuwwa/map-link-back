import json
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from fastapi import (
    status,
    Cookie,
    APIRouter,
    WebSocket,
    HTTPException,
    WebSocketDisconnect,
)

from app.core import settings
from app.db.models import User
from app.db.session import SessionLocal
from app.core.redis import create_redis_client
from app.core.security import decode_token, get_token_user


router = APIRouter(prefix="/location", tags=["location"])
USERS_LOCATIONS_KEY = "users_locations"
REPORTS_LOCATIONS_KEY = "reports_locations"
NEARBY_RADIUS_KM = 5


class LocationMessage(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


def get_websocket_user(token: str | None) -> User | None:
    if token is None:
        return None

    db = SessionLocal()
    try:
        payload = decode_token(token)
        return get_token_user(db, payload, token_type="access")
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
) -> None:
    user = get_websocket_user(access_token)
    if user is None:
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Unauthorized",
        )
        return

    user_id = str(user.id)
    await websocket.accept()
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
                    },
                    "users": users,
                    "reports": reports,
                }
            )

    except WebSocketDisconnect:
        return
    finally:
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

    return users


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
    return [
        json.loads(report_value)
        for report_value in report_values
        if report_value is not None
    ]
