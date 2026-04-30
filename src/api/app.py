"""Phase 7 — FastAPI application factory.

`app = create_app()` is the ASGI entry point served by uvicorn:

    ~/miniconda3/envs/bd-coldcall/python.exe -m uvicorn src.api.app:app --reload

Lifespan behavior:
  - Reads `ApiSettings` once (env-driven).
  - Unless `API_SKIP_WARMUP=1`, preloads the local Exaone LLM and the
    bge-m3 embedder in a worker thread so the first /runs request
    doesn't pay the 30s load cost.
  - Sets `app.state.exaone_loaded` / `embedder_loaded` flags for /healthz.

The warmup uses best-effort logging, not hard failure — if CUDA isn't
available (e.g. dev box without GPU), the endpoints still accept
requests and Exaone is lazily loaded on first use.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import anyio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.checkpoint import build_sqlite_checkpointer, close_checkpointer
from src.api.config import get_api_settings
from src.api.db import init_db
from src.api.routes import discovery as discovery_routes
from src.api.routes import health as health_routes
from src.api.routes import ingest as ingest_routes
from src.api.routes import rag as rag_routes
from src.api.routes import runs as runs_routes
from src.api.routes import targets as targets_routes


_LOGGER = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_api_settings()
    app.state.api_settings = settings
    app.state.warmup_skipped = settings.skip_warmup
    app.state.exaone_loaded = False
    app.state.embedder_loaded = False
    app.state.checkpointer = None

    try:
        app.state.checkpointer = build_sqlite_checkpointer(settings.checkpoint_db)
        _LOGGER.info(
            "lifespan: sqlite checkpointer ready at %s", settings.checkpoint_db
        )
    except Exception:
        _LOGGER.exception(
            "lifespan: sqlite checkpointer init failed — falling back to in-memory"
        )
        app.state.checkpointer = None

    try:
        init_db(settings.app_db)
        app.state.app_db_path = settings.app_db
        _LOGGER.info("lifespan: app db ready at %s", settings.app_db)
    except Exception:
        _LOGGER.exception("lifespan: app db init failed (continuing)")
        app.state.app_db_path = None

    try:
        from pathlib import Path

        from src.config.loader import PROJECT_ROOT, get_settings
        from src.rag.namespace import migrate_flat_layout

        rag_settings = get_settings().rag
        vs_root = Path(rag_settings.vectorstore_path)
        if not vs_root.is_absolute():
            vs_root = PROJECT_ROOT / vs_root
        cd_root = PROJECT_ROOT / "data" / "company_docs"
        report = migrate_flat_layout(
            vectorstore_root=vs_root, company_docs_root=cd_root
        )
        if any(v for k, v in report.items() if k != "errors"):
            _LOGGER.info("lifespan: namespace migration: %s", report)
    except Exception:
        _LOGGER.exception("lifespan: namespace migration failed (continuing)")

    if not settings.skip_warmup:
        try:
            from src.llm import local_exaone

            await anyio.to_thread.run_sync(local_exaone.load)
            app.state.exaone_loaded = True
            _LOGGER.info("lifespan: exaone loaded")
        except Exception:
            _LOGGER.exception("lifespan: exaone warmup failed (continuing)")

        try:
            from src.rag import embeddings

            await anyio.to_thread.run_sync(embeddings.get_embedder)
            app.state.embedder_loaded = True
            _LOGGER.info("lifespan: embedder loaded")
        except Exception:
            _LOGGER.exception("lifespan: embedder warmup failed (continuing)")

    try:
        yield
    finally:
        if app.state.checkpointer is not None:
            close_checkpointer(app.state.checkpointer)
            app.state.checkpointer = None


def create_app() -> FastAPI:
    settings = get_api_settings()

    app = FastAPI(
        title="BD Cold-Call Agent API",
        version="0.7.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    app.include_router(health_routes.router, tags=["health"])
    app.include_router(runs_routes.router, tags=["runs"])
    app.include_router(ingest_routes.router, tags=["ingest"])
    app.include_router(rag_routes.router, tags=["rag"])
    app.include_router(targets_routes.router, tags=["targets"])
    app.include_router(discovery_routes.router, tags=["discovery"])

    return app


app = create_app()
