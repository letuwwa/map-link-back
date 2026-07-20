from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Cookie
from redis.asyncio import Redis
from app.core.security import decode_token, get_token_user
from app.db.deps import SessionLocal
from app.core.settings import settings
from app.core.redis import create_redis_client
router = APIRouter(prefix="/location", tags=["location"])

def get_websocket_user(token: str):
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
    redis_client=create_redis_client()

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

            raw_locations = await redis_client.georadius(
                name="users_locations",
                longitude=float(lng),
                latitude=float(lat),
                radius=5,        
                unit="km",       
                withcoord=True   
            )

            all_users_list = []
            for member, coord in raw_locations:
                other_user_id = member
                
                if other_user_id == user_id:
                    continue
                    
                all_users_list.append({
                    "user_id": other_user_id,
                    "lng": coord[0],  
                    "lat": coord[1]   
                })

            await websocket.send_json({
                "type": "nearby_locations",
                "users": all_users_list
            })

    except WebSocketDisconnect:
        print(f"User {user.username} stopped streaming.")
    
    finally:
        await redis_client.aclose()
        print(f"Redis connection closed for user {user_id}")

