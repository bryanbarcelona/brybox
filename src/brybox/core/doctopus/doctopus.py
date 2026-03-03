"""
Doctopus PDF classification and filing system.

Public API:
    DoctopusPrime     — processes a single PDF file
    DoctopusPrimeNexus — batch-processes a directory of PDFs
"""

from pathlib import Path

from brybox.core.models.document import DoctopusComponents, ProcessingContext
from brybox.exceptions.documents import (
    DoctopusConfigurationError,
    DoctopusError,
    DoctopusFileOperationError,
    DoctopusPDFError,
    DoctopusPDFNotFoundError,
)
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
        *,
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
            If no category is found, context.category will be None and
            output_filepath will be empty - this is a normal outcome.

        Raises:
            DoctopusPDFError: If the PDF file is corrupted, missing, or unreadable
            DoctopusConfigurationError: If configuration is invalid
            DoctopusFileOperationError: If file system operations fail
        """
        context = ProcessingContext(pdf_filepath=self.pdf_filepath, base_dir=self.base_dir)

        try:
            context.content = self.text_processor.extract_content(self.pdf_filepath)
        except DoctopusPDFNotFoundError:
            log_and_display(f'📄 File not found: {self.pdf_filepath.name}', level='error')
            raise
        except DoctopusPDFError as e:
            log_and_display(f'📄 PDF error for {self.pdf_filepath.name}: {e}', level='error')
            raise

        context.category = self._classify_document(context.content)

        self._last_context = context

        if not context.category:
            log_and_display(f'⏸️ No category match: {self.pdf_filepath.name}', level='info')
            return context

        context.condensed_lines = self.text_processor.reduce_to_relevant_lines(context.content)
        context.condensed_lines = self.special_handler.handle_special_cases(context.category, context.condensed_lines)

        context.document_date = self.metadata_extractor.extract_date(context.condensed_lines)
        context.invoice_id = self.metadata_extractor.extract_invoice_id(context.condensed_lines)

        filename_stem = self.path_builder.get_filename_component(context.category, self.config)
        context.output_filename = self.path_builder.build_filename(
            context.document_date, filename_stem, context.invoice_id
        )

        context.output_filepath = self.path_builder.build_output_path(
            context.category, context.output_filename, self.config, self.pdf_filepath
        )

        self._last_context = context
        return context

    def shuttle_service(self) -> bool:
        """
        Move the PDF to its organised destination if categorized.

        Returns:
            True if the file was successfully moved (implies it was categorized).
            False if no category matched (file left in place).

        Raises:
            DoctopusPDFError: If the PDF file is corrupted, missing, or unreadable
            DoctopusConfigurationError: If configuration is invalid
            DoctopusFileOperationError: If file system operations fail
        """
        context = self.process()

        if not context.category or not context.output_filepath:
            return False

        try:
            success, is_new = self.file_mover.move_file(context.pdf_filepath, context.output_filepath)
        except DoctopusFileOperationError as e:
            log_and_display(f'💾 File operation failed for {self.pdf_filepath.name}: {e}', level='error')
            raise
        else:
            context.is_new_file = is_new
            if is_new:
                log_and_display(f'✅ Moved: {self.pdf_filepath.name} → {context.category}', level='info')
            else:
                log_and_display(
                    f'🔄 Duplicate deleted: {self.pdf_filepath.name} (already exists in {context.category})',
                    level='info',
                )
            self._last_context = context
            return success

    def _classify_document(self, content: str) -> str | None:
        """Return the first category whose triggers all appear in content, or None."""
        for category, rules in self.config.get('categories', {}).items():
            if all(trigger in content for trigger in rules.get('triggers', [])):
                return category
        return None

    @property
    def category(self) -> str | None:
        return self._last_context.category if self._last_context else None

    @property
    def document_date(self) -> str | None:
        return self._last_context.document_date if self._last_context else None

    @property
    def invoice_id(self) -> str | None:
        return self._last_context.invoice_id if self._last_context else None


class DoctopusPrimeNexus:
    """
    Batch-processes all PDF files in a directory using shared configuration.
    """

    def __init__(
        self,
        dir_path: str | Path,
        base_dir: str | Path | None = None,
        config: dict | None = None,
        *,
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

    def process_all(self, *, progress_bar: bool = True) -> dict[str, dict]:
        """
        Process all PDF files in the configured directory.

        Args:
            progress_bar: Whether to show a progress bar.

        Returns:
            Dict mapping each file path to a result dict:
            {
                'success': bool,      # True if no errors occurred
                'processed': bool,    # True if file was categorized AND moved
                'category': str|None, # Category if found
                'error': str|None     # Error message if any
            }

        Raises:
            DoctopusConfigurationError: If configuration is fundamentally broken
        """
        if not self.dir_path.exists():
            raise DoctopusConfigurationError(f'Directory does not exist: {self.dir_path}', pdf_path=self.dir_path)

        pdf_files = list(self.dir_path.glob('*.pdf'))

        log_and_display(f'Processing {len(pdf_files)} PDF file(s) in {self.dir_path}', sticky=True)

        iterable = (
            trackerator(pdf_files, description='Processing PDFs', final_message='All PDFs processed!')
            if progress_bar
            else pdf_files
        )

        results = {}

        for pdf_file in iterable:
            result = {'success': False, 'processed': False, 'category': None, 'error': None}

            try:
                processor = self.processor_class(
                    pdf_filepath=pdf_file,
                    base_dir=self.base_dir,
                    config=self.config,
                    dry_run=self.dry_run,
                )

                moved = processor.shuttle_service()

                result['success'] = True
                result['processed'] = moved
                result['category'] = processor.category

            except DoctopusError as e:
                result['error'] = str(e)
                # No logging here - Prime already logged it

            except Exception as e:  # noqa: BLE001
                result['error'] = f'Unexpected error: {e}'
                log_and_display(f'💥 Unexpected error for {pdf_file.name}: {e}', level='error')

            finally:
                results[str(pdf_file)] = result

        # Summary
        successful = sum(1 for r in results.values() if r['success'])
        processed = sum(1 for r in results.values() if r['processed'])
        log_and_display(
            f'Completed: {processed} moved, {successful - processed} skipped, {len(results) - successful} failed'
        )

        return results
