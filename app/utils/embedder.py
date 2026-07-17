import numpy as np
import faiss
from openai import OpenAI
import os
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
import tiktoken
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

def count_tokens(text: str) -> int:
    try:
        encoding = tiktoken.get_encoding('cl100k_base')
        return len(encoding.encode(text))
    except:
        return len(text) // 4

def _embed_batch(batch: list, batch_num: int) -> list:
    try:
        print(f'  ...sending batch {batch_num} ({len(batch)} chunks) for embedding.')
        response = get_openai_client().embeddings.create(input=batch, model='text-embedding-3-small')
        return [item.embedding for item in response.data]
    except Exception as e:
        print(f'Error embedding batch {batch_num}: {e}')
        return []

def create_safe_batches(chunks: list, max_tokens_per_batch: int=250000) -> list:
    batches = []
    current_batch = []
    current_tokens = 0
    for chunk in chunks:
        chunk_tokens = count_tokens(chunk)
        if current_tokens + chunk_tokens > max_tokens_per_batch and current_batch:
            batches.append(current_batch)
            current_batch = [chunk]
            current_tokens = chunk_tokens
        else:
            current_batch.append(chunk)
            current_tokens += chunk_tokens
    if current_batch:
        batches.append(current_batch)
    return batches

def embed_chunks(chunks: list) -> np.ndarray:
    batches = create_safe_batches(chunks, max_tokens_per_batch=250000)
    all_embeddings = [None] * len(chunks)
    print(f'Embedding {len(chunks)} chunks in {len(batches)} token-safe batches...')
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {}
        for i, batch in enumerate(batches):
            batch_num = i + 1
            future = executor.submit(_embed_batch, batch, batch_num)
            futures[future] = i
        for future in as_completed(futures):
            batch_index = futures[future]
            try:
                batch_embeddings = future.result()
                start_index = sum((len(batches[j]) for j in range(batch_index)))
                end_index = start_index + len(batch_embeddings)
                all_embeddings[start_index:end_index] = batch_embeddings
            except Exception as e:
                print(f'A batch failed to process: {e}')
    final_embeddings = [emb for emb in all_embeddings if emb is not None]
    print('Embedding complete.')
    return np.array(final_embeddings, dtype=np.float32)

def build_faiss_index(embeddings: np.ndarray):
    if embeddings.size == 0:
        return None
    dim = embeddings.shape[1]
    index = faiss.IndexFlatL2(dim)
    index.add(embeddings)
    return index