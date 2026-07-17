import os
import sys
import time
import json
import requests
from pathlib import Path
from typing import Optional
sys.path.insert(0, str(Path(__file__).parent))
from app.celery_app import get_celery_app
from app.tasks import process_document
from app.utils.document_parser import DocumentParser, get_file_hash
FASTAPI_URL = os.getenv('FASTAPI_URL', 'http://localhost:8000')
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
TEST_DOCUMENT_PATH = Path(__file__).parent / 'test_files' / 'test.txt'
GREEN = '\x1b[92m'
YELLOW = '\x1b[93m'
RED = '\x1b[91m'
BLUE = '\x1b[94m'
RESET = '\x1b[0m'

def print_section(title: str):
    print(f"\n{BLUE}{'=' * 60}")
    print(f'  {title}')
    print(f"{'=' * 60}{RESET}\n")

def print_success(msg: str):
    print(f'{GREEN}✓ {msg}{RESET}')

def print_warning(msg: str):
    print(f'{YELLOW}⚠ {msg}{RESET}')

def print_error(msg: str):
    print(f'{RED}✗ {msg}{RESET}')

def check_redis_connection() -> bool:
    print_section('Checking Redis Connection')
    try:
        import redis
        r = redis.from_url(REDIS_URL)
        r.ping()
        print_success(f'Redis is accessible at {REDIS_URL}')
        return True
    except Exception as e:
        print_error(f'Failed to connect to Redis: {e}')
        print(f'Make sure Redis is running and accessible at: {REDIS_URL}')
        return False

def check_fastapi_server() -> bool:
    print_section('Checking FastAPI Server')
    try:
        response = requests.get(f'{FASTAPI_URL}/', timeout=5)
        if response.status_code == 200:
            print_success(f'FastAPI server is running at {FASTAPI_URL}')
            return True
    except Exception as e:
        print_error(f'Failed to connect to FastAPI: {e}')
        print(f'Make sure FastAPI is running with: uvicorn app.main:app --reload')
        return False
    return False

def check_celery_worker() -> bool:
    print_section('Checking Celery Worker')
    try:
        celery_app = get_celery_app()
        inspect = celery_app.control.inspect()
        stats = inspect.stats()
        if stats:
            print_success(f'Celery worker(s) available: {list(stats.keys())}')
            return True
        else:
            print_error('No Celery workers are active')
            print('Start a worker with: celery -A app.celery_app worker --loglevel=info')
            return False
    except Exception as e:
        print_error(f'Failed to inspect Celery: {e}')
        return False

def test_document_upload() -> Optional[str]:
    print_section('Testing Document Upload')
    if not TEST_DOCUMENT_PATH.exists():
        print_error(f'Test document not found: {TEST_DOCUMENT_PATH}')
        print('Creating a simple test document...')
        TEST_DOCUMENT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(TEST_DOCUMENT_PATH, 'w') as f:
            f.write('This is a test document.\n')
            f.write('It contains some sample text for testing the document processing pipeline.\n')
            f.write('The RAG system should be able to parse and chunk this content.\n')
            f.write('And then answer questions about it.\n')
    print(f'Using test document: {TEST_DOCUMENT_PATH}')
    try:
        print(f'Kicking off process_document task...')
        task = process_document.delay(str(TEST_DOCUMENT_PATH), f'file://{TEST_DOCUMENT_PATH}')
        print_success(f'Task created with ID: {task.id}')
        return task.id
    except Exception as e:
        print_error(f'Failed to upload document: {e}')
        return None

def monitor_task_progress(task_id: str, max_wait_seconds: int=60, poll_interval: int=2):
    print_section('Monitoring Task Progress')
    celery_app = get_celery_app()
    start_time = time.time()
    last_state = None
    while time.time() - start_time < max_wait_seconds:
        task_result = celery_app.AsyncResult(task_id)
        state = task_result.status
        if state != last_state:
            if state == 'PENDING':
                print(f'Status: {YELLOW}{state}{RESET} (waiting to start)')
            elif state == 'STARTED':
                print(f'Status: {BLUE}{state}{RESET}')
                if isinstance(task_result.info, dict):
                    stage = task_result.info.get('stage', 'unknown')
                    progress = task_result.info.get('progress', 0)
                    print(f'  Stage: {stage}, Progress: {progress}%')
            elif state == 'SUCCESS':
                print(f'Status: {GREEN}{state}{RESET}')
                if task_result.result:
                    result = task_result.result
                    print(f'  Result: {json.dumps(result, indent=2)}')
                return True
            elif state == 'FAILURE':
                print(f'Status: {RED}{state}{RESET}')
                print(f'  Error: {task_result.info}')
                return False
            elif state == 'RETRY':
                print(f'Status: {YELLOW}{state}{RESET}')
            else:
                print(f'Status: {state}')
            last_state = state
        if state in ('SUCCESS', 'FAILURE'):
            break
        time.sleep(poll_interval)
    if time.time() - start_time >= max_wait_seconds:
        print_warning(f'Task did not complete within {max_wait_seconds} seconds')
        print(f'Current status: {task_result.status}')
        return False
    return True

