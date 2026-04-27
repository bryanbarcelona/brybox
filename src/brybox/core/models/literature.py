# ruff: noqa
# ty: ignore
"""
Data models for the DoiSmith pipeline.

    DoiSmithContext    — carries all per-file state through the pipeline
    DoiSmithComponents — injectable collaborator factories for DoiSmithPrime
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from brybox.core.doismith.extraction import DoiMetadataExtractor, DoiTextProcessor
from brybox.core.doismith.path_builder import DoiPathBuilder
from brybox.utils.file_ops import FileMover


@dataclass
class DoiSmithContext:
    """Holds processing state for a single PDF through the DoiSmith pipeline."""

    pdf_filepath: Path
    base_dir: Path

    # Set by DoiTextProcessor
    raw_content: str = ''
    doi_lines: list[str] = field(default_factory=list)
    doi_candidates: list[str] = field(default_factory=list)

    # Set by DoiMetadataExtractor
    metadata: dict[str, Any] | None = None
    year: int | None = None
    author: str | None = None
    title: str | None = None

    # Set by DoiPathBuilder
    output_filename: str | None = None
    output_filepath: Path | None = None
    is_new_file: bool = True

    def __str__(self) -> str:
        lines = []

        lines.append('\n')
        lines.append('=' * 50)
        lines.append('LITERATURE PROCESSING CONTEXT')
        lines.append('=' * 50)

        lines.append(f'PDF Name:        {self.pdf_filepath.name}')
        lines.append(f'PDF Path:        {self.pdf_filepath}')
        lines.append(f'Base Directory:  {self.base_dir}')
        lines.append('')

        lines.append('-' * 20)
        lines.append('EXTRACTED METADATA')
        lines.append('-' * 20)
        lines.append(f'Title:           {self.title or "None"}')
        lines.append(f'Author:          {self.author or "None"}')
        lines.append(f'Year:            {self.year or "None"}')
        lines.append(f'Output Filename: {self.output_filename or "None"}')
        lines.append(f'Output Path:     {self.output_filepath or "None"}')
        lines.append(f'Is New File:     {self.is_new_file}')
        lines.append('')

        lines.append('-' * 20)
        lines.append('DOI CANDIDATES')
        lines.append('-' * 20)
        if self.doi_candidates:
            lines.extend(self.doi_candidates)
        else:
            lines.append('(none found)')
        lines.append('')

        lines.append('-' * 20)
        lines.append('DOI LINES')
        lines.append('-' * 20)
        if self.doi_lines:
            lines.extend(self.doi_lines)
        else:
            lines.append('(none)')
        lines.append('')

        lines.append('-' * 20)
        lines.append('FULL CONTENT')
        lines.append('-' * 20)
        lines.append(self.raw_content if self.raw_content else '(empty)')
        lines.append('=' * 50)
        lines.append('')

        return '\n'.join(lines)


@dataclass
class DoiSmithComponents:
    """
    Injectable collaborator classes for DoiSmithPrime.

    Holds class references (not instances) so DoiSmithPrime controls
    instantiation with the correct arguments. Pass a customised instance
    to DoiSmithPrime to override any collaborator — useful for testing.

    Example:
        components = DoiSmithComponents(file_mover=MockFileMover)
        processor = DoiSmithPrime('paper.pdf', components=components)
    """

    text_processor: type = None
    metadata_extractor: type = None
    path_builder: type = None
    file_mover: type = None

    def __post_init__(self):

        if self.text_processor is None:
            self.text_processor = DoiTextProcessor
        if self.metadata_extractor is None:
            self.metadata_extractor = DoiMetadataExtractor
        if self.path_builder is None:
            self.path_builder = DoiPathBuilder
        if self.file_mover is None:
            self.file_mover = FileMover
