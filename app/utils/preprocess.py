import os
import sys
import json
import faiss
from dotenv import load_dotenv

# --- SETUP ---
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, PROJECT_ROOT)
load_dotenv()
# --- END SETUP ---

import requests
from app.utils.pdf_parser import get_file_hash
from app.utils.document_parser import DocumentParser
from app.utils.semantic_chunker import semantic_chunk_text
from app.utils.embedder import embed_chunks  # Includes batching logic

# --- CONFIG ---
KNOWN_DOCUMENTS = [
  "https://hackrx.blob.core.windows.net/assets/Test%20/Pincode%20data.xlsx?sv=2023-01-03&spr=https&st=2025-08-04T18%3A50%3A43Z&se=2026-08-05T18%3A50%3A00Z&sr=b&sp=r&sig=xf95kP3RtMtkirtUMFZn%2FFNai6sWHarZsTcvx8ka9mI%3D",
  "https://hackrx.blob.core.windows.net/assets/Test%20/Test%20Case%20HackRx.pptx?sv=2023-01-03&spr=https&st=2025-08-04T18%3A36%3A56Z&se=2026-08-05T18%3A36%3A00Z&sr=b&sp=r&sig=v3zSJ%2FKW4RhXaNNVTU9KQbX%2Bmo5dDEIzwaBzXCOicJM%3D",
  "https://hackrx.blob.core.windows.net/assets/Test%20/Mediclaim%20Insurance%20Policy.docx?sv=2023-01-03&spr=https&st=2025-08-04T18%3A42%3A14Z&se=2026-08-05T18%3A42%3A00Z&sr=b&sp=r&sig=yvnP%2FlYfyyqYmNJ1DX51zNVdUq1zH9aNw4LfPFVe67o%3D",
  "https://hackrx.blob.core.windows.net/assets/Test%20/Salary%20data.xlsx?sv=2023-01-03&spr=https&st=2025-08-04T18%3A46%3A54Z&se=2026-08-05T18%3A46%3A00Z&sr=b&sp=r&sig=sSoLGNgznoeLpZv%2FEe%2FEI1erhD0OQVoNJFDPtqfSdJQ%3D",
  "https://hackrx.blob.core.windows.net/assets/Test%20/image.png?sv=2023-01-03&spr=https&st=2025-08-04T19%3A21%3A45Z&se=2026-08-05T19%3A21%3A00Z&sr=b&sp=r&sig=lAn5WYGN%2BUAH7mBtlwGG4REw5EwYfsBtPrPuB0b18M4%3D",
  "https://hackrx.blob.core.windows.net/assets/Test%20/image.jpeg?sv=2023-01-03&spr=https&st=2025-08-04T19%3A29%3A01Z&se=2026-08-05T19%3A29%3A00Z&sr=b&sp=r&sig=YnJJThygjCT6%2FpNtY1aHJEZ%2F%2BqHoEB59TRGPSxJJBwo%3D",
  "https://hackrx.blob.core.windows.net/assets/Test%20/Fact%20Check.docx?sv=2023-01-03&spr=https&st=2025-08-04T20%3A27%3A22Z&se=2028-08-05T20%3A27%3A00Z&sr=b&sp=r&sig=XB1%2FNzJ57eg52j4xcZPGMlFrp3HYErCW1t7k1fMyiIc%3D"
]
ASSET_DIR = os.path.join(PROJECT_ROOT, "known_documents")


def _download_file(url: str) -> str:
    """Download a file from URL preserving its filename, return local path"""
    local_filename = os.path.join(ASSET_DIR, os.path.basename(url.split("?")[0]))
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(local_filename, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
    return local_filename


def process_and_save_document(doc_url: str):
    """Downloads, parses, chunks, embeds, and stores assets for a known document."""
    print(f"--- Processing: {doc_url[:60]}... ---")

    try:
        # Step 1: Download
        print("Step 1: Downloading document...")
        file_path = _download_file(doc_url)

        # Step 2: Hashing
        print("Step 2: Calculating document hash...")
        doc_hash = get_file_hash(file_path)
        asset_path = os.path.join(ASSET_DIR, doc_hash)

        # Skip if already processed
        if os.path.exists(os.path.join(asset_path, "chunks.json")) and os.path.exists(os.path.join(asset_path, "index.faiss")):
            print(f"Assets for {doc_hash} already exist. Skipping.\n")
            os.remove(file_path)
            return

        # Step 3: Parsing via DocumentParser
        print("Step 3: Parsing document...")
        parser = DocumentParser()
        parse_result = parser.extract_text_from_file(file_path)
        text = parse_result.get("text", "")
        if not text.strip():
            print("No text extracted. Skipping.")
            os.remove(file_path)
            return

        # Step 4: Chunking
        print("Step 4: Semantic chunking...")
        chunks = semantic_chunk_text(text)
        if not chunks:
            print("No chunks generated. Skipping.")
            os.remove(file_path)
            return

        # Step 5: Embedding
        print(f"Step 5: Embedding {len(chunks)} chunks...")
        embeddings = embed_chunks(chunks)
        if embeddings.size == 0:
            print("No embeddings created. Skipping.")
            os.remove(file_path)
            return

        # Step 6: Indexing
        print("Step 6: Building FAISS index...")
        index = faiss.IndexFlatL2(embeddings.shape[1])
        index.add(embeddings)

        # Step 7: Save
        print("Step 7: Saving assets...")
        os.makedirs(asset_path, exist_ok=True)
        with open(os.path.join(asset_path, "chunks.json"), "w", encoding='utf-8') as f:
            json.dump(chunks, f)
        faiss.write_index(index, os.path.join(asset_path, "index.faiss"))

        print(f"✓ Done processing document with hash: {doc_hash}\n")
        os.remove(file_path)

    except Exception as e:
        print(f"✗ Failed to process {doc_url[:50]} — {e}\n")


if __name__ == "__main__":
    print("=== Starting pre-processing of all known documents ===")
    os.makedirs(ASSET_DIR, exist_ok=True)
    for url in KNOWN_DOCUMENTS:
        process_and_save_document(url)
    print("=== All documents processed ===")
