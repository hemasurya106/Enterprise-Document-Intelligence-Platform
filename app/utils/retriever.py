import numpy as np
from openai import OpenAI
import os
from dotenv import load_dotenv
load_dotenv()

# OpenAI client will be initialized lazily
client = None

def get_openai_client():
    """Lazy initialization of OpenAI client"""
    global client
    if client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable is not set")
        client = OpenAI(api_key=api_key)
    return client

def retrieve_relevant_chunks(question: str, chunks: list, index, embeddings: np.ndarray, top_k: int = 3) -> list[str]:
    """
    Retrieve the most relevant chunks for a given question using FAISS search and OpenAI embedding.
    """
    if index is None:
        print(f"[ERROR] FAISS index is None. Cannot perform search for question: {question}")
        return []
    # Embed the question using OpenAI
    response = get_openai_client().embeddings.create(
        input=[question],
        model="text-embedding-3-small"
    )
    question_embedding = np.array([response.data[0].embedding], dtype=np.float32)  # shape: (1, dim)

    # Search the FAISS index
    distances, indices = index.search(question_embedding, top_k)

    # Return top_k most relevant chunks
    relevant_chunks = [chunks[i] for i in indices[0]]
    return relevant_chunks
