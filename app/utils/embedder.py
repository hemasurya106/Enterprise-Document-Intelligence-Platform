import numpy as np
import faiss
from openai import OpenAI
import os
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
import tiktoken

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

def count_tokens(text: str) -> int:
    """Count tokens in text using tiktoken"""
    try:
        encoding = tiktoken.get_encoding("cl100k_base")  # OpenAI's encoding
        return len(encoding.encode(text))
    except:
        # Fallback: rough estimate (1 token ≈ 4 characters)
        return len(text) // 4

def _embed_batch(batch: list, batch_num: int) -> list:
    """
    Private helper function to embed a single batch of text chunks.
    This function is designed to be called by a thread pool executor.
    """
    try:
        print(f"  ...sending batch {batch_num} ({len(batch)} chunks) for embedding.")
        response = get_openai_client().embeddings.create(
            input=batch,
            model="text-embedding-3-small"
        )
        return [item.embedding for item in response.data]
    except Exception as e:
        print(f"Error embedding batch {batch_num}: {e}")
        return []

def create_safe_batches(chunks: list, max_tokens_per_batch: int = 250000) -> list:
    """
    Create batches that respect token limits.
    """
    batches = []
    current_batch = []
    current_tokens = 0
    
    for chunk in chunks:
        chunk_tokens = count_tokens(chunk)
        
        # If adding this chunk would exceed the limit, start a new batch
        if current_tokens + chunk_tokens > max_tokens_per_batch and current_batch:
            batches.append(current_batch)
            current_batch = [chunk]
            current_tokens = chunk_tokens
        else:
            current_batch.append(chunk)
            current_tokens += chunk_tokens
    
    # Add the last batch if it has content
    if current_batch:
        batches.append(current_batch)
    
    return batches

def embed_chunks(chunks: list) -> np.ndarray:
    """
    Convert text chunks into dense vectors using OpenAI embeddings.
    This version processes chunks in parallel batches to maximize speed
    and avoid API token limits.
    """
    # Create safe batches based on token count rather than chunk count
    batches = create_safe_batches(chunks, max_tokens_per_batch=250000)
    all_embeddings = [None] * len(chunks) # Pre-allocate list for ordered results

    print(f"Embedding {len(chunks)} chunks in {len(batches)} token-safe batches...")

    with ThreadPoolExecutor(max_workers=4) as executor:  # Reduced workers to avoid rate limits
        # Create a list of futures, keeping track of the original index
        futures = {}
        for i, batch in enumerate(batches):
            batch_num = i + 1
            future = executor.submit(_embed_batch, batch, batch_num)
            futures[future] = i # Map future to the batch index

        for future in as_completed(futures):
            batch_index = futures[future]
            try:
                batch_embeddings = future.result()
                # Calculate the starting index for this batch
                start_index = sum(len(batches[j]) for j in range(batch_index))
                # Place the results back in the correct order
                end_index = start_index + len(batch_embeddings)
                all_embeddings[start_index:end_index] = batch_embeddings
            except Exception as e:
                print(f"A batch failed to process: {e}")

    # Filter out any None values in case of errors
    final_embeddings = [emb for emb in all_embeddings if emb is not None]
    
    print("Embedding complete.")
    return np.array(final_embeddings, dtype=np.float32)

def build_faiss_index(embeddings: np.ndarray):
    """
    Build a FAISS index from the chunk embeddings.
    """
    if embeddings.size == 0:
        return None
    dim = embeddings.shape[1]
    index = faiss.IndexFlatL2(dim)
    index.add(embeddings)
    return index