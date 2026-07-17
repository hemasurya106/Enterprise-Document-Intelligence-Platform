from app.utils.pdf_parser import download_pdf, extract_text_from_pdf
from app.utils.chunker import chunk_text
from app.utils.embedder import embed_chunks, build_faiss_index
url = 'https://hackrx.blob.core.windows.net/assets/policy.pdf?sv=2023-01-03&st=2025-07-04T09%3A11%3A24Z&se=2027-07-05T09%3A11%3A00Z&sr=b&sp=r&sig=N4a9OU0w0QXO6AOIBiu4bpl7AXvEZogeT%2FjUHNO7HzQ%3D'
pdf_path = download_pdf(url)
text = extract_text_from_pdf(pdf_path)
chunks = chunk_text(text, chunk_size=300, overlap=50)
print(f'Extracted {len(chunks)} chunks')
print('Sample chunk:\n', chunks[0][:500])
embeddings = embed_chunks(chunks)
index = build_faiss_index(embeddings)
print(f'FAISS index built with {index.ntotal} vectors')