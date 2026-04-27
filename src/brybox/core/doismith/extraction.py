# ruff: noqa


"""
Text extraction and CrossRef metadata retrieval for the DoiSmith pipeline.

    DoiTextProcessor    — PDF page selection and DOI-bearing line filtering
    DoiMetadataExtractor — DOI regex, candidate generation, CrossRef HTTP
"""

import re
from pathlib import Path
from typing import Any

import pdfplumber
import requests
from pdfplumber.utils.exceptions import MalformedPDFException, PdfminerException

from brybox.exceptions.literature import (
    LiteratureDOINotFoundError,
    LiteratureMetadataError,
    LiteraturePDFError,
    LiteraturePDFNotFoundError,
)
from brybox.utils.logging import get_configured_logger, log_and_display

logger = get_configured_logger('DoiSmith.Extraction')

CROSSREF_BASE_URL = 'https://api.crossref.org/works/'

# Pages with this many or more "doi" occurrences are treated as reference
# lists and excluded (except page 0, which is always included).
_REFERENCE_PAGE_DOI_THRESHOLD = 5

# Matches a bare DOI: 10.{4+ digits}/{suffix} up to whitespace or closing paren
_DOI_PATTERN = re.compile(r'10\.[0-9]{4,}/[^\s)]+')

# Characters that can appear as noise at the end of a scraped DOI token
_DOI_TRAILING_SEPARATORS = ('.', ';', '|')


class DoiTextProcessor:
    """Handles PDF text extraction and DOI-bearing line filtering."""

    def __init__(self, config: dict[str, Any] | None = None):
        # Config reserved for future per-category tuning.
        self.config = config or {}

    def extract_content(self, pdf_path: Path) -> str:
        """
        Extract lowercased text from relevant pages of a PDF.

        Always includes page 0. Subsequent pages are included only when
        their "doi" occurrence count is below the reference-list threshold,
        avoiding noisy bibliography sections.

        Raises:
            LiteraturePDFNotFoundError: File does not exist.
            LiteraturePDFError: File is corrupted, password-protected, or unreadable.
        """
        if not pdf_path.exists():
            raise LiteraturePDFNotFoundError(f'PDF file not found: {pdf_path}', pdf_path=pdf_path)

        try:
            with pdfplumber.open(pdf_path) as pdf:
                if not pdf.pages:
                    return ''

                parts: list[str] = []
                for i, page in enumerate(pdf.pages):
                    page_text = (page.extract_text() or '').lower()
                    if i == 0 or page_text.count('doi') < _REFERENCE_PAGE_DOI_THRESHOLD:
                        parts.append(page_text)

                return '\n'.join(parts)

        except (MalformedPDFException, PdfminerException) as e:
            raise LiteraturePDFError(f'PDF is corrupted or invalid: {pdf_path}', pdf_path=pdf_path) from e
        except Exception as e:
            if 'password' in str(e).lower():
                raise LiteraturePDFError(f'PDF is password protected: {pdf_path}', pdf_path=pdf_path) from e
            raise LiteraturePDFError(f'Unexpected error opening PDF {pdf_path}: {e}', pdf_path=pdf_path) from e

    @staticmethod
    def extract_doi_lines(content: str) -> list[str]:
        """
        Return lines containing "doi", joining lines split mid-identifier.

        When a line ends with "/" — a DOI that wrapped across lines — the
        following line is appended before filtering.
        """
        lines = content.split('\n')
        joined: list[str] = []
        for i, line in enumerate(lines):
            if line.endswith('/') and i < len(lines) - 1:
                joined.append(line + lines[i + 1])
            else:
                joined.append(line)

        return [line for line in joined if 'doi' in line]


