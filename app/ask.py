import os
import tempfile
from typing import Optional
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
import requests
from app.pipeline import run_pipeline
from app.celery_app import get_celery_app
from app.tasks import process_document, answer_questions
from app.utils.document_parser import DocumentParser
router = APIRouter()
celery_app = get_celery_app()

class AskRequest(BaseModel):
    documents: str
    questions: list[str]

class DocumentUploadRequest(BaseModel):
    document_url: str = Field(..., description='URL or local path to document')

    class Config:
        json_schema_extra = {'example': {'document_url': 'https://example.com/policy.pdf'}}

class DocumentUploadResponse(BaseModel):
    job_id: str = Field(..., description='Celery task ID for tracking progress')
    status: str = Field(default='pending', description='Initial status')
    document_url: str

    class Config:
        json_schema_extra = {'example': {'job_id': 'a1b2c3d4-e5f6-7890-abcd-ef1234567890', 'status': 'pending', 'document_url': 'https://example.com/policy.pdf'}}

class JobStatus(BaseModel):
    job_id: str
    status: str = Field(..., description='PENDING, STARTED, SUCCESS, FAILURE, or RETRY')
    result: Optional[dict] = Field(default=None, description='Result payload if status is SUCCESS')
    error: Optional[str] = Field(default=None, description='Error message if status is FAILURE')
    progress: Optional[dict] = Field(default=None, description='Progress details (stage, %) if STARTED')

    class Config:
        json_schema_extra = {'example': {'job_id': 'a1b2c3d4-e5f6-7890-abcd-ef1234567890', 'status': 'SUCCESS', 'result': {'status': 'success', 'doc_hash': 'abc123...', 'chunks_count': 42, 'chunks_file': '/path/to/chunks.json', 'index_file': '/path/to/index.faiss', 'cached': False}}}

@router.get('/')
def read_root():
    return {'msg': 'FastAPI on Render working!'}

@router.post('/api/v1/hackrx/run')
async def ask_policy_questions(req: AskRequest):
    result = run_pipeline(req.documents, req.questions)
    return result

@router.post('/api/v1/hackrx/upload', response_model=DocumentUploadResponse)
async def upload_document(req: DocumentUploadRequest) -> DocumentUploadResponse:
    try:
        parser = DocumentParser()
        logger_info = f'Downloading document from {req.document_url}'
        print(logger_info)
        file_path = parser.download_file(req.document_url)
        if not os.path.exists(file_path):
            raise HTTPException(status_code=400, detail=f'Failed to download document from {req.document_url}')
        task = process_document.delay(file_path, req.document_url)
        return DocumentUploadResponse(job_id=task.id, status='pending', document_url=req.document_url)
    except Exception as e:
        print(f'Error uploading document: {str(e)}')
        raise HTTPException(status_code=500, detail=f'Error uploading document: {str(e)}')

@router.get('/api/v1/hackrx/jobs/{job_id}/status', response_model=JobStatus)
async def get_job_status(job_id: str) -> JobStatus:
    try:
        task_result = celery_app.AsyncResult(job_id)
        status = task_result.status
        result = None
        error = None
        progress = None
        if status == 'SUCCESS':
            result = task_result.result
        elif status == 'FAILURE':
            error = str(task_result.info)
        elif status == 'STARTED' or status == 'PROGRESS':
            if hasattr(task_result, 'info') and isinstance(task_result.info, dict):
                progress = task_result.info
        return JobStatus(job_id=job_id, status=status, result=result, error=error, progress=progress)
    except Exception as e:
        print(f'Error getting job status: {str(e)}')
        raise HTTPException(status_code=500, detail=f'Error retrieving job status: {str(e)}')