from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Cookie
from redis.asyncio import Redis
from app.core.security import decode_token, get_token_user
from app.db.deps import SessionLocal
from app.core.settings import settings
router = APIRouter(prefix="/location", tags=["location"])

def get_websocket_user(token: str):
    """פונקציית האימות המצוינת שלך מהקוקיז (ללא שינוי)"""
    if not token: return None
    try:
        payload = decode_token(token)
        db = SessionLocal()
        user = get_token_user(db, payload, token_type="access")
        db.close()
        return user
    except Exception: return None


@router.websocket("/ws")
async def websocket_location_endpoint(websocket: WebSocket, access_token: str = Cookie(None)):
    user = get_websocket_user(access_token)
    if user is None:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    user_id = str(user.id)
    await websocket.accept()
    print(f"User {user.username} started streaming location.")

    try:
        while True:
            data = await websocket.receive_json()
            
            lat = data.get("lat") 
            lng = data.get("lng")  
            if lat is None or lng is None:
                continue

           
            await redis_client.geoadd(
                "users_locations", 
                (float(lng), float(lat), user_id)
            )

            print(f"Updated location for User {user_id}: Lat {lat}, Lng {lng}")

    except WebSocketDisconnect:
        
        print(f"User {user.username} stopped streaming.")
