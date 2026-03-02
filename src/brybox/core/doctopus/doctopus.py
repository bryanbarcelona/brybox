"""
Doctopus PDF classification and filing system.

Public API:
    DoctopusPrime     — processes a single PDF file
    DoctopusPrimeNexus — batch-processes a directory of PDFs
"""

from functools import cached_property
from pathlib import Path

from brybox.core.models.document import DoctopusComponents, ProcessingContext
from brybox.utils.logging import get_configured_logger, log_and_display, trackerator
from brybox.utils.settings import BryboxSettings

logger = get_configured_logger('Doctopus')


class DoctopusPrime:
    """
    Processes a single PDF through the full classification and filing pipeline.

    Orchestrates TextProcessor, MetadataExtractor, SpecialCaseHandler,
    and FileMover — holds no processing logic itself.
    """

    def __init__(
        self,
        pdf_filepath: str | Path,
        base_dir: str | Path | None = None,
        config: dict | None = None,
        dry_run: bool = False,
        components: DoctopusComponents | None = None,
    ):
        """
        Args:
            pdf_filepath: Path to the PDF file to process.
            base_dir: Override the target base directory from config.
            config: Pre-loaded config dict. Loads from BryboxSettings if not provided.
            dry_run: If True, no files are moved or deleted.
            components: Injectable collaborator classes. Defaults to standard implementations.
        """
        self.pdf_filepath = Path(pdf_filepath)
        self.dry_run = dry_run
        self.config = config or BryboxSettings().doctopus

        if base_dir:
            self.base_dir = Path(base_dir)
        elif 'target_dir' in self.config:
            self.base_dir = Path(self.config['target_dir'])
        else:
            self.base_dir = Path.home() / 'BryBoxPDFs'

        c = components or DoctopusComponents()
        self.text_processor = c.text_processor(self.config)
        self.metadata_extractor = c.metadata_extractor(self.config)
        self.special_handler = c.special_handler()
        self.path_builder = c.path_builder(self.base_dir)
        self.file_mover = c.file_mover(dry_run)

    def process(self) -> ProcessingContext:
        """
        Run the PDF through the full pipeline.

        Returns:
            ProcessingContext populated with all extracted information.
        """
        context = ProcessingContext(pdf_filepath=self.pdf_filepath, base_dir=self.base_dir)

        context.content = self.text_processor.extract_content(self.pdf_filepath)
        context.category = self._classify_document(context.content)
        context.condensed_lines = self.text_processor.reduce_to_relevant_lines(context.content)

        if context.category:
            context.condensed_lines = self.special_handler.handle_special_cases(
                context.category, context.condensed_lines
            )

        context.document_date = self.metadata_extractor.extract_date(context.condensed_lines)
        context.invoice_id = self.metadata_extractor.extract_invoice_id(context.condensed_lines)

        filename_stem = self.path_builder.get_filename_component(context.category or '', self.config)
        context.output_filename = self.path_builder.build_filename(
            context.document_date, filename_stem, context.invoice_id
        )

        if context.category:
            context.output_filepath = self.path_builder.build_output_path(
                context.category, context.output_filename, self.config, self.pdf_filepath
            )

        return context

    def shuttle_service(self) -> bool:
        """
        Move the PDF to its organised destination.

        Returns:
            True if the file was successfully processed.
        """
        context = self.process()

        if not context.category or not context.output_filepath:
            return False

        success, is_new = self.file_mover.move_file(context.pdf_filepath, context.output_filepath)

        if not success:
            return False

        context.is_new_file = is_new
        return True

    def _classify_document(self, content: str) -> str | None:
        """Return the first category whose triggers all appear in content, or None."""
        for category, rules in self.config.get('categories', {}).items():
            if all(trigger in content for trigger in rules.get('triggers', [])):
                return category
        return None

    @cached_property
    def category(self) -> str | None:
        return self.process().category

    @cached_property
    def document_date(self) -> str | None:
        return self.process().document_date

    @cached_property
    def invoice_id(self) -> str | None:
        return self.process().invoice_id


class DoctopusPrimeNexus:
    """
    Batch-processes all PDF files in a directory using shared configuration.
    """

    def __init__(
        self,
        dir_path: str | Path,
        base_dir: str | Path | None = None,
        config: dict | None = None,
        dry_run: bool = False,
        processor_class: type[DoctopusPrime] = DoctopusPrime,
    ):
        """
        Args:
            dir_path: Directory containing PDFs to process.
            base_dir: Override the target base directory from config.
            config: Pre-loaded config dict. Loads from BryboxSettings if not provided.
            dry_run: If True, no files are moved or deleted.
            processor_class: Processor class to use — injectable for testing.
        """
        self.dir_path = Path(dir_path)
        self.base_dir = Path(base_dir) if base_dir else None
        self.dry_run = dry_run
        self.processor_class = processor_class
        self.config = config or BryboxSettings().doctopus

    def process_all(self, progress_bar: bool = True) -> dict[str, bool]:
        """
        Process all PDF files in the configured directory.

        Args:
            progress_bar: Whether to show a progress bar.

        Returns:
            Dict mapping each file path to its success status.
        """
        pdf_files = list(self.dir_path.glob('*.pdf'))

        log_and_display(f'Processing {len(pdf_files)} PDF file(s) in {self.dir_path}', sticky=True)

        iterable = (
            trackerator(pdf_files, description='Processing PDFs', final_message='All PDFs processed!')
            if progress_bar
            else pdf_files
        )

        results = {}
        for pdf_file in iterable:
            try:
                processor = self.processor_class(
                    pdf_filepath=pdf_file,
                    base_dir=self.base_dir,
                    config=self.config,
                    dry_run=self.dry_run,
                )
                results[pdf_file] = processor.shuttle_service()
            except Exception as e:
                log_and_display(f'Error processing {pdf_file}: {e}')
                results[pdf_file] = False

        return results
