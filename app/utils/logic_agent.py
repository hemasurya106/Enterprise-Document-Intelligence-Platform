import os
from openai import OpenAI
import google.generativeai as genai
from dotenv import load_dotenv
load_dotenv()
openai_client = None

def get_openai_client():
    global openai_client
    if openai_client is None:
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            raise ValueError('OPENAI_API_KEY environment variable is not set')
        openai_client = OpenAI(api_key=api_key)
    return openai_client
gemini_configured = False

def configure_gemini():
    global gemini_configured
    if not gemini_configured:
        api_key = os.getenv('GEMINI_AI_API_KEY')
        if not api_key:
            raise ValueError('GEMINI_AI_API_KEY environment variable is not set')
        genai.configure(api_key=api_key)
        gemini_configured = True

def generate_response_with_context(question: str, context: str) -> str:
    prompt = f'\nUsing the following insurance context, answer the question accurately.\n\nContext:\n{context}\n\nQuestion: {question}\n\nRespond clearly and only with information **grounded in the context even though if the context states universal facts incorrectly.**\n**DO NOT ASSUME ANYTHING OTHER THAN THAT GIVEN IN THE CONTEXT"**\n'
    try:
        client = get_openai_client()
        response = client.chat.completions.create(model='gpt-4o-mini', messages=[{'role': 'user', 'content': prompt}], temperature=0)
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f'Error generating response from GPT: {str(e)}'

def summarize_text(text: str, question: str) -> str:
    prompt = f'\nYou are an AI assistant tasked to summarize a response provided by the RAG system to provide answer in a concise format.\nText: {text}\nQuestion: {question}\n'
    try:
        configure_gemini()
        model = genai.GenerativeModel('gemini-2.0-flash')
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        return f'Error summarizing text with Gemini: {str(e)}'