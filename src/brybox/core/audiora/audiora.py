"""
Audiora audio classification and filing system.
A sleek, futuristic audio processing system for organizing audio files.
"""

from dataclasses import dataclass
from pathlib import Path

from brybox.core.audiora.file_ops import FileMover
from brybox.core.audiora.filename import FilenameProcessor
from brybox.core.audiora.metadata import AudioMetadataExtractor
from brybox.core.audiora.path_builder import PathBuilder
from brybox.exceptions.audio import (
    AudioraAudioNotFoundError,
    AudioraConfigurationError,
    AudioraCorruptedFileError,
    AudioraError,
    AudioraFileOperationError,
    AudioraMetadataError,
)
from brybox.utils.logging import get_configured_logger, log_and_display, trackerator
from brybox.utils.settings import BryboxSettings

logger = get_configured_logger('Audiora')


@dataclass
class _ProcessingContext:
    """Holds processing state for a single audio file."""

    audio_filepath: str
    base_dir: str
    category: str | None = None
    metadata_date: str | None = None
    filename_date: str | None = None
    validated_date: str | None = None
    session_name: str = ''
    output_filename: str = ''
    output_filepath: str = ''
    is_new_file: bool = True


class AudioraCore:
    """Single audio file processor with configurable classification and filing."""

    def __init__(
        self,
        audio_filepath: str,
        base_dir: str | None = None,
        config: dict | None = None,
        *,
        dry_run: bool = False,
    ) -> None:
        """
        Initialize audio file processor.

        Args:
            audio_filepath: Path to audio file to process
            base_dir: Override target base directory
            config_path: Path to config directory
            config: Pre-loaded config dict
            dry_run: If True, no files are moved or deleted
        """
        self.audio_filepath = audio_filepath
        self.dry_run = dry_run

        # Load configuration
        self.config = config or BryboxSettings().audiora

        # Determine base directory
        if base_dir:
            self.base_dir = base_dir
        elif 'audio_target_dir' in self.config:
            self.base_dir = self.config['audio_target_dir']
        else:
            self.base_dir = str(Path.home() / 'AudioFiles')

        # Initialize processors
        self.metadata_extractor = AudioMetadataExtractor()
        self.filename_processor = FilenameProcessor(self.config)
        self.path_builder = PathBuilder(self.base_dir)
        self.file_mover = FileMover(self.base_dir, dry_run=dry_run)

    def process(self) -> _ProcessingContext:
        """
        Process the audio file through the complete pipeline.

        Returns:
            ProcessingContext with all extracted information

        Raises:
            AudioraAudioNotFoundError: If audio file doesn't exist
            AudioraMetadataError: If metadata extraction fails
            AudioraConfigurationError: If configuration is invalid
            AudioraFileOperationError: If path building fails
        """
        context = _ProcessingContext(audio_filepath=self.audio_filepath, base_dir=self.base_dir)

        filepath = Path(self.audio_filepath)
        filename_without_ext = filepath.stem
        extension = filepath.suffix

        if not filepath.exists():
            raise AudioraAudioNotFoundError(
                f'Audio file not found: {self.audio_filepath}', audio_path=self.audio_filepath
            )

        # Classify audio file
        context.category = self.filename_processor.classify_audio(filepath.name)

        if not context.category:
            log_and_display(f'No category match for: {filepath.name}', level='warning')
            return context

        # Extract dates
        context.metadata_date = self.metadata_extractor.extract_media_created_date(self.audio_filepath)
        context.filename_date = self.metadata_extractor.extract_filename_date(filename_without_ext)

        # Validate and choose date
        context.validated_date = self.metadata_extractor.validate_dates(
            context.metadata_date, context.filename_date, filepath.name
        )

        # Extract session name
        context.session_name = self.filename_processor.extract_session_name(filename_without_ext, context.category)

        # Build output filename
        context.output_filename = self.filename_processor.build_filename(
            context.validated_date, context.session_name, context.category, extension
        )

        # Build output path
        built_path = self.path_builder.build_output_path(
            context.category, context.output_filename, self.config, self.audio_filepath
        )
        context.output_filepath = built_path or ''

        return context

    def shuttle_service(self) -> bool:
        """
        Move file to organized location.

        Returns:
            True if file was successfully processed (moved or identified as duplicate)
            False if file had no category match (left in place)

        Raises:
            AudioraAudioNotFoundError: If source file doesn't exist
            AudioraMetadataError: If metadata extraction fails
            AudioraConfigurationError: If configuration is invalid (fatal)
            AudioraFileOperationError: If file operations fail
            AudioraCorruptedFileError: If moved file is corrupted
        """
        try:
            context = self.process()
        except AudioraAudioNotFoundError:
            log_and_display(f'📄 File not found: {Path(self.audio_filepath).name}', level='error')
            raise
        except AudioraMetadataError as e:
            log_and_display(f'📊 Metadata error for {Path(self.audio_filepath).name}: {e}', level='error')
            raise
        except AudioraConfigurationError as e:
            log_and_display(f'⚙️ Configuration error: {e}', level='error')
            raise
        except AudioraFileOperationError as e:
            log_and_display(f'📁 File operation error: {e}', level='error')
            raise
        except AudioraCorruptedFileError as e:
            log_and_display(f'💥 Corrupted file: {e}', level='error')
            raise

        if not context.category or not context.output_filepath:
            return False

        try:
            success, is_new = self.file_mover.move_file(context.audio_filepath, context.output_filepath)
        except AudioraFileOperationError as e:
            log_and_display(f'💾 File operation failed for {Path(self.audio_filepath).name}: {e}', level='error')
            raise
        else:
            context.is_new_file = is_new
            if is_new:
                log_and_display(f'✅ Moved: {Path(self.audio_filepath).name} → {context.output_filepath}')
            else:
                log_and_display(
                    f'🔄 Duplicate deleted: {Path(self.audio_filepath).name} (already exists in {context.category})',
                    level='info',
                )
            return success

    @property
    def category(self) -> str | None:
        """Get audio file category."""
        context = self.process()
        return context.category

    @property
    def validated_date(self) -> str | None:
        """Get validated date."""
        context = self.process()
        return context.validated_date


