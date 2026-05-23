from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import router

def create_app() -> FastAPI:
    app = FastAPI(title="PatchSorter Tile Server", version="1.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    app.include_router(router, prefix="/agg")

    # Global session managers are lazily constructed by the package getters
    # (get_head_session_manager / get_worker_session_manager) when needed.

    return app


app = create_app()
