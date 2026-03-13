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
    output_filename: str = ''
    output_filepath: Path = Path()
    is_new_file: bool = True


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
