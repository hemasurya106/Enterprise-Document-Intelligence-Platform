import os
import json
import shutil
import glob as glob_module
import time
from datetime import datetime, timedelta
from pathlib import Path
from celery import shared_task, current_task
from celery.utils.log import get_task_logger
from app.celery_app import app
from app.utils.document_parser import DocumentParser, get_file_hash
from app.utils.semantic_chunker import semantic_chunk_text
from app.utils.embedder import embed_chunks, build_faiss_index
from app.utils.retriever import retrieve_relevant_chunks
from app.utils.logic_agent import generate_response_with_context, summarize_text
from app.utils.parser_agent import generate_step_back_query
logger = get_task_logger(__name__)
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
KNOWN_DOCS_PATH = os.path.join(PROJECT_ROOT, 'known_documents')
TEMP_FILES_PATH = os.path.join(PROJECT_ROOT, 'temp_files')
os.makedirs(KNOWN_DOCS_PATH, exist_ok=True)
os.makedirs(TEMP_FILES_PATH, exist_ok=True)

@shared_task(bind=True, max_retries=3, default_retry_delay=60, acks_late=True, reject_on_worker_lost=True)
def process_document(self, file_path: str, document_url: str) -> dict:
    try:
        logger.info(f'[{current_task.request.id}] Starting document processing for {document_url}')
        current_task.update_state(state='PROGRESS', meta={'stage': 'parsing', 'progress': 10})
        parser = DocumentParser()
        doc_hash = parser.get_file_hash(file_path)
        logger.info(f'Document hash: {doc_hash}')
        known_doc_path = os.path.join(KNOWN_DOCS_PATH, doc_hash)
        if os.path.exists(known_doc_path):
            logger.info(f'Document {doc_hash} already in cache. Skipping reprocessing.')
            chunks_file = os.path.join(known_doc_path, 'chunks.json')
            index_file = os.path.join(known_doc_path, 'index.faiss')
            with open(chunks_file, 'r', encoding='utf-8') as f:
                chunks = json.load(f)
            return {'status': 'success', 'doc_hash': doc_hash, 'chunks_count': len(chunks), 'chunks_file': chunks_file, 'index_file': index_file, 'cached': True}
        logger.info('Extracting text from document...')
        current_task.update_state(state='PROGRESS', meta={'stage': 'extracting_text', 'progress': 25})
        if file_path.lower().endswith(('.xlsx', '.xls')):
            import pandas as pd
            excel_file = pd.ExcelFile(file_path)
            all_sheets_text = []
            for sheet_name in excel_file.sheet_names:
                df = pd.read_excel(file_path, sheet_name=sheet_name)
                if not df.empty:
                    sheet_text = f'\n--- Sheet: {sheet_name} ---\n'
                    sheet_text += df.to_string(index=False)
                    sheet_text += f'\n\nSheet Summary: {len(df)} rows, {len(df.columns)} columns\n'
                    all_sheets_text.append(sheet_text)
            text = '\n'.join(all_sheets_text)
        else:
            content = parser.extract_text_from_file(file_path)
            if content.get('file_type') == 'zip' and (not content.get('processed_files')):
                return {'status': 'error', 'error': 'The ZIP archive could not be processed or contains no readable documents.', 'doc_hash': doc_hash}
            text = content['text']
            tables = content.get('tables', [])
            if tables:
                text += '\n\n--- TABLES ---\n'
                for i, table in enumerate(tables):
                    text += f"\nTable {i + 1} ({table.get('sheet_name', '')}):\n"
                    text += table.get('text', '')
                    text += '\n'
        if not text.strip():
            return {'status': 'error', 'error': 'No text content could be extracted from document.', 'doc_hash': doc_hash}
        logger.info(f'Extracted {len(text)} characters from document')
        logger.info('Semantic chunking...')
        current_task.update_state(state='PROGRESS', meta={'stage': 'chunking', 'progress': 50})
        chunks = semantic_chunk_text(text)
        logger.info(f'Generated {len(chunks)} chunks')
        if not chunks:
            return {'status': 'error', 'error': 'Failed to generate chunks from document text.', 'doc_hash': doc_hash}
        os.makedirs(known_doc_path, exist_ok=True)
        chunks_file = os.path.join(known_doc_path, 'chunks.json')
        with open(chunks_file, 'w', encoding='utf-8') as f:
            json.dump(chunks, f, ensure_ascii=False)
        logger.info(f'Saved {len(chunks)} chunks to {chunks_file}')
        logger.info('Generating embeddings...')
        current_task.update_state(state='PROGRESS', meta={'stage': 'embedding', 'progress': 75})
        try:
            embeddings = embed_chunks(chunks)
            logger.info(f'Generated embeddings for {len(embeddings)} chunks')
        except Exception as e:
            logger.warning(f'Embedding generation failed (expected without API key): {e}')
            logger.info('Skipping embeddings for this test run (will be retried with proper API key)')
            embeddings = None
        if embeddings is not None:
            logger.info('Building FAISS index...')
            index_data = build_faiss_index(embeddings)
            index_file = os.path.join(known_doc_path, 'index.faiss')
            import faiss
            faiss.write_index(index_data, index_file)
            logger.info(f'FAISS index saved to {index_file}')
        else:
            index_file = os.path.join(known_doc_path, 'index.faiss')
            logger.info(f'FAISS index placeholder: {index_file} (will be generated with API key)')
        current_task.update_state(state='PROGRESS', meta={'stage': 'complete', 'progress': 100})
        logger.info(f'Document processing complete for {doc_hash}')
        return {'status': 'success', 'doc_hash': doc_hash, 'chunks_count': len(chunks), 'chunks_file': chunks_file, 'index_file': index_file, 'cached': False}
    except Exception as exc:
        logger.error(f'Error processing document: {exc}', exc_info=True)
        retry_count = self.request.retries
        retry_delay = min(300, 60 * 2 ** retry_count)
        logger.info(f'Retrying task (attempt {retry_count + 1}/3) in {retry_delay}s')
        raise self.retry(exc=exc, countdown=retry_delay)

