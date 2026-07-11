import os
import google.generativeai as genai
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure the Gemini API key
# This will be used by the model initialized below.
try:
    api_key = os.getenv("GEMINI_AI_API_KEY")
    if api_key:
        genai.configure(api_key=api_key)
    else:
        print("Warning: GEMINI_AI_API_KEY not found in .env file.")
except Exception as e:
    print(f"Error configuring Gemini: {e}")


# Create a single, reusable instance of the model for efficiency.
# We use gemini-1.5-flash-latest for a good balance of speed and reasoning.
try:
    STEP_BACK_MODEL = genai.GenerativeModel('gemini-2.0-flash')
except Exception as e:
    print(f"Error initializing Gemini model: {e}")
    STEP_BACK_MODEL = None


def generate_step_back_query(original_query: str) -> str:
    """
    Generates a step-back query from the original user question using a Gemini model.
    """
    if not STEP_BACK_MODEL:
        print("Step-back model not initialized. Falling back to original query.")
        return original_query

    # This prompt is specifically designed for Gemini's instruction-following capabilities.
    prompt = f"""
You are an AI assistant tasked with generating broader, more general queries to improve context retrieval in a RAG system.
Given the original query, generate a step-back query that is more general and can help retrieve relevant background information.

Original question: {original_query}

Step-back question:
"""

    try:
        # Generate content using the configured Gemini model
        response = STEP_BACK_MODEL.generate_content(prompt)
        # Return the generated text, stripping any leading/trailing whitespace
        return response.text.strip()
    except Exception as e:
        print(f"Error generating step-back query with Gemini: {e}. Falling back to original query.")
        # If the API call fails, return the original query to ensure the pipeline continues
        return original_query

# You can keep your original query refinement function if you still need it elsewhere,
# or remove it if it's no longer used. For completeness, I'll include a placeholder for it.

def parse_query_with_llm(question: str) -> str:
    """
    This function can remain if you need simple query refinement elsewhere,
    or it can be removed if the step-back query is the only transformation needed.
    For now, it will just pass the question through.
    """
    # This is where your original Gemini-based query refinement logic would go.
    # For this example, we'll just return the question as-is.
    return question
