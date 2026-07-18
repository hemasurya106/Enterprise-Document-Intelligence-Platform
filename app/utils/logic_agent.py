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
    global gemini_configured
    if not gemini_configured:
        api_key = os.getenv("GEMINI_AI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_AI_API_KEY environment variable is not set")
        genai.configure(api_key=api_key)
        gemini_configured = True


def generate_response_with_context(question: str, context: str) -> str:
    prompt = (
        "\nUsing the following insurance context, answer the question accurately.\n\n"
        f"Context:\n{context}\n\n"
        f"Question: {question}\n\n"
        "Respond clearly and only with information **grounded in the context even "
        "though if the context states universal facts incorrectly.**\n"
        '**DO NOT ASSUME ANYTHING OTHER THAN THAT GIVEN IN THE CONTEXT"**\n'
    )
    try:
        client = get_openai_client()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        return response.choices[0].message.content.strip()
    except Exception as exc:
        logger.error(
            "Error generating response from GPT",
            extra={"error": str(exc), "question": question[:120]},
            exc_info=True,
        )
        return f"Error generating response from GPT: {str(exc)}"


def summarize_text(text: str, question: str) -> str:
    """
    Summarise a RAG answer via Gemini.

    Protected by the circuit breaker — if Gemini is unavailable the raw
    ``text`` is returned as-is so callers always get *something* useful.
    """
    prompt = (
        "\nYou are an AI assistant tasked to summarize a response provided by "
        "the RAG system to provide answer in a concise format.\n"
        f"Text: {text}\n"
        f"Question: {question}\n"
    )
    try:
        configure_gemini()
        model    = genai.GenerativeModel("gemini-2.0-flash")
        response = gemini_breaker.call(model.generate_content, prompt)

        if response is None:
            logger.warning(
                "Gemini summarize unavailable (circuit breaker/timeout) — "
                "returning raw text",
                extra={"circuit_state": gemini_breaker.state},
            )
            return text  # graceful fallback: return the unsummarized answer

        return response.text.strip()
    except Exception as exc:
        logger.error(
            "Error summarizing text with Gemini",
            extra={"error": str(exc)},
            exc_info=True,
        )
        return f"Error summarizing text with Gemini: {str(exc)}"