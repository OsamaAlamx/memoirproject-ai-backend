# src/main.py
import sys
from dotenv import load_dotenv

# Windows consoles default to cp1252: any print with emoji/CJK (chapter
# service LLM warnings, etc.) crashed the request with UnicodeEncodeError.
# Replace unencodable chars instead of blowing up the whole response.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

load_dotenv()
from src.core.config import settings
from src.core.app_lifespan import lifespan
from src.core.logging_config import setup_logging

setup_logging()
from src.api.share import owner_router, reader_router

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from postgrest.exceptions import APIError as PostgrestAPIError
from starlette.middleware.base import BaseHTTPMiddleware


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds baseline security headers (SEC-H4) to every response."""

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; frame-ancestors 'none'; object-src 'none'",
        )
        return response

# Import modular feature routers
from src.api.media import router as media_router
from src.api.memoir import router as memoir_router
from src.api.memory import router as memory_router
from src.api.auth import router as auth_router
from src.api.comments import router as comment_router
from src.api.search import router as search_router
from src.api.export import router as export_router
from src.api.transcripts import router as transcript_router
from src.api.chapters import router as chapter_router

app = FastAPI(
    title="Memoir App API",
    version="1.0.0",
    description="Backend API services for the Memoir life-story documentation platform.",
    lifespan=lifespan
)

origins = settings.cors_origins
if isinstance(origins, str):
    origins = [o.strip() for o in origins.split(",") if o.strip()]

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)

@app.get("/", tags=["Root"])
def read_root():
    return {"message": "Welcome to the Memoir App API"}

@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "healthy"}


@app.exception_handler(PostgrestAPIError)
async def postgrest_api_error_handler(request: Request, exc: PostgrestAPIError):
    """Malformed UUIDs reach PostgREST as code 22P02 (`invalid input syntax
    for type uuid`). That is a client error, not a 500: answer 422 so bad
    ids fail cleanly on every route without per-endpoint validation."""
    code = (exc.code or "") if hasattr(exc, "code") else ""
    if code == "22P02":
        return JSONResponse(status_code=422, content={"detail": "Invalid ID format: expected UUID."})
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})

app.include_router(auth_router)
app.include_router(memoir_router)
app.include_router(memory_router)
app.include_router(media_router)
app.include_router(comment_router)
app.include_router(search_router)
app.include_router(export_router)
app.include_router(transcript_router)
app.include_router(owner_router)
app.include_router(reader_router)
app.include_router(chapter_router)