class AudioraNexus:
    """Batch audio file processor with shared configuration."""

    def __init__(
        self,
        dir_path: str | Path,
        base_dir: str | None = None,
        config: dict | None = None,
        *,
        dry_run: bool = False,
        processor_class: type[AudioraCore] = AudioraCore,
    ):
        """
        Initialize batch processor.

        Args:
            dir_path: Directory containing audio files to process
            base_dir: Override target base directory
            config: Pre-loaded config dict
            dry_run: If True, no files are moved or deleted
            processor_class: Processor class to use (for testing)

        Raises:
            AudioraConfigurationError: If directory doesn't exist
        """
        self.dir_path = Path(dir_path)
        self.base_dir = base_dir
        self.dry_run = dry_run
        self.processor_class = processor_class

        self.config = config or BryboxSettings().audiora

        if not self.dir_path.exists():
            raise AudioraConfigurationError(f'Directory does not exist: {dir_path}', audio_path=dir_path)

    def process_all(self, *, progress_bar: bool = True, file_extensions: list[str] | None = None) -> dict[str, bool]:
        """
        Process all audio files in directory.

        Args:
            progress_bar: Whether to show progress bar
            file_extensions: List of file extensions to process (default: ['.m4a', '.mp3', '.flac', '.wav'])

        Returns:
            Dict mapping file paths to success status
        """
        if file_extensions is None:
            file_extensions = ['.m4a', '.mp3', '.flac', '.wav']

        audio_files = []
        for ext in file_extensions:
            audio_files.extend(Path(self.dir_path).glob(f'*{ext}'))

        results = {}

        log_and_display(f'Processing {len(audio_files)} audio file(s) in {self.dir_path}', sticky=True)
        audio_files = (
            trackerator(audio_files, description='Processing audio', final_message='All audio processed!')
            if progress_bar
            else audio_files
        )

        for audio_file in audio_files:
            result = {'success': False, 'processed': False, 'category': None, 'error': None}

            try:
                processor = self.processor_class(
                    audio_filepath=str(audio_file),
                    base_dir=self.base_dir,
                    config=self.config,
                    dry_run=self.dry_run,
                )

                processed = processor.shuttle_service()

                result['success'] = True
                result['processed'] = processed
                result['category'] = processor.category

            except AudioraError as e:
                result['error'] = str(e)

            except Exception as e:  # noqa: BLE001
                result['error'] = f'Unexpected: {e}'
                log_and_display(f'💥 Unexpected error for {audio_file.name}: {e}', level='error')

            finally:
                results[str(audio_file)] = result

        # Summary
        successful = sum(1 for r in results.values() if r['success'])
        processed = sum(1 for r in results.values() if r['processed'])
        log_and_display(
            f'Completed: {processed} moved, {successful - processed} skipped, {len(results) - successful} failed'
        )

        return results
