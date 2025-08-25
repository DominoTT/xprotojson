from fastapi import FastAPI
from app.clients.feishu import FeishuClient

from app.core.config import settings
from app.api.v1.router import api_v1_router

app = FastAPI(title=settings.app_name)

app.include_router(api_v1_router, prefix="/api/v1")


@app.get("/")
def read_root():
	return {"message": "Hello from app.main"}


@app.on_event("startup")
def startup() -> None:
	app.state.feishu = FeishuClient()
