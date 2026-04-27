"""
DoiSmith PDF renaming pipeline.

Public API:
    DoiSmithPrime  — processes a single PDF file
    DoiSmithNexus  — batch-processes a directory of PDFs
"""

from pathlib import Path

from brybox.core.models.literature import DoiSmithComponents, DoiSmithContext
from brybox.exceptions.literature import (
    LiteratureConfigurationError,
    LiteratureDOIError,
    LiteratureFileOperationError,
    LiteratureMetadataError,
    LiteraturePDFError,
)
from brybox.utils.logging import get_configured_logger, log_and_display, trackerator
from brybox.utils.settings import BryboxSettings

logger = get_configured_logger('DoiSmith')


class DoiSmithPrime:
    """
    Processes a single PDF through the full DOI resolution and renaming pipeline.

    Orchestrates DoiTextProcessor, DoiMetadataExtractor, DoiPathBuilder,
    and FileMover — holds no processing logic itself.
    """

    def __init__(
        self,
        pdf_filepath: str | Path,
        base_dir: str | Path | None = None,
        config: dict | None = None,
        *,
        dry_run: bool = False,
        components: DoiSmithComponents | None = None,
    ):
        self.pdf_filepath = Path(pdf_filepath)
        self.dry_run = dry_run

        # TODO: register 'doismith.paths' pipe in BryboxSettings._register_pipes()
        # and add CF_DOISMITH_PATHS = 'doismith_paths' constant.
        # Then replace the fallback below with: self.config = config or BryboxSettings().doismith
        self.config = config or BryboxSettings().doismith

        if base_dir:
            self.base_dir = Path(base_dir)
        elif 'target_dir' in self.config:
            self.base_dir = Path(self.config['target_dir'])
        else:
            self.base_dir = Path.home() / 'BryBoxPDFs' / 'Literature'

        c = components or DoiSmithComponents()
        self.text_processor = c.text_processor(self.config)
        self.metadata_extractor = c.metadata_extractor(self.config)
        self.path_builder = c.path_builder(self.base_dir)
        self.file_mover = c.file_mover(dry_run=dry_run)

        self._last_context: DoiSmithContext | None = None

    def process(self) -> DoiSmithContext:
        """
        Run the PDF through the full pipeline.

        Returns:
            DoiSmithContext populated with all extracted information.
            output_filepath will be None if DOI resolution or metadata
            extraction failed — the file is left in place.

        Note:
            DOI and metadata failures are non-fatal: they are logged as
            warnings and the context is returned with partial state so the
            caller can inspect what was found.
        """
        context = DoiSmithContext(pdf_filepath=self.pdf_filepath, base_dir=self.base_dir)

        # Stage 1: extract text — fatal per-file if unreadable
        try:
            context.raw_content = self.text_processor.extract_content(self.pdf_filepath)
        except LiteraturePDFError:
            log_and_display(f'📄 Could not read PDF: {self.pdf_filepath.name}', level='error')
            raise

        # Stage 2: filter DOI lines
        context.doi_lines = self.text_processor.extract_doi_lines(context.raw_content)

        # Stage 3: build candidate URLs — non-fatal (pudding recipes welcome)
        try:
            context.doi_candidates = self.metadata_extractor.extract_doi_candidates(context.doi_lines)
        except LiteratureDOIError:
            log_and_display(
                f'⏸️  No DOI found: {self.pdf_filepath.name} — skipping.',
                level='warning',
            )
            self._last_context = context
            return context

        # Stage 4: CrossRef lookup — non-fatal (flaky network, bad DOI)
        try:
            context.metadata = self.metadata_extractor.fetch_metadata(context.doi_candidates)
            context.year, context.author, context.title = self.metadata_extractor.parse_authorship(context.metadata)
        except LiteratureMetadataError:
            log_and_display(
                f'⏸️  Metadata unavailable: {self.pdf_filepath.name} — skipping.',
                level='warning',
            )
            self._last_context = context
            return context

        # Stage 5: build output path
        context.output_filename = self.path_builder.build_filename(context.title, context.author, context.year)
        context.output_filepath = self.path_builder.build_output_path(context.output_filename)
        context.is_new_file = self.path_builder.is_new_file(context.output_filepath)

        self._last_context = context
        return context

    def shuttle_service(self) -> bool:
        """
        Move the PDF to its renamed destination if metadata was resolved.

        Returns:
            True if the file was successfully moved.
            False if DOI/metadata resolution failed (file left in place).
        """
        context = self.process()

        if not context.output_filepath:
            return False

        try:
            success, is_new = self.file_mover.move_file(context.pdf_filepath, context.output_filepath)
        except LiteratureFileOperationError as e:
            log_and_display(f'💾 File operation failed for {self.pdf_filepath.name}: {e}', level='error')
            raise
        else:
            context.is_new_file = is_new
            if is_new:
                log_and_display(
                    f'✅ Renamed & moved: {self.pdf_filepath.name} → {context.output_filename}',
                    level='info',
                )
            else:
                log_and_display(
                    f'🔄 Duplicate deleted: {self.pdf_filepath.name} (already exists at destination)',
                    level='info',
                )
            self._last_context = context
            return success

    @property
    def preview(self) -> DoiSmithContext:
        """Run the pipeline and return the context for inspection. Does not move any files."""
        return self.process()

    @property
    def title(self) -> str | None:
        return self._last_context.title if self._last_context else None

    @property
    def author(self) -> str | None:
        return self._last_context.author if self._last_context else None

    @property
    def year(self) -> int | None:
        return self._last_context.year if self._last_context else None


