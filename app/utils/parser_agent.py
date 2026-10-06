import os
import logging
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("app.parser_agent")

openai_client = None


def get_openai_client() -> OpenAI | None:
    global openai_client
    if openai_client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return None
        openai_client = OpenAI(api_key=api_key)
    return openai_client


def generate_step_back_query(original_query: str) -> str:
    """Generate a higher-level step-back query via OpenAI gpt-4o-mini to broaden retrieval."""
    client = get_openai_client()
    if not client:
        return original_query

    prompt = (
        "You are an AI assistant tasked with generating broader, more general queries to improve context retrieval in a RAG system.\n"
        "Given the original query, generate a step-back query that is more general and helps retrieve relevant background information.\n\n"
        f"Original question: {original_query}\n\n"
        "Return ONLY the step-back query, nothing else."
    )
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=80,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.warning(
            "Error generating step-back query with OpenAI (%s). Falling back to original query.",
            e,
        )
        return original_query


def parse_query_with_llm(question: str) -> str:
    return question