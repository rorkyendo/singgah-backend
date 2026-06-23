import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes import chat_route, user_route
from app.db.base import Base
from app.db.session import engine
import app.models.saved_property  # noqa: F401 — registers table with Base.metadata

Base.metadata.create_all(bind=engine)

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    from app.agents._browser import close_browser
    await close_browser()

app = FastAPI(title="Singgah SmartAdvisor API", lifespan=lifespan)

def _parse_cors_origins():
    raw = settings.CORS_ORIGINS.strip()
    if raw == "*":
        return ["*"]
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_parse_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_route.router)
app.include_router(user_route.router)

@app.get("/")
def root():
    return {"message": "Singgah SmartAdvisor API is running"}
