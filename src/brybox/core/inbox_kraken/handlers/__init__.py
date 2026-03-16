from .attachment import download_attachment_handler
from .dropbox import dropbox_audio_handler
from .misc import delete_handler, ignore_handler, manual_click_handler
from .pdf_link import download_pdf_handler
from .scrapers import kfw_handler, techem_handler

__all__ = [
    'delete_handler',
    'download_attachment_handler',
    'download_pdf_handler',
    'dropbox_audio_handler',
    'ignore_handler',
    'kfw_handler',
    'manual_click_handler',
    'techem_handler',
]
