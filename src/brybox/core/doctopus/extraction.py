"""
Text extraction, line filtering, metadata extraction, and special case handling
for the Doctopus PDF classification pipeline.
"""

import re
from pathlib import Path
from typing import Any

import pdfplumber
from dateutil import parser

from brybox.exceptions.documents import DoctopusPDFError, DoctopusPDFNotFoundError
from brybox.utils.logging import get_configured_logger

logger = get_configured_logger('Extraction')


class TextProcessor:
    """Handles PDF text extraction and line filtering."""

    def __init__(self, config: dict[str, Any]):
        self.config = config

    def extract_content(self, pdf_path: Path) -> str:
        """Extract text content from the first page of a PDF."""
        if not pdf_path.exists():
            raise DoctopusPDFNotFoundError(f'PDF file not found: {pdf_path}', pdf_path=pdf_path)

        try:
            with pdfplumber.open(pdf_path) as pdf:
                if not pdf.pages:
                    return ''  # Empty PDF, not an error

                text = pdf.pages[0].extract_text()
                return text or ''  # None becomes empty string, not an error

        except pdfplumber.PDFSyntaxError as e:
            raise DoctopusPDFError(f'PDF is corrupted or invalid: {pdf_path}', pdf_path=pdf_path) from e
        except Exception as e:
            if 'password' in str(e).lower():
                raise DoctopusPDFError(f'PDF is password protected: {pdf_path}', pdf_path=pdf_path) from e
            raise DoctopusPDFError(f'Unexpected error opening PDF {pdf_path}: {e}', pdf_path=pdf_path) from e

    def reduce_to_relevant_lines(self, content: str) -> list[str]:
        """
        Filter content to lines likely to contain dates or invoice metadata,
        based on extraction rules defined in config.
        """
        extraction_rules = self.config.get('extraction_rules', {})

        months = [
            'January',
            'Januar',
            'February',
            'Februar',
            'March',
            'März',
            'April',
            'May',
            'Mai',
            'June',
            'Juni',
            'July',
            'Juli',
            'August',
            'September',
            'October',
            'Oktober',
            'November',
            'December',
            'Dezember',
        ]

        month_translations = {
            'January': 'Januar',
            'February': 'Februar',
            'March': 'März',
            'May': 'Mai',
            'June': 'Juni',
            'July': 'Juli',
            'October': 'Oktober',
            'Oct': 'Okt',
            'December': 'Dezember',
            'Dec': 'Dez',
        }

        lines = content.split('\n')

        # Normalise German month names to English so downstream parsing is consistent
        for i, line in enumerate(lines):
            for english, german in month_translations.items():
                if english not in line:
                    lines[i] = lines[i].replace(german, english)

        relevant_lines = []
        for i, line in enumerate(lines):
            if any(substring in line for substring in month_translations.keys() | month_translations.values()):
                relevant_lines.append(line)

            for trigger_type, triggers in extraction_rules.items():
                for trigger in triggers:
                    if trigger in line:
                        if trigger_type == 'same_line':
                            line = f'{trigger}{line.split(trigger)[-1]}'
                            relevant_lines.append(line.replace(trigger, '').replace(':', '').strip())
                            relevant_lines.append(line)
                        elif trigger_type == 'previous_line' and i > 0:
                            relevant_lines.append(lines[i - 1])
                        elif trigger_type == 'next_line' and i < len(lines) - 1:
                            relevant_lines.append(lines[i + 1])

            if any(month.lower() in line.lower() for month in months):
                relevant_lines.append(line)

        return relevant_lines if relevant_lines else lines


class MetadataExtractor:
    """Extracts document metadata (dates, invoice IDs) from filtered lines."""

    def __init__(self, config: dict[str, Any]):
        self.config = config

    def extract_date(self, lines: list[str]) -> str | None:
        """Extract and return the first valid date found in lines as YYYYMMDD."""
        date_patterns = self.config.get('metadata_triggers', {}).get('date_patterns', [])
        if not date_patterns:
            date_patterns = [r'\b(?:\d{1,2}(?:st|nd|rd|th)?[ ./-](?:\d{1,2}|[a-zA-Z]+)[ ./-]\d{2,4})\b']

        date_list = []
        for line in lines:
            for pattern in date_patterns:
                match = re.search(pattern, line)
                if match:
                    date_list.append(match.group())

        for date_str in date_list:
            try:
                parsed = self._parse_date(date_str)
                return parsed.strftime('%Y%m%d')
            except (ValueError, TypeError, parser.ParserError):
                continue

        return None

    def _parse_date(self, line: str) -> Any:
        """Parse a date string into a datetime object, inferring delimiter convention."""
        line = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', line)

        if '.' in line:
            return parser.parse(line, dayfirst=True)
        elif '/' in line:
            return parser.parse(line, dayfirst=False)
        else:
            return parser.parse(line, dayfirst=True)

    def extract_invoice_id(self, lines: list[str]) -> str | None:
        """Extract invoice ID from lines using configured triggers."""
        invoice_triggers = self.config.get('metadata_triggers', {}).get('invoice_id', [])

        for line in lines:
            for trigger in invoice_triggers:
                if trigger in line:
                    invoice_number = (
                        line.replace(trigger, '').replace(':', '').replace('. ', '').replace(')', '').strip()
                    )
                    return invoice_number.split(' ')[0]

        return None


class SpecialCaseHandler:
    """
    Applies category-specific line transformations before metadata extraction.

    # TODO: move to a dedicated special_cases.py once a second special case is added.
    """

    def handle_special_cases(self, category: str, lines: list[str]) -> list[str]:
        """Dispatch to category-specific handler, returning lines unchanged if none applies."""
        if category == 'McDonalds Rechnung':
            return self._handle_mcdonalds(lines)

        return lines

    def _handle_mcdonalds(self, lines: list[str]) -> list[str]:
        """
        Normalise McDonald's date format.

        McDonald's receipts use DD/MM/YYYY with American-style '/' delimiters,
        which dateutil misreads as MM/DD/YYYY. This rewrites matches to DD.MM.YYYY
        so the standard parser handles them correctly.
        """
        date_pattern = r'\b(0[1-9]|[12][0-9]|3[01])/(0[1-9]|1[0-2])/(19|20)\d{2}\b'

        for i, line in enumerate(lines):
            match = re.search(date_pattern, line)
            if match:
                lines[i] = match.group(0).replace('/', '.')

        return lines
