import logging
import os

from openai import OpenAI
import google.generativeai as genai
from dotenv import load_dotenv

from app.utils.gemini_circuit_breaker import gemini_breaker

load_dotenv()
logger = logging.getLogger("app.logic_agent")

openai_client = None


def get_openai_client() -> OpenAI:
    global openai_client
    if openai_client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable is not set")
        openai_client = OpenAI(api_key=api_key)
    return openai_client


gemini_configured = False


def configure_gemini() -> None:
    """Retained for backward compatibility; not required when using OpenAI."""
    global gemini_configured
    if not gemini_configured:
        api_key = os.getenv("GEMINI_AI_API_KEY")
        if api_key and genai is not None:
            try:
                genai.configure(api_key=api_key)
                gemini_configured = True
            except Exception:
                pass


def generate_response_with_context(question: str, context: str) -> str:
    prompt = (
        "Using the following document context, answer the question accurately and concisely.\n\n"
        f"Context:\n{context}\n\n"
        f"Question: {question}\n\n"
        "Guidelines:\n"
        "- Respond clearly and ground all statements strictly in the provided context.\n"
        "- If universal facts are stated differently in the context, strictly adhere to the context.\n"
        "- Do NOT assume or hallucinate anything outside the provided context.\n"
        "- If the answer cannot be found in the context, respond: 'Could not find relevant information in the document to answer the question.'\n"
    )
    try:
        client = get_openai_client()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a precise, grounded document intelligence AI. "
                        "Answer questions accurately and directly based solely on the provided context."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0,
        )
        return response.choices[0].message.content.strip()
    except Exception as exc:
        logger.error(
            "Error generating response from OpenAI gpt-4o-mini",
            extra={"error": str(exc), "question": question[:120]},
            exc_info=True,
        )
        return f"Error generating response: {str(exc)}"


def summarize_text(text: str, question: str) -> str:
    """
    Refine / summarize a RAG response using OpenAI gpt-4o-mini into a concise answer.
    Gracefully falls back to raw text if already brief or if an error occurs.
    """
    if not text or len(text.split()) < 35 or text.startswith("Error") or "Could not find" in text:
        return text

    prompt = (
        "You are an AI assistant tasked to refine an answer provided by the RAG system into a concise format.\n"
        "Preserve all key facts, numbers, dates, and names.\n\n"
        f"Question: {question}\n"
        f"Answer to summarize: {text}\n"
    )
    try:
        client = get_openai_client()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You provide clear, direct, and concise summaries."},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            max_tokens=400,
        )
        return response.choices[0].message.content.strip()
    except Exception as exc:
        logger.warning("OpenAI summarize fallback (%s) — returning answer as-is", exc)
        return text