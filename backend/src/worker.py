import sys
import logging
from src import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("rq_worker")

def start_worker():
    if not config.USE_REDIS:
        logger.error("Redis is not available according to configuration checks. Can't start RQ Worker.")
        sys.exit(1)

    try:
        import redis
        from rq import Worker, Queue, Connection
        
        logger.info(f"Connecting to Redis at {config.REDIS_HOST}:{config.REDIS_PORT}...")
        redis_conn = redis.Redis(
            host=config.REDIS_HOST,
            port=config.REDIS_PORT,
            db=config.REDIS_DB,
            password=config.REDIS_PASSWORD
        )
        
        # Test connection
        redis_conn.ping()
        logger.info("Connected to Redis successfully.")
        
        with Connection(redis_conn):
            queues = [Queue("default")]
            worker = Worker(queues)
            logger.info("RQ Worker started. Listening for ingestion jobs...")
            worker.work()
    except Exception as e:
        logger.critical(f"Failed to start RQ Worker: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    start_worker()
