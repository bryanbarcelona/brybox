import logging
import datetime
import os

timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

def configure_logging() -> None | tuple:
    """Configures logging settings for the application."""

    # Create Logs directory if it doesn't exist
    logs_dir = 'logs'
    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir)
        print(f"Created directory: {logs_dir}")
    
    log_filepath = os.path.join(logs_dir, f'{timestamp}_brybox.log')
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(message)s',
        filename=log_filepath,
        filemode='a',
        encoding='utf-8'
    )

    pdfminer_logger = logging.getLogger("pdfminer")
    pdfminer_logger.propagate = False
    pdfminer_logger.handlers.clear()
    pdfminer_logger.addHandler(logging.NullHandler())