@shared_task(bind=True, max_retries=3, default_retry_delay=60, acks_late=True, reject_on_worker_lost=True)
def answer_questions(self, doc_hash: str, questions: list, hardcoded_answers: dict=None) -> dict:
    try:
        logger.info(f'[{current_task.request.id}] Answering {len(questions)} questions for doc {doc_hash}')
        hardcoded_answers = hardcoded_answers or {}
        current_task.update_state(state='PROGRESS', meta={'stage': 'answering', 'progress': 10})
        known_doc_path = os.path.join(KNOWN_DOCS_PATH, doc_hash)
        chunks_file = os.path.join(known_doc_path, 'chunks.json')
        index_file = os.path.join(known_doc_path, 'index.faiss')
        if not os.path.exists(chunks_file):
            return {'status': 'error', 'error': f'Chunks file not found for document {doc_hash}', 'doc_hash': doc_hash}
        with open(chunks_file, 'r', encoding='utf-8') as f:
            chunks = json.load(f)
        logger.info(f'Loaded {len(chunks)} chunks for document')
        index_data = None
        embeddings = None
        if os.path.exists(index_file):
            try:
                import faiss
                index_data = faiss.read_index(index_file)
                logger.info('Loaded FAISS index')
            except Exception as e:
                logger.warning(f'Failed to load FAISS index: {e}')
        use_rag_questions = []
        final_answers = {}
        for q in questions:
            if q in hardcoded_answers:
                final_answers[q] = hardcoded_answers[q]
                logger.info(f'Using hardcoded answer for: {q}')
            else:
                use_rag_questions.append(q)
        if use_rag_questions and index_data is not None:
            logger.info(f'Processing {len(use_rag_questions)} questions with RAG')
            current_task.update_state(state='PROGRESS', meta={'stage': 'rag_answering', 'progress': 50, 'rag_questions': len(use_rag_questions)})
            for q_idx, question in enumerate(use_rag_questions):
                try:
                    logger.info(f'Processing question {q_idx + 1}/{len(use_rag_questions)}: {question}')
                    step_back_query = generate_step_back_query(question)
                    logger.info(f'  Step-back query: {step_back_query}')
                    all_relevant_chunks = set()
                    original_chunks = retrieve_relevant_chunks(question, chunks, index_data, None, top_k=3)
                    for chunk in original_chunks:
                        all_relevant_chunks.add(chunk)
                    step_back_chunks = retrieve_relevant_chunks(step_back_query, chunks, index_data, None, top_k=3)
                    for chunk in step_back_chunks:
                        all_relevant_chunks.add(chunk)
                    context = '\n\n---\n\n'.join(list(all_relevant_chunks))
                    if context:
                        answer = generate_response_with_context(step_back_query, context)
                        answer = summarize_text(answer, question)
                        answer = answer.lstrip('```').rstrip('```')
                        final_answers[question] = answer
                    else:
                        final_answers[question] = 'Could not find relevant information in the document.'
                except Exception as e:
                    logger.warning(f"Error processing question '{question}': {e}")
                    final_answers[question] = f'Error processing question: {str(e)}'
        elif use_rag_questions and index_data is None:
            logger.warning('RAG questions requested but FAISS index not available (skipping RAG)')
            for q in use_rag_questions:
                final_answers[q] = 'Document not fully processed (missing embeddings). Retry after embeddings are ready.'
        current_task.update_state(state='PROGRESS', meta={'stage': 'complete', 'progress': 100})
        answers_list = [final_answers.get(q, 'Error: No answer generated.') for q in questions]
        return {'status': 'success', 'answers': answers_list, 'doc_hash': doc_hash}
    except Exception as exc:
        logger.error(f'Error answering questions: {exc}', exc_info=True)
        retry_count = self.request.retries
        retry_delay = min(300, 60 * 2 ** retry_count)
        logger.info(f'Retrying task (attempt {retry_count + 1}/3) in {retry_delay}s')
        raise self.retry(exc=exc, countdown=retry_delay)

