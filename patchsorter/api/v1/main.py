from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .confusion_matrix.routes import router as confusion_matrix_router
from .project.routes import router as project_router
from .label_class.routes import router as label_class_router
from .patch.routes import router as patch_router


def create_app() -> FastAPI:
    app = FastAPI(title="PatchSorter Tile Server", version="1.0.0", root_path="/api/v1")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    app.include_router(confusion_matrix_router)
    app.include_router(project_router)
    app.include_router(label_class_router)
    app.include_router(patch_router)

    # Global session managers are lazily constructed by the package getters
    # (get_head_session_manager / get_worker_session_manager) when needed.

    return app


app = create_app()