def verify_cache_created(task_result) -> bool:
    print_section('Verifying Cache Files')
    if task_result.status != 'SUCCESS':
        print_error('Task did not complete successfully, skipping cache verification')
        return False
    result = task_result.result
    if not result or result.get('status') != 'success':
        print_error(f'Task returned error: {result}')
        return False
    chunks_file = result.get('chunks_file')
    index_file = result.get('index_file')
    if chunks_file and os.path.exists(chunks_file):
        with open(chunks_file, 'r') as f:
            chunks = json.load(f)
        print_success(f'Chunks file exists: {chunks_file}')
        print(f'  → {len(chunks)} chunks generated')
        return True
    else:
        print_warning(f'Chunks file not found: {chunks_file}')
        return False

def test_idempotency(task_id_1: str) -> bool:
    print_section('Testing Idempotency (Second Upload Should Use Cache)')
    celery_app = get_celery_app()
    result_1 = celery_app.AsyncResult(task_id_1)
    if result_1.status != 'SUCCESS':
        print_warning('First task not complete, skipping idempotency test')
        return False
    result_1_data = result_1.result
    doc_hash = result_1_data.get('doc_hash')
    print(f'Uploading same document again (doc_hash: {doc_hash})')
    try:
        task_2 = process_document.delay(str(TEST_DOCUMENT_PATH), f'file://{TEST_DOCUMENT_PATH}')
        print_success(f'Second task created with ID: {task_2.id}')
        if not monitor_task_progress(task_2.id, max_wait_seconds=30):
            return False
        result_2 = celery_app.AsyncResult(task_2.id)
        if result_2.status == 'SUCCESS':
            result_2_data = result_2.result
            if result_2_data.get('cached'):
                print_success('Second task used cached results (idempotency verified!)')
                return True
            else:
                print_warning('Second task did not use cache (re-processed)')
                return False
        else:
            print_error(f'Second task failed: {result_2.info}')
            return False
    except Exception as e:
        print_error(f'Idempotency test failed: {e}')
        return False

def test_status_endpoint(task_id: str) -> bool:
    print_section('Testing FastAPI Status Endpoint')
    try:
        url = f'{FASTAPI_URL}/api/v1/hackrx/jobs/{task_id}/status'
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            status_data = response.json()
            print_success(f"Status endpoint response: {status_data['status']}")
            if 'result' in status_data and status_data['result']:
                print(f"  Result: {json.dumps(status_data['result'], indent=2)}")
            if 'progress' in status_data and status_data['progress']:
                print(f"  Progress: {status_data['progress']}")
            return True
        else:
            print_error(f'Status endpoint returned {response.status_code}')
            print(f'  Response: {response.text}')
            return False
    except Exception as e:
        print_error(f'Failed to query status endpoint: {e}')
        return False

def print_summary(results: dict):
    print_section('Test Summary')
    passed = sum((1 for v in results.values() if v))
    total = len(results)
    for test_name, passed_flag in results.items():
        status = f'{GREEN}PASS{RESET}' if passed_flag else f'{RED}FAIL{RESET}'
        print(f'  [{status}] {test_name}')
    print()
    if passed == total:
        print_success(f'All {total} tests passed!')
    else:
        print_warning(f'{passed}/{total} tests passed')

def main():
    print(f"\n{BLUE}{'=' * 60}")
    print('  RAG Pipeline Async Processing Tests')
    print(f"{'=' * 60}{RESET}\n")
    results = {}
    task_id = None
    results['Redis Connection'] = check_redis_connection()
    if not results['Redis Connection']:
        print_error('Redis not available. Cannot continue.')
        print_summary(results)
        return 1
    results['FastAPI Server'] = check_fastapi_server()
    results['Celery Worker'] = check_celery_worker()
    if not results['Celery Worker']:
        print_error('Celery worker not available. Cannot continue.')
        print_summary(results)
        return 1
    task_id = test_document_upload()
    results['Document Upload'] = task_id is not None
    if task_id:
        if monitor_task_progress(task_id):
            results['Task Completion'] = True
            celery_app = get_celery_app()
            task_result = celery_app.AsyncResult(task_id)
            results['Cache Creation'] = verify_cache_created(task_result)
            results['Idempotency'] = test_idempotency(task_id)
            results['Status Endpoint'] = test_status_endpoint(task_id)
        else:
            results['Task Completion'] = False
    print_summary(results)
    all_passed = all(results.values())
    return 0 if all_passed else 1
if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)