class DoiSmithNexus:
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
        processor_class: type[DoiSmithPrime] = DoiSmithPrime,
    ):
        """
        Args:
            dir_path:        Directory containing PDFs to process.
            base_dir:        Override the target base directory from config.
            config:          Pre-loaded config dict. Loads from BryboxSettings if not provided.
            dry_run:         If True, no files are moved or deleted.
            processor_class: Processor class to use — injectable for testing.
        """
        self.dir_path = Path(dir_path)
        self.base_dir = Path(base_dir) if base_dir else None
        self.dry_run = dry_run
        self.processor_class = processor_class
        self.config = config or BryboxSettings().doismith

    def process_all(self, *, progress_bar: bool = True) -> dict[str, dict]:
        """
        Process all PDF files in the configured directory.

        Returns:
            Dict mapping each file path (str) to a result dict:
            {
                'success':   bool,      # True if no errors occurred
                'processed': bool,      # True if file was resolved AND moved
                'skipped':   bool,      # True if DOI/metadata not found (non-fatal)
                'title':     str|None,
                'error':     str|None   # Error message if any
            }

        Raises:
            LiteratureConfigurationError: Directory does not exist.
        """
        if not self.dir_path.exists():
            raise LiteratureConfigurationError(
                f'Directory does not exist: {self.dir_path}',
                pdf_path=self.dir_path,
            )

        pdf_files = list(self.dir_path.glob('*.pdf'))
        log_and_display(f'Processing {len(pdf_files)} PDF file(s) in {self.dir_path}', sticky=True)

        iterable = (
            trackerator(pdf_files, description='Processing PDFs', final_message='All PDFs processed!')
            if progress_bar
            else pdf_files
        )

        results: dict[str, dict] = {}

        for pdf_file in iterable:
            result: dict = {
                'success': False,
                'processed': False,
                'skipped': False,
                'title': None,
                'error': None,
            }

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
                result['skipped'] = not moved
                result['title'] = processor.title

            except LiteraturePDFError as e:
                result['error'] = str(e)
                # Already logged by Prime

            except LiteratureFileOperationError as e:
                result['error'] = str(e)
                # Already logged by Prime

            except LiteratureConfigurationError as e:
                result['error'] = str(e)
                log_and_display(f'⚙️  Configuration error: {e}', level='error')

            except Exception as e:  # noqa: BLE001
                result['error'] = f'Unexpected error: {e}'
                log_and_display(f'💥 Unexpected error for {pdf_file.name}: {e}', level='error')

            finally:
                results[str(pdf_file)] = result

        successful = sum(1 for r in results.values() if r['success'])
        processed = sum(1 for r in results.values() if r['processed'])
        skipped = sum(1 for r in results.values() if r['skipped'])
        failed = len(results) - successful

        log_and_display(f'Completed: {processed} moved, {skipped} skipped, {failed} failed')

        return results