class DoiMetadataExtractor:
    """Extracts DOI expressions and retrieves metadata from the CrossRef API."""

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}

    # ── Public interface ──────────────────────────────────────────────────────

    def extract_doi_candidates(self, doi_lines: list[str]) -> list[str]:
        """
        Build an ordered list of CrossRef URLs to try from DOI-bearing lines.

        For each raw DOI match, generates a small family of progressively
        cleaned candidates (original, trailing-non-digit stripped, separator
        truncated) to maximise the chance of a successful lookup without
        making redundant HTTP requests.

        Raises:
            LiteratureDOINotFoundError: No DOI pattern found in any line.
        """
        raw_dois = self._extract_raw_dois(doi_lines)

        if not raw_dois:
            raise LiteratureDOINotFoundError(
                'No DOI expression found in PDF content — likely not an academic paper.',
            )

        candidates: list[str] = []
        seen: set[str] = set()

        for raw in raw_dois:
            for url in self._build_candidate_urls(raw):
                if url not in seen:
                    seen.add(url)
                    candidates.append(url)

        return candidates

    def fetch_metadata(self, candidates: list[str]) -> dict[str, Any]:
        """
        Try each CrossRef URL candidate in order, returning the first
        successful response payload.

        Raises:
            LiteratureMetadataError: All candidates exhausted without a 200 response,
                or the response payload is missing required fields.
        """
        for url in candidates:
            # Normalise em-dash that occasionally appears in scraped DOI text
            url = url.replace('–', '-')
            try:
                response = requests.get(url, timeout=10)
            except requests.RequestException as e:
                log_and_display(f'🌐 Network error fetching {url}: {e}', level='warning')
                continue

            if response.status_code != 200:
                continue

            try:
                payload = response.json().get('message', {})
            except ValueError:
                continue

            if not self._is_usable(payload):
                continue

            return payload

        raise LiteratureMetadataError(
            f'CrossRef lookup failed for all {len(candidates)} candidate(s) — no usable metadata returned.'
        )

    def parse_authorship(self, metadata: dict[str, Any]) -> tuple[int, str, str]:
        """
        Extract (year, author, title) from a CrossRef message payload.

        Raises:
            LiteratureMetadataError: Required fields absent or malformed.
        """
        try:
            year = metadata['created']['date-parts'][0][0]
            title = metadata['title'][0]
        except (KeyError, IndexError, TypeError) as e:
            raise LiteratureMetadataError(f'Metadata payload is missing required fields: {e}') from e

        authors = metadata.get('author', [])
        if len(authors) > 1:
            author = f'{authors[0]["family"]} et al'
        elif len(authors) == 1:
            author = authors[0].get('family', 'Unknown')
        else:
            author = 'Unknown'

        return year, author, title

    # ── Private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _extract_raw_dois(doi_lines: list[str]) -> list[str]:
        """Return the first raw DOI match from each line that contains one."""
        raw: list[str] = []
        for line in doi_lines:
            match = _DOI_PATTERN.search(line)
            if match:
                raw.append(match.group())
        return raw

    @staticmethod
    def _build_candidate_urls(raw_doi: str) -> list[str]:
        """
        Generate an ordered family of CrossRef URL candidates from a single
        raw DOI string.

        Order: original → trailing-non-digit stripped → separator truncated.
        Duplicates within the family are preserved here; deduplication across
        all families is handled by the caller.
        """
        base = CROSSREF_BASE_URL
        candidates: list[str] = [f'{base}{raw_doi}']

        # Strip trailing non-digit characters
        trimmed = raw_doi
        while trimmed and not trimmed[-1].isdigit():
            trimmed = trimmed[:-1]
        if trimmed != raw_doi:
            candidates.append(f'{base}{trimmed}')

        # Truncate at each trailing separator
        for sep in _DOI_TRAILING_SEPARATORS:
            if sep in raw_doi:
                truncated = raw_doi[: raw_doi.rfind(sep)]
                if truncated:
                    candidates.append(f'{base}{truncated}')

        return candidates

    @staticmethod
    def _is_usable(payload: dict[str, Any]) -> bool:
        """Return True if the CrossRef payload contains the minimum required fields."""
        try:
            _ = payload['created']['date-parts'][0][0]
            _ = payload['title'][0]
            return True
        except (KeyError, IndexError, TypeError):
            return False
