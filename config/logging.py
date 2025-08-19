import logging
import sys

def setup_logging(log_level=logging.INFO):
    import sys
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        stream=sys.stdout,
        force=True
    )
    logger = logging.getLogger(__name__)
    def log_print(message, level="INFO"):
        timestamp = __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{timestamp}] [{level}] {message}", flush=True)
    def safe_log_info(message):
        logger.info(message)
        log_print(message, "INFO")
    return logger, log_print, safe_log_info
