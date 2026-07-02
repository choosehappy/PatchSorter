import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .confusion_matrix.routes import router as confusion_matrix_router
from .export.routes import router as export_router
from .image.routes import router as image_router
from .label_class.routes import router as label_class_router
from .patch.routes import router as patch_router
from .project.routes import router as project_router
from .settings.routes import router as settings_router
from .upload.routes import router as upload_router

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize Ray and start the upload-session GC thread.
    # Both steps are wrapped in try/except so the server starts even when
    # no Ray cluster is available (e.g. in CI or lightweight dev environments).
    try:
        import ray

        if not ray.is_initialized():
            ray.init(ignore_reinit_error=True)

        from .upload.gc import start_gc_thread

        start_gc_thread()
    except Exception as exc:
        log.warning("Ray initialization skipped — upload sessions will not be available: %s", exc)

    yield
    # Shutdown: GC thread is daemon=True and dies with the process; nothing to clean up.


def create_app() -> FastAPI:
    app = FastAPI(
        title="PatchSorter Tile Server",
        version="1.0.0",
        root_path="/api/v1",
        lifespan=lifespan,
    )

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
    app.include_router(settings_router)
    app.include_router(image_router)
    app.include_router(export_router)
    app.include_router(upload_router)

    # Global session managers are lazily constructed by the package getters
    # (get_head_session_manager / get_worker_session_manager) when needed.

    return app


app = create_app()
