import numpy as np
from openai import OpenAI
import os
from dotenv import load_dotenv
load_dotenv()
client = None

def get_openai_client():
    global client
    if client is None:
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            raise ValueError('OPENAI_API_KEY environment variable is not set')
        client = OpenAI(api_key=api_key)
    return client

def retrieve_relevant_chunks(question: str, chunks: list, index, embeddings: np.ndarray, top_k: int=3) -> list[str]:
    if index is None:
        print(f'[ERROR] FAISS index is None. Cannot perform search for question: {question}')
        return []
    response = get_openai_client().embeddings.create(input=[question], model='text-embedding-3-small')
    question_embedding = np.array([response.data[0].embedding], dtype=np.float32)
    distances, indices = index.search(question_embedding, top_k)
    relevant_chunks = [chunks[i] for i in indices[0]]
    return relevant_chunks