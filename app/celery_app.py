import os
import sys
from celery import Celery
from celery.schedules import crontab
from dotenv import load_dotenv
load_dotenv()
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
CELERY_LOG_LEVEL = os.getenv('CELERY_LOG_LEVEL', 'info')
_DEFAULT_POOL = 'solo' if sys.platform == 'win32' else 'prefork'
CELERY_POOL = os.getenv('CELERY_POOL', _DEFAULT_POOL)
app = Celery('rag_pipeline', broker=REDIS_URL, backend=REDIS_URL, include=['app.tasks'])
app.conf.update(broker_connection_retry_on_startup=True, broker_connection_retry=True, broker_connection_max_retries=10, result_expires=86400, result_extended=True, task_serializer='json', accept_content=['json'], result_serializer='json', timezone='UTC', enable_utc=True, task_acks_late=True, task_reject_on_worker_lost=True, worker_pool=CELERY_POOL, beat_scheduler='celery.beat:PersistentScheduler', beat_schedule={'cleanup-old-cache': {'task': 'app.tasks.cleanup_old_cache', 'schedule': crontab(hour=2, minute=0), 'options': {'expires': 300}}}, worker_log_format='[%(asctime)s: %(levelname)s/%(processName)s] %(message)s', worker_task_log_format='[%(asctime)s: %(levelname)s/%(processName)s] [%(task_name)s(%(task_id)s)] %(message)s')

def get_celery_app():
    return app