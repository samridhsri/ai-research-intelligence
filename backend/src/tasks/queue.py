import logging
import threading
from src import config

logger = logging.getLogger(__name__)

# Try initializing RQ
redis_conn = None
rq_queue = None

if config.USE_REDIS:
    try:
        import redis
        from rq import Queue
        redis_conn = redis.Redis(
            host=config.REDIS_HOST,
            port=config.REDIS_PORT,
            db=config.REDIS_DB,
            password=config.REDIS_PASSWORD
        )
        rq_queue = Queue("default", connection=redis_conn)
        logger.info("Successfully connected to Redis Queue.")
    except Exception as e:
        logger.error(f"Failed to connect to Redis. Fallback task queue active. Error: {e}")
        rq_queue = None

def enqueue_job(func, *args, background_tasks=None, **kwargs) -> str:
    """
    Enqueues a background job.
    Uses RQ if Redis is available, otherwise falls back to FastAPI's BackgroundTasks
    or a daemon thread.
    """
    if config.USE_REDIS and rq_queue:
        try:
            job = rq_queue.enqueue(func, *args, **kwargs)
            logger.info(f"Enqueued job {job.id} to RQ.")
            return job.id
        except Exception as e:
            logger.error(f"Failed to enqueue job to RQ: {e}. Falling back to in-process execution.")
    
    # Fallback to in-process async execution
    if background_tasks:
        background_tasks.add_task(func, *args, **kwargs)
        logger.info("Enqueued job using FastAPI BackgroundTasks.")
        return "fastapi_background_task"
    else:
        # Run in a daemon thread so it does not block the HTTP request
        thread = threading.Thread(target=func, args=args, kwargs=kwargs)
        thread.daemon = True
        thread.start()
        logger.info("Enqueued job using background Thread.")
        return "daemon_thread_task"
