"""
Text extraction, line filtering, metadata extraction, and special case handling
for the Doctopus PDF classification pipeline.
"""

import re
from pathlib import Path
from typing import Any

import pdfplumber
from dateutil import parser
from pdfplumber.utils.exceptions import MalformedPDFException, PdfminerException

from brybox.exceptions.documents import DoctopusPDFError, DoctopusPDFNotFoundError
from brybox.utils.logging import get_configured_logger

logger = get_configured_logger('Extraction')


class TextProcessor:
    """Handles PDF text extraction and line filtering."""

    def __init__(self, config: dict[str, Any]):
        self.config = config

    @staticmethod
    def extract_content(pdf_path: Path) -> str:
        """Extract text content from the first page of a PDF."""
        if not pdf_path.exists():
            raise DoctopusPDFNotFoundError(f'PDF file not found: {pdf_path}', pdf_path=pdf_path)

        try:
            with pdfplumber.open(pdf_path) as pdf:
                if not pdf.pages:
                    return ''  # Empty PDF, not an error

                text = pdf.pages[0].extract_text()
                return text or ''  # None becomes empty string, not an error

        except (MalformedPDFException, PdfminerException) as e:
            raise DoctopusPDFError(f'PDF is corrupted or invalid: {pdf_path}', pdf_path=pdf_path) from e
        except Exception as e:
            if 'password' in str(e).lower():
                raise DoctopusPDFError(f'PDF is password protected: {pdf_path}', pdf_path=pdf_path) from e
            raise DoctopusPDFError(f'Unexpected error opening PDF {pdf_path}: {e}', pdf_path=pdf_path) from e

    def reduce_to_relevant_lines(self, content: str) -> list[str]:
        """
        Filter content to lines likely to contain dates or invoice metadata.
        """
        lines = content.split('\n')
        normalized_lines = self._normalize_months(lines)

        extraction_rules = self.config.get('extraction_rules', {})
        relevant_lines = []

        for i, line in enumerate(normalized_lines):
            if self._contains_month(line):
                relevant_lines.append(line)
                continue

            rule_matches = self._get_rule_matches(line, i, normalized_lines, extraction_rules)
            relevant_lines.extend(rule_matches)

        return relevant_lines if relevant_lines else normalized_lines

    def _get_rule_matches(self, line: str, index: int, all_lines: list[str], rules: dict) -> list[str]:
        """Helper to process all triggers for a single line to keep nesting low."""
        matches = []
        for trigger_type, triggers in rules.items():
            for trigger in triggers:
                if trigger not in line:
                    continue

                result = self._apply_trigger_logic(trigger_type, trigger, line, index, all_lines)
                if isinstance(result, list):
                    matches.extend(result)
                elif result:
                    matches.append(result)
        return matches

    @staticmethod
    def _normalize_months(lines: list[str]) -> list[str]:
        """Helper to translate German months to English."""
        month_translations = {
            'Januar': 'January',
            'Februar': 'February',
            'März': 'March',
            'Mai': 'May',
            'Juni': 'June',
            'Juli': 'July',
            'Oktober': 'October',
            'Okt': 'Oct',
            'Dezember': 'December',
            'Dez': 'Dez',
        }
        new_lines = []
        for line in lines:
            updated_line = line
            for german, english in month_translations.items():
                updated_line = updated_line.replace(german, english)
            new_lines.append(updated_line)
        return new_lines

    @staticmethod
    def _contains_month(line: str) -> bool:
        """Helper to check if a line contains any month name."""
        months = [
            'january',
            'february',
            'march',
            'april',
            'may',
            'june',
            'july',
            'august',
            'september',
            'october',
            'november',
            'december',
        ]
        line_lower = line.lower()
        return any(m in line_lower for m in months)

    @staticmethod
    def _apply_trigger_logic(trigger_type: str, trigger: str, line: str, index: int, all_lines: list[str]) -> Any:
        """Handles the specific 'trigger_type' logic for line filtering."""
        if trigger_type == 'same_line':
            segment = f'{trigger}{line.rsplit(trigger, maxsplit=1)[-1]}'
            return [segment.replace(trigger, '').replace(':', '').strip(), segment]

        if trigger_type == 'previous_line' and index > 0:
            return all_lines[index - 1]

        if trigger_type == 'next_line' and index < len(all_lines) - 1:
            return all_lines[index + 1]

        return None


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

    @staticmethod
    def _parse_date(line: str) -> Any:
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

    @staticmethod
    def _handle_mcdonalds(lines: list[str]) -> list[str]:
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