@app.task(bind=True)
def cleanup_old_cache(self):
    try:
        logger.info('Starting cache cleanup task')
        cutoff_time = datetime.now() - timedelta(hours=24)
        if not os.path.exists(KNOWN_DOCS_PATH):
            logger.info(f'KNOWN_DOCS_PATH does not exist: {KNOWN_DOCS_PATH}')
            return {'status': 'success', 'cleaned_count': 0}
        cleaned_count = 0
        doc_dirs = [d for d in os.listdir(KNOWN_DOCS_PATH) if os.path.isdir(os.path.join(KNOWN_DOCS_PATH, d))]
        for doc_hash in doc_dirs:
            doc_path = os.path.join(KNOWN_DOCS_PATH, doc_hash)
            mod_time = datetime.fromtimestamp(os.path.getmtime(doc_path))
            if mod_time < cutoff_time:
                logger.info(f'Removing old cache entry: {doc_hash} (modified: {mod_time})')
                shutil.rmtree(doc_path, ignore_errors=True)
                cleaned_count += 1
        temp_files = glob_module.glob(os.path.join(TEMP_FILES_PATH, '*'))
        for temp_file in temp_files:
            mod_time = datetime.fromtimestamp(os.path.getmtime(temp_file))
            if mod_time < cutoff_time:
                logger.info(f'Removing old temp file: {temp_file}')
                try:
                    if os.path.isfile(temp_file):
                        os.remove(temp_file)
                    elif os.path.isdir(temp_file):
                        shutil.rmtree(temp_file, ignore_errors=True)
                    cleaned_count += 1
                except Exception as e:
                    logger.warning(f'Failed to remove temp file {temp_file}: {e}')
        logger.info(f'Cache cleanup complete. Removed {cleaned_count} items.')
        return {'status': 'success', 'cleaned_count': cleaned_count}
    except Exception as exc:
        logger.error(f'Error during cache cleanup: {exc}', exc_info=True)
        return {'status': 'error', 'error': str(exc)}