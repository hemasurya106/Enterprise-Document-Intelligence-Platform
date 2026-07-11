import os
from openai import OpenAI
import google.generativeai as genai
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# --- Client and Configuration Setup ---

# Lazy initialization for the OpenAI client
openai_client = None
def get_openai_client():
    """Lazy initialization of the OpenAI client."""
    global openai_client
    if openai_client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable is not set")
        openai_client = OpenAI(api_key=api_key)
    return openai_client

# Lazy configuration for the Gemini API
gemini_configured = False
def configure_gemini():
    """Lazy configuration of Gemini API."""
    global gemini_configured
    if not gemini_configured:
        api_key = os.getenv("GEMINI_AI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_AI_API_KEY environment variable is not set")
        genai.configure(api_key=api_key)
        gemini_configured = True

# --- Agent Functions ---

def generate_response_with_context(question: str, context: str) -> str:
    """
    Generate a response using gpt-4o-mini with provided context.
    """
    prompt = f"""
Using the following insurance context, answer the question accurately.

Context:
{context}

Question: {question}

Respond clearly and only with information **grounded in the context even though if the context states universal facts incorrectly.**
**DO NOT ASSUME ANYTHING OTHER THAN THAT GIVEN IN THE CONTEXT"**
"""
    try:
        client = get_openai_client()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Error generating response from GPT: {str(e)}"

def summarize_text(text: str, question: str) -> str:
    """
    Summarize text using the Gemini model (gemini-2.0-flash).
    """
    prompt = f"""
You are an AI assistant tasked to summarize a response provided by the RAG system to provide answer in a concise format.
Text: {text}
Question: {question}
"""
    try:
        configure_gemini()
        model = genai.GenerativeModel('gemini-2.0-flash')
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        return f"Error summarizing text with Gemini: {str(e)}"