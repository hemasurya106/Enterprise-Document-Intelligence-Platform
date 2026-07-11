# In utils/pdf_parser.py
import fitz  # PyMuPDF
import requests
import tempfile
import hashlib # Add this import

def download_pdf(url: str) -> str:
    # ... (no change to this function)
    response = requests.get(url)
    if response.status_code != 200:
        raise Exception(f"Failed to download PDF: {response.status_code}")
    
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    temp_file.write(response.content)
    temp_file.close()
    return temp_file.name


def get_file_hash(pdf_path: str) -> str:
    """Calculates the SHA-256 hash of a file."""
    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()
        sha256_hash = hashlib.sha256(pdf_bytes).hexdigest()
    return sha256_hash

def extract_text_from_pdf(pdf_path: str) -> str:
    # ... (no change to this function)
    text = ""
    with fitz.open(pdf_path) as doc:
        for page in doc:
            text += page.get_text()
    return text