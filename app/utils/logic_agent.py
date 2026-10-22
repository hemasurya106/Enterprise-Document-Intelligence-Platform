import logging
import os
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("app.logic_agent")

openai_client = None
gemini_configured = False


def get_openai_client():
    global openai_client
    if openai_client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return None
        from openai import OpenAI
        openai_client = OpenAI(api_key=api_key)
    return openai_client


def configure_gemini() -> bool:
    global gemini_configured
    if not gemini_configured:
        api_key = os.getenv("GEMINI_AI_API_KEY")
        if api_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=api_key)
                gemini_configured = True
            except Exception as e:
                logger.warning("Failed to configure Google Gemini: %s", e)
                return False
    return gemini_configured


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

    # 1. Try OpenAI if API key configured
    oai_client = get_openai_client()
    if oai_client:
        try:
            response = oai_client.chat.completions.create(
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
            logger.warning("OpenAI response generation failed (%s), attempting Gemini fallback...", exc)

    # 2. Try Gemini if GEMINI_AI_API_KEY configured
    if configure_gemini():
        try:
            import google.generativeai as genai
            model = genai.GenerativeModel("gemini-1.5-flash")
            response = model.generate_content(prompt)
            if response and response.text:
                return response.text.strip()
        except Exception as exc:
            logger.warning("Gemini response generation failed: %s", exc)

    # 3. If neither key is available or both failed
    if not os.getenv("OPENAI_API_KEY") and not os.getenv("GEMINI_AI_API_KEY"):
        return (
            "[API Key Required]: Neither OPENAI_API_KEY nor GEMINI_AI_API_KEY is configured in your .env file. "
            "Please add an API key to the .env file in the project root to enable neural question synthesis."
        )

    return "Could not find relevant information in the document to answer the question."


def summarize_text(text: str, question: str) -> str:
    """
    Refine / summarize a RAG response into a concise answer.
    Gracefully falls back to raw text if already brief, if an error occurs, or if no API key is set.
    """
    if (
        not text
        or len(text.split()) < 35
        or text.startswith("Error")
        or text.startswith("[API Key")
        or "Could not find" in text
    ):
        return text

    prompt = (
        "You are an AI assistant tasked to refine an answer provided by the RAG system into a concise format.\n"
        "Preserve all key facts, numbers, dates, and names.\n\n"
        f"Question: {question}\n"
        f"Answer to summarize: {text}\n"
    )

    oai_client = get_openai_client()
    if oai_client:
        try:
            response = oai_client.chat.completions.create(
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