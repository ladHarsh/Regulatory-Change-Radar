"""
main.py — FastAPI application entrypoint for Regulatory Change Radar.

Responsibilities:
  - Create the FastAPI application instance
  - Register all routers
  - Configure CORS
  - Initialize the database on startup
  - Expose a health check endpoint
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.config import get_settings
from app.db.session import init_db

settings = get_settings()


def _run_migrations() -> None:
    """
    Lightweight schema migrations for columns added after the initial release.
    Uses ALTER TABLE ... ADD COLUMN which is idempotent-safe via try/except.
    SQLite does not support IF NOT EXISTS for ADD COLUMN, so we catch the error.
    """
    from app.db.session import engine
    migrations = [
        # Original migrations
        "ALTER TABLE policy_documents ADD COLUMN policy_domain VARCHAR(100) DEFAULT ''",
        "ALTER TABLE policy_documents ADD COLUMN policy_domain_confidence FLOAT DEFAULT 0.0",
        # Pipeline v3: QueryLog extended fields
        "ALTER TABLE query_logs ADD COLUMN query_type VARCHAR(20)",
        "ALTER TABLE query_logs ADD COLUMN verified BOOLEAN",
        "ALTER TABLE query_logs ADD COLUMN stage_timings_json TEXT",
        "ALTER TABLE query_logs ADD COLUMN retrieval_confidence FLOAT",
        "ALTER TABLE query_logs ADD COLUMN reasoning_path VARCHAR(20)",
        "ALTER TABLE query_logs ADD COLUMN fallback_used BOOLEAN DEFAULT 0",
    ]
    with engine.connect() as conn:
        for sql in migrations:
            try:
                conn.execute(__import__("sqlalchemy").text(sql))
                conn.commit()
            except Exception:
                # Column already exists — safe to ignore
                pass
    logger.debug("Schema migrations complete")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Handles application startup and shutdown.
    On startup: creates the SQLite DB + tables, ensures data directories exist.
    """
    logger.info("🚀 Starting Regulatory Change Radar API")

    # Ensure data directories exist
    os.makedirs(settings.data_dir, exist_ok=True)
    os.makedirs(settings.chroma_dir, exist_ok=True)
    os.makedirs(os.path.join(settings.data_dir, "policies"), exist_ok=True)
    os.makedirs(os.path.join(settings.data_dir, "documents"), exist_ok=True)

    # Initialize SQLite database
    logger.info("Initializing database...")
    init_db()
    logger.info("✅ Database ready")

    # Run lightweight migrations for columns added after initial schema creation
    _run_migrations()

    # Self-healing: Ingest baseline documents in a background thread if the database is empty.
    # This ensures that even on Render free tier restarts where the ephemeral DB is wiped,
    # the server automatically repopulates itself with documents.
    from app.db.session import SessionLocal
    from app.db.models import Document
    import threading
    from app.ingestion.pipeline import run_ingestion_pipeline

    db = SessionLocal()
    try:
        doc_count = db.query(Document).count()
        if doc_count == 0:
            logger.info("Database is empty on startup. Triggering automatic baseline ingestion in a background thread...")
            # Run in a daemon thread so it doesn't block FastAPI startup
            thread = threading.Thread(
                target=run_ingestion_pipeline,
                kwargs={"regulators": ["RBI", "SEBI"], "max_docs": 5}
            )
            thread.daemon = True
            thread.start()
        else:
            logger.info(f"Database contains {doc_count} documents. Skipping auto-ingestion.")
    except Exception as e:
        logger.error(f"Error checking database for self-healing: {e}")
    finally:
        db.close()

    yield

    logger.info("👋 Shutting down Regulatory Change Radar API")


app = FastAPI(
    title="Regulatory Change Radar API",
    description=(
        "Production-grade RAG system for regulatory compliance monitoring. "
        "Tracks RBI, SEBI, and IRDAI circulars, detects clause-level changes, "
        "and generates plain-English impact summaries."
    ),
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ── CORS ─────────────────────────────────────────────────────────────────────
# In production, we allow all origins because the Vercel frontend domain may
# vary (preview deployments, custom domains, etc.). The backend is protected
# by the Groq API key requirement for sensitive operations.
_cors_origins = settings.cors_origins if settings.app_env != "production" else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=settings.app_env != "production",  # can't use credentials with wildcard
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
from app.api.documents import router as documents_router
from app.api.changes import router as changes_router
from app.api.query import router as query_router
from app.api.policy import router as policy_router
from app.api.bookmarks import router as bookmarks_router
from app.api.notifications import router as notifications_router
from app.api.search import router as search_router
from app.api.evaluation import router as evaluation_router

app.include_router(documents_router)
app.include_router(changes_router)
app.include_router(query_router)
app.include_router(policy_router)
app.include_router(bookmarks_router)
app.include_router(notifications_router)
app.include_router(search_router)
app.include_router(evaluation_router)


# ── Health Check ──────────────────────────────────────────────────────────────
@app.get("/health", tags=["health"])
def health_check():
    """
    Simple liveness probe.
    Returns 200 OK with version and config summary (no secrets).
    """
    return {
        "status": "healthy",
        "version": "2.0.0",
        "llm_provider": settings.llm_provider,
        "embedding_model": settings.embedding_model,
        "data_dir": settings.data_dir,
    }


@app.get("/", tags=["health"])
def root():
    """Root redirect hint."""
    return {
        "message": "Regulatory Change Radar API",
        "docs": "/docs",
        "health": "/health",
    }


# ── Debug Route ─────────────────────────────────────────────────────────────
@app.get("/api/debug/db", tags=["debug"])
def debug_db():
    """
    Exposes raw DB counts for troubleshooting production issues.
    """
    from app.db.session import SessionLocal
    from app.db.models import Document, DocumentVersion, DocumentChunk, ChangeRecord
    import os

    db = SessionLocal()
    try:
        doc_count = db.query(Document).count()
        ver_count = db.query(DocumentVersion).count()
        chunk_count = db.query(DocumentChunk).count()
        change_count = db.query(ChangeRecord).count()
        
        # Check files in data directory
        data_files = []
        if os.path.exists(settings.data_dir):
            for root, dirs, files in os.walk(settings.data_dir):
                for f in files[:20]: # cap at 20 files
                    data_files.append(os.path.join(root, f))
                    
        return {
            "sqlite_url": settings.sqlite_url,
            "data_dir": settings.data_dir,
            "chroma_dir": settings.chroma_dir,
            "documents_count": doc_count,
            "versions_count": ver_count,
            "chunks_count": chunk_count,
            "changes_count": change_count,
            "files_found": data_files[:20],
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        db.close()

