from fastapi import APIRouter
from app.api.v1 import auth_router, users_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(users_router)

