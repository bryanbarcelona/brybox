import csv
from pathlib import Path
from typing import Any, ClassVar

from brybox.utils.config.handlers.base import BaseFormatHandler


class CsvHandler(BaseFormatHandler):
    """
    Handles .csv files.
    Reads via DictReader → list[dict].
    Auto-detects delimiter (comma or semicolon) via csv.Sniffer.
    Empty cells are treated as None (field absent, not empty string).
    'action' column defaults to 'DELETE' if absent or empty.
    Writes back with semicolon delimiter for Excel compatibility.
    """

    # Canonical column order for write-back.
    # Any extra columns not in this list are appended at the end.
    _COLUMN_ORDER: ClassVar[list[str]] = [
        'domain',
        'sender',
        'subject',
        'has_pdf_attachment',
        'embedded_link',
        'action',
    ]

    # Write-back delimiter — semicolon for broad Excel/LibreOffice compatibility
    _WRITE_DELIMITER: ClassVar[str] = ';'

    @staticmethod
    def read(path: Path) -> list[dict[str, Any]]:
        """
        Read a CSV file and return a list of dicts.
        Delimiter is auto-detected (comma or semicolon).
        Empty strings are converted to None.
        Boolean fields (has_pdf_attachment, embedded_link) are coerced to bool.
        Missing or empty 'action' defaults to 'DELETE'.
        """
        content = path.read_text(encoding='utf-8')

        # Sniff delimiter from first 2048 chars, fall back to semicolon
        try:
            dialect = csv.Sniffer().sniff(content[:2048], delimiters=',;')
            delimiter = dialect.delimiter
        except csv.Error:
            delimiter = ';'

        lines = content.splitlines()
        reader = csv.DictReader(lines, delimiter=delimiter)
        rows = list(reader)
        fieldnames = reader.fieldnames or []

        has_action_col = 'action' in fieldnames
        bool_fields = {'has_pdf_attachment', 'embedded_link'}

        result = []
        for row in rows:
            cleaned: dict[str, Any] = {}
            for k, raw_v in row.items():
                if k is None:
                    continue  # skip phantom columns from sniffer artifacts
                v = raw_v.strip() if isinstance(raw_v, str) else raw_v
                if not v:
                    cleaned[k] = None
                elif k in bool_fields:
                    cleaned[k] = v.lower() in {'true', '1', 'yes'}
                else:
                    cleaned[k] = v

            # Default action to DELETE if column absent or empty
            if not has_action_col or cleaned.get('action') is None:
                cleaned['action'] = 'DELETE'

            # Drop None values to keep dicts lean
            cleaned = {k: v for k, v in cleaned.items() if v is not None}

            # Skip rows with no sender
            if not cleaned.get('sender'):
                continue

            result.append(cleaned)

        return result

    @staticmethod
    def write(path: Path, data: list[dict[str, Any]]) -> None:
        """
        Write a list of dicts back to CSV using semicolon delimiter.
        Columns follow _COLUMN_ORDER, extra fields appended after.
        None values are written as empty strings.
        Rows with no sender are skipped.
        """
        if not data:
            path.write_text('', encoding='utf-8')
            return

        # Build full column set in canonical order
        all_keys: set[str] = set()
        for row in data:
            all_keys.update(row.keys())

        fieldnames = [c for c in CsvHandler._COLUMN_ORDER if c in all_keys]
        extras = sorted(all_keys - set(fieldnames))
        fieldnames += extras

        with path.open('w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(
                f,
                fieldnames=fieldnames,
                delimiter=CsvHandler._WRITE_DELIMITER,
                extrasaction='ignore',
            )
            writer.writeheader()
            for row in data:
                if not row.get('sender'):
                    continue
                writer.writerow({k: ('' if row.get(k) is None else row.get(k)) for k in fieldnames})

    @classmethod
    def supported_extensions(cls) -> set[str]:
        return {'.csv'}
