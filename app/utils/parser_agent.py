import os
import google.generativeai as genai
from dotenv import load_dotenv
load_dotenv()
try:
    api_key = os.getenv('GEMINI_AI_API_KEY')
    if api_key:
        genai.configure(api_key=api_key)
    else:
        print('Warning: GEMINI_AI_API_KEY not found in .env file.')
except Exception as e:
    print(f'Error configuring Gemini: {e}')
try:
    STEP_BACK_MODEL = genai.GenerativeModel('gemini-2.0-flash')
except Exception as e:
    print(f'Error initializing Gemini model: {e}')
    STEP_BACK_MODEL = None

def generate_step_back_query(original_query: str) -> str:
    if not STEP_BACK_MODEL:
        print('Step-back model not initialized. Falling back to original query.')
        return original_query
    prompt = f'\nYou are an AI assistant tasked with generating broader, more general queries to improve context retrieval in a RAG system.\nGiven the original query, generate a step-back query that is more general and can help retrieve relevant background information.\n\nOriginal question: {original_query}\n\nStep-back question:\n'
    try:
        response = STEP_BACK_MODEL.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        print(f'Error generating step-back query with Gemini: {e}. Falling back to original query.')
        return original_query

def parse_query_with_llm(question: str) -> str:
    return question