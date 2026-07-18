import os
import logging
from typing import Optional

import redis as redis_lib
from fastapi import APIRouter, Depends, HTTPException

from pydantic import BaseModel, Field

from app.pipeline import run_pipeline
from app.celery_app import get_celery_app
from app.tasks import process_document, answer_questions
from app.utils.document_parser import DocumentParser
from app.auth.jwt import get_current_user
from app.auth.models import AuthUser
from app.auth.supabase_client import upsert_user_profile

logger     = logging.getLogger("app.ask")
router     = APIRouter()
celery_app = get_celery_app()

# ── Redis client for job ownership ────────────────────────────────────────────
# Reuses the same Redis instance as Celery / rate-limiter.
_REDIS_URL   = os.getenv("REDIS_URL", "redis://localhost:6379/0")
_JOB_TTL_S   = 86_400   # 24 h — matches Celery result_expires

_redis: redis_lib.Redis | None = None


def _get_redis() -> redis_lib.Redis:
    global _redis
    if _redis is None:
        _redis = redis_lib.from_url(
            _REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    return _redis


def _set_job_owner(job_id: str, user_id: str) -> None:
    """Store owner_id alongside the Celery task so we can enforce ownership."""
    try:
        r = _get_redis()
        r.hset(f"job:{job_id}", mapping={"owner_id": user_id})
        r.expire(f"job:{job_id}", _JOB_TTL_S)
    except Exception as exc:
        # Non-fatal — worst case a job is orphaned and the owner check skips
        logger.warning(
            "Failed to set job owner in Redis",
            extra={"job_id": job_id, "user_id": user_id, "error": str(exc)},
        )


def _get_job_owner(job_id: str) -> Optional[str]:
    """Return the owner_id for a job, or None if the key has expired / never set."""
    try:
        r = _get_redis()
        return r.hget(f"job:{job_id}", "owner_id")
    except Exception as exc:
        logger.warning(
            "Failed to get job owner from Redis",
            extra={"job_id": job_id, "error": str(exc)},
        )
        return None


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class AskRequest(BaseModel):
    documents: str
    questions: list[str]


class DocumentUploadRequest(BaseModel):
    document_url: str = Field(..., description="URL or local path to document")

    class Config:
        json_schema_extra = {
            "example": {"document_url": "https://example.com/policy.pdf"}
        }


class DocumentUploadResponse(BaseModel):
    job_id:       str = Field(..., description="Celery task ID for tracking progress")
    status:       str = Field(default="pending", description="Initial status")
    document_url: str

    class Config:
        json_schema_extra = {
            "example": {
                "job_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                "status": "pending",
                "document_url": "https://example.com/policy.pdf",
            }
        }


class JobStatus(BaseModel):
    job_id:   str
    status:   str  = Field(..., description="PENDING, STARTED, SUCCESS, FAILURE, or RETRY")
    result:   Optional[dict] = Field(default=None, description="Result payload if SUCCESS")
    error:    Optional[str]  = Field(default=None, description="Error message if FAILURE")
    progress: Optional[dict] = Field(default=None, description="Progress details if STARTED")

    class Config:
        json_schema_extra = {
            "example": {
                "job_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                "status": "SUCCESS",
                "result": {
                    "status": "success",
                    "doc_hash": "abc123...",
                    "chunks_count": 42,
                    "chunks_file": "/path/to/chunks.json",
                    "index_file":  "/path/to/index.faiss",
                    "cached": False,
                },
            }
        }


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/")
def read_root():
    """Redirect browsers to the static login page."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/static/index.html")


@router.post("/api/v1/hackrx/run")
async def ask_policy_questions(
    req: AskRequest,
    user: AuthUser = Depends(get_current_user),
):
    """
    Synchronous RAG pipeline. Protected — requires a valid Supabase JWT.
    Upserts the user profile on first call (idempotent via ON CONFLICT DO NOTHING).
    """
    upsert_user_profile(user)
    logger.info(
        "RAG run requested",
        extra={"user_id": user.id, "questions": len(req.questions)},
    )
    result = run_pipeline(req.documents, req.questions)
    return result


@router.post("/api/v1/hackrx/upload", response_model=DocumentUploadResponse)
async def upload_document(
    req: DocumentUploadRequest,
    user: AuthUser = Depends(get_current_user),
) -> DocumentUploadResponse:
    """
    Async document ingestion. Protected — requires a valid Supabase JWT.
    Stores job ownership in Redis so only the submitting user can query status.
    """
    upsert_user_profile(user)
    try:
        parser = DocumentParser()
        logger.info(
            "Downloading document",
            extra={"document_url": req.document_url, "user_id": user.id},
        )
        file_path = parser.download_file(req.document_url)
        if not os.path.exists(file_path):
            raise HTTPException(
                status_code=400,
                detail=f"Failed to download document from {req.document_url}",
            )
        task = process_document.delay(file_path, req.document_url)

        # Record ownership before returning so the status endpoint can verify
        _set_job_owner(task.id, user.id)

        logger.info(
            "Document queued for ingestion",
            extra={"job_id": task.id, "document_url": req.document_url, "user_id": user.id},
        )
        return DocumentUploadResponse(
            job_id=task.id, status="pending", document_url=req.document_url
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Error uploading document",
            extra={"document_url": req.document_url, "user_id": user.id, "error": str(e)},
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail=f"Error uploading document: {str(e)}"
        )


@router.get("/api/v1/hackrx/jobs/{job_id}/status", response_model=JobStatus)
async def get_job_status(
    job_id: str,
    user: AuthUser = Depends(get_current_user),
) -> JobStatus:
    """
    Returns status for a Celery job.  Protected — requires a valid Supabase JWT.

    Returns 403 if the requesting user is not the job owner.
    Returns 404 if the job ownership record has expired (>24 h) — the user
    should re-submit if needed.
    """
    owner_id = _get_job_owner(job_id)

    if owner_id is None:
        # Ownership record expired or never written (e.g. pre-auth jobs)
        # Treat as not found rather than leaking that the job exists.
        raise HTTPException(status_code=404, detail="Job not found or has expired")

    if owner_id != user.id:
        logger.warning(
            "Job ownership mismatch",
            extra={"job_id": job_id, "owner": owner_id, "requester": user.id},
        )
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        task_result = celery_app.AsyncResult(job_id)
        status   = task_result.status
        result   = None
        error    = None
        progress = None

        if status == "SUCCESS":
            result = task_result.result
        elif status == "FAILURE":
            error = str(task_result.info)
        elif status in ("STARTED", "PROGRESS"):
            if hasattr(task_result, "info") and isinstance(task_result.info, dict):
                progress = task_result.info

        return JobStatus(
            job_id=job_id, status=status, result=result, error=error, progress=progress
        )
    except Exception as e:
        logger.error(
            "Error retrieving job status",
            extra={"job_id": job_id, "user_id": user.id, "error": str(e)},
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail=f"Error retrieving job status: {str(e)}"
        )