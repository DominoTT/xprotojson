from fastapi import APIRouter

from .endpoints import health, data

api_v1_router = APIRouter()     
api_v1_router.include_router(health.router, tags=["健康检查"])
api_v1_router.include_router(data.router, prefix="/data", tags=["数据接口"])
