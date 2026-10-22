from __future__ import annotations
from typing import List, Tuple
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from langchain_core.documents import Document
_DEFAULT_HEADERS: List[Tuple[str, str]] = [('#', 'H1'), ('##', 'H2'), ('###', 'H3')]
_DEFAULT_CHUNK_SIZE = 400
_DEFAULT_OVERLAP = 80

def semantic_chunk_text(text: str, *, chunk_size: int=_DEFAULT_CHUNK_SIZE, overlap: int=_DEFAULT_OVERLAP, headers_to_split_on: List[Tuple[str, str]] | None=None) -> List[str]:
    if not text:
        return []
    headers = headers_to_split_on or _DEFAULT_HEADERS
    md_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers)
    header_docs: List[Document] = md_splitter.split_text(text)
    recursive_splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=overlap)
    final_chunks: List[str] = []
    for doc in header_docs:
        sub_chunks = recursive_splitter.split_text(doc.page_content)
        final_chunks.extend(sub_chunks)
    return final_chunks