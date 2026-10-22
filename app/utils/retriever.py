import os
import re
import numpy as np
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = None


def get_openai_client():
    global client
    if client is None:
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            return None
        client = OpenAI(api_key=api_key)
    return client


def retrieve_relevant_chunks(question: str, chunks: list, index, embeddings: np.ndarray, top_k: int = 3) -> list[str]:
    """
    Retrieve top_k most relevant chunks using FAISS cosine vector search when available,
    with an automatic, resilient BM25 / token-overlap keyword ranking fallback.
    """
    if not chunks:
        return []

    # 1. Try Vector Search via FAISS + OpenAI embedding if index and API key exist
    if index is not None and getattr(index, 'ntotal', 0) > 0:
        oai_client = get_openai_client()
        if oai_client:
            try:
                response = oai_client.embeddings.create(input=[question], model='text-embedding-3-small')
                question_embedding = np.array([response.data[0].embedding], dtype=np.float32)
                distances, indices = index.search(question_embedding, top_k)
                valid_chunks = [chunks[i] for i in indices[0] if 0 <= i < len(chunks)]
                if valid_chunks:
                    return valid_chunks
            except Exception as e:
                print(f'[WARN] Vector search failed ({e}), falling back to lexical search.')

    # 2. Resilient Keyword / Lexical overlap ranking fallback
    tokens = set(re.findall(r'\w+', question.lower()))
    stopwords = {
        'what', 'is', 'the', 'in', 'this', 'document', 'a', 'an', 'and', 'or',
        'for', 'to', 'of', 'explain', 'tell', 'me', 'how', 'are', 'which', 'who',
        'where', 'when', 'why', 'can', 'you', 'does', 'with', 'from', 'about'
    }
    query_terms = [t for t in tokens if t not in stopwords and len(t) > 2]
    if not query_terms:
        query_terms = [t for t in tokens if len(t) > 1] or list(tokens)

    scored = []
    for chunk in chunks:
        chunk_lower = chunk.lower()
        score = sum(chunk_lower.count(term) for term in query_terms)
        scored.append((score, chunk))

    scored.sort(key=lambda x: x[0], reverse=True)
    top_chunks = [c for score, c in scored[:top_k] if score > 0]

    # If no positive keyword matches or query is generic, grab the introductory chunks
    if not top_chunks:
        top_chunks = chunks[:min(top_k, len(chunks))]

    return top_chunks