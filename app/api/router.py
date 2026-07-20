from fastapi import APIRouter
from app.api.v1 import auth_router, reports_router


api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(reports_router)
