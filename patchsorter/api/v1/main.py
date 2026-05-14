from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from patchsorter.api.v1.routes import router


def create_app() -> FastAPI:
    app = FastAPI(title="PatchSorter Tile Server", version="1.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    app.include_router(router)

    return app


app = create_app()
