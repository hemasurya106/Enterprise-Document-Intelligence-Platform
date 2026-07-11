"""Semantic-aware text chunking utilities.

This module provides a single public function `semantic_chunk_text` that
splits raw or markdown text into semantically coherent chunks that work
better for retrieval-augmented generation (RAG) than simple fixed-word
splits.  It applies a two-stage strategy similar to the one already used
in `preprocess.py`:

1. Header-aware split – if the text appears to be markdown (lines that
   start with one of `# ## ###`), we first segment by those headers to
   preserve topical boundaries.
2. Recursive split – each large segment is then further divided with
   LangChain's `RecursiveCharacterTextSplitter`, which keeps chunks
   within a given token/character budget while maintaining some
   overlap.

The function returns a plain list[str] so that the rest of the pipeline
(embedding / faiss) can stay unchanged.
"""
from __future__ import annotations

from typing import List, Tuple
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from langchain_core.documents import Document

# Default configuration
_DEFAULT_HEADERS: List[Tuple[str, str]] = [("#", "H1"), ("##", "H2"), ("###", "H3")]
_DEFAULT_CHUNK_SIZE = 400
_DEFAULT_OVERLAP = 80


def semantic_chunk_text(
    text: str,
    *,
    chunk_size: int = _DEFAULT_CHUNK_SIZE,
    overlap: int = _DEFAULT_OVERLAP,
    headers_to_split_on: List[Tuple[str, str]] | None = None,
) -> List[str]:
    """Split *text* into semantically coherent, overlapping chunks.

    Parameters
    ----------
    text : str
        The source text (plain-text or markdown).
    chunk_size : int, optional
        Maximum characters per final chunk, by default 400.
    overlap : int, optional
        Desired character overlap between adjacent chunks, by default 80.
    headers_to_split_on : list, optional
        Markdown header patterns to split on.  If ``None`` the default
        ``[("#", "H1"), ("##", "H2"), ("###", "H3")]`` is used.

    Returns
    -------
    list[str]
        A list of chunk strings.
    """
    if not text:
        return []

    headers = headers_to_split_on or _DEFAULT_HEADERS

    # Stage 1 – header-aware splitter.  For non-markdown text this will
    # just return a single big Document instance.
    md_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers)
    header_docs: List[Document] = md_splitter.split_text(text)

    # Stage 2 – recursive splitter with overlap to create final chunks.
    recursive_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size, chunk_overlap=overlap
    )

    final_chunks: List[str] = []
    for doc in header_docs:
        sub_chunks = recursive_splitter.split_text(doc.page_content)
        final_chunks.extend(sub_chunks)

    return final_chunks
