"""
Document models for Doctopus PDF processing.
"""

from dataclasses import dataclass, field
from pathlib import Path

from brybox.core.doctopus.extraction import MetadataExtractor, SpecialCaseHandler, TextProcessor
from brybox.core.doctopus.file_ops import FileMover
from brybox.core.doctopus.path_builder import PathBuilder


@dataclass
class ProcessingContext:
    """Holds processing state for a single PDF through the Doctopus pipeline."""

    pdf_filepath: Path
    base_dir: Path
    content: str = ''
    category: str | None = None
    condensed_lines: list[str] = field(default_factory=list)
    document_date: str | None = None
    invoice_id: str | None = None
    output_filename: str | None = None
    output_filepath: Path | None = None
    is_new_file: bool = True

    def __str__(self):
        """Custom representation for better readability."""
        lines = []

        # Header
        lines.append('\n')
        lines.append('=' * 50)
        lines.append('DOCUMENT PROCESSING CONTEXT')
        lines.append('=' * 50)

        # Status & File Info
        category_status = f'{self.category}' if self.category else 'None'
        lines.append(f'Category:        {category_status}')
        lines.append(f'PDF Name:        {self.pdf_filepath.name}')
        lines.append(f'PDF Path:        {self.pdf_filepath}')
        lines.append('')

        # Extracted Metadata
        lines.append('-' * 20)
        lines.append('EXTRACTED METADATA')
        lines.append('-' * 20)
        lines.append(f'Document Date:   {self.document_date or "None"}')
        lines.append(f'Invoice ID:      {self.invoice_id or "None"}')
        lines.append(f'Output Filename: {self.output_filename or "None"}')
        lines.append(f'Output Path:     {self.output_filepath or "None"}')
        lines.append(f'Base Directory:  {self.base_dir}')
        lines.append(f'Is New File:     {self.is_new_file}')
        lines.append('')

        # Focused Lines
        lines.append('-' * 20)
        lines.append('FOCUSED LINES')
        lines.append('-' * 20)
        if self.condensed_lines:
            lines.extend(self.condensed_lines)
        else:
            lines.append('(none)')
        lines.append('')

        # Full Content
        lines.append('-' * 20)
        lines.append('FULL CONTENT')
        lines.append('-' * 20)
        if self.content:
            lines.append(self.content)
        else:
            lines.append('(empty)')

        lines.append('=' * 50)
        lines.append('')

        return '\n'.join(lines)


@dataclass
class DoctopusComponents:
    """
    Injectable collaborator classes for DoctopusPrime.

    Holds class references (not instances) so DoctopusPrime controls
    instantiation with the correct arguments. Pass a customised instance
    to DoctopusPrime to override any collaborator — useful for testing.

    Example:
        components = DoctopusComponents(file_mover=MockFileMover)
        processor = DoctopusPrime('invoice.pdf', components=components)
    """

    text_processor: type[TextProcessor] = TextProcessor
    metadata_extractor: type[MetadataExtractor] = MetadataExtractor
    special_handler: type[SpecialCaseHandler] = SpecialCaseHandler
    path_builder: type[PathBuilder] = PathBuilder
    file_mover: type[FileMover] = FileMover
