from fastapi import APIRouter
from pydantic import BaseModel
from app.pipeline import run_pipeline  # all phases wrapped here

router = APIRouter()

class AskRequest(BaseModel):
    documents: str
    questions: list[str]
@router.get("/")
def read_root():
    return {"msg": "FastAPI on Render working!"}
@router.post("/api/v1/hackrx/run")
async def ask_policy_questions(req: AskRequest):
    result = run_pipeline(req.documents, req.questions)
    return result

