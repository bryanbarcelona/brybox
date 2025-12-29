"""
Audiora audio classification and filing system.
A sleek, futuristic audio processing system for organizing audio files.
"""

import glob
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from brybox.utils.config_loader import ConfigLoader as _ConfigLoader
from brybox.utils.logging import get_configured_logger, log_and_display, trackerator
from .file_ops import _FileMover
from .filename import _FilenameProcessor
from .metadata import _AudioMetadataExtractor

logger = get_configured_logger('Audiora')


def _load_audiora_config(config_path: str | None = None, config: dict | None = None) -> dict[str, Any]:
    """Return merged audiora JSON configs."""
    if config is not None:
        return config
    config_path = config_path or 'configs'
    return _ConfigLoader.load_configs(config_path=config_path, config_files={'categories': 'audiora_rules.json'})


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
        config_path: str | None = None,
        config: dict | None = None,
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
        self.config = _load_audiora_config(config_path, config)

        # Determine base directory
        if base_dir:
            self.base_dir = base_dir
        elif 'audio_target_dir' in self.config:
            self.base_dir = self.config['audio_target_dir']
        else:
            self.base_dir = str(Path.home() / 'AudioFiles')

        # Initialize processors
        self.metadata_extractor = _AudioMetadataExtractor()
        self.filename_processor = _FilenameProcessor(self.config)
        self.file_mover = _FileMover(self.base_dir, dry_run)

    def process(self) -> _ProcessingContext:
        """
        Process the audio file through the complete pipeline.

        Returns:
            ProcessingContext with all extracted information
        """
        context = _ProcessingContext(audio_filepath=self.audio_filepath, base_dir=self.base_dir)

        filepath = Path(self.audio_filepath)
        filename_without_ext = filepath.stem
        extension = filepath.suffix

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
        built_path = self.file_mover.build_output_path(
            context.category, context.output_filename, self.config, self.audio_filepath
        )
        context.output_filepath = built_path or ''

        return context

    def shuttle_service(self) -> bool:
        """
        Move file to organized location.

        Returns:
            True if file was successfully processed
        """
        context = self.process()

        if not context.category or not context.output_filepath:
            return False

        # Move main file
        success, is_new = self.file_mover.move_file(context.audio_filepath, context.output_filepath)

        if not success:
            return False

        context.is_new_file = is_new
        return True

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
        dir_path: str,
        base_dir: str | None = None,
        config_path: str | None = None,
        config: dict | None = None,
        dry_run: bool = False,
        processor_class: type[AudioraCore] = AudioraCore,
    ):
        """
        Initialize batch processor.

        Args:
            dir_path: Directory containing audio files to process
            base_dir: Override target base directory
            config_path: Path to config directory
            config: Pre-loaded config dict
            dry_run: If True, no files are moved or deleted
            processor_class: Processor class to use (for testing)
        """
        self.dir_path = dir_path
        self.base_dir = base_dir
        self.dry_run = dry_run
        self.processor_class = processor_class

        # Load config once for all files
        self.config = _load_audiora_config(config_path, config)

    def process_all(self, progress_bar: bool = True, file_extensions: list[str] | None = None) -> dict[str, bool]:
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

        # Gather all matching audio files
        audio_files = []
        for ext in file_extensions:
            pattern = os.path.join(self.dir_path, f'*{ext}')
            audio_files.extend(glob.glob(pattern))

        results = {}

        log_and_display(f'Processing {len(audio_files)} audio file(s) in {self.dir_path}', sticky=True)
        audio_files = (
            trackerator(audio_files, description='Processing audio', final_message='All audio processed!')
            if progress_bar
            else audio_files
        )

        for audio_file in audio_files:
            try:
                processor = self.processor_class(
                    audio_filepath=audio_file, base_dir=self.base_dir, config=self.config, dry_run=self.dry_run
                )

                success = processor.shuttle_service()
                results[audio_file] = success

            except Exception as e:
                log_and_display(f'Error processing {audio_file}: {e}', level='error')
                results[audio_file] = False

        return results
