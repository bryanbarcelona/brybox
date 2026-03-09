import shutil
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path

from brybox.exceptions.images import (
    SnapJediConversionFailedError,
    SnapJediConversionTimeoutError,
    SnapJediFileOperationError,
    SnapJediToolNotFoundError,
)
from brybox.utils.logging import get_configured_logger

logger = get_configured_logger('ImageConverter')


class ImageConverter(ABC):
    """Abstract interface for image format conversion."""

    @abstractmethod
    def convert_to_jpg(self, source: Path, target: Path) -> None:
        """
        Convert image to JPG format.

        Args:
            source: Source image path
            target: Target JPG path

        Raises:
            SnapJediConversionError: If conversion fails
        """


class ImageMagickConverter(ImageConverter):
    """
    Converts images using ImageMagick's mogrify command.

    Preserves all metadata during conversion.
    """

    def __init__(self, mogrify_path: str | None = None):
        """
        Initialize converter.

        Args:
            mogrify_path: Path to mogrify command. If None, attempts to find it.
        """
        self.mogrify_path = mogrify_path or self._find_mogrify()

    def convert_to_jpg(self, source: Path, target: Path) -> None:
        """
        Convert HEIC/HEIF to JPG preserving all metadata.

        Uses ImageMagick's mogrify which:
        - Preserves EXIF data
        - Preserves GPS coordinates
        - Maintains color profiles

        Args:
            source: Source image path (HEIC, HEIF, etc.)
            target: Target JPG path

        Raises:
            ConversionError: If conversion fails
        """
        # mogrify creates output in same directory with .jpg extension
        command = f'{self.mogrify_path} -format jpg "{source}"'

        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,  # Prevent hanging on large files
            )

            if result.returncode != 0:
                raise SnapJediConversionFailedError(
                    f'ImageMagick conversion failed: {result.stderr}', image_path=source, stderr=result.stderr
                )

            # mogrify creates source_name.jpg in same directory
            intermediate = source.with_suffix('.jpg')

            if not intermediate.exists():
                raise SnapJediConversionFailedError(
                    f'ImageMagick did not create expected output: {intermediate}', image_path=source
                )

            # Move to target if different from intermediate
            if intermediate != target:
                try:
                    intermediate.rename(target)
                except (PermissionError, OSError) as e:
                    raise SnapJediFileOperationError(
                        f'Failed to move converted image from {intermediate} to {target}',
                        source_path=intermediate,
                        dest_path=target,
                    ) from e

        except subprocess.TimeoutExpired as e:
            raise SnapJediConversionTimeoutError(
                'Conversion timed out after 30 seconds', image_path=source, timeout_seconds=30
            ) from e

    @staticmethod
    def _find_mogrify() -> str:
        """
        Locate mogrify command.

        Search order:
        1. 'magick mogrify' (ImageMagick 7+)
        2. 'mogrify' (ImageMagick 6)
        3. Bundled in assets/bin/ (future)

        Returns:
            Command string to invoke mogrify

        Raises:
            RuntimeError: If mogrify not found
        """
        # Try ImageMagick 7 syntax first
        if shutil.which('magick'):
            return 'magick mogrify'

        # Fall back to ImageMagick 6 syntax
        if shutil.which('mogrify'):
            return 'mogrify'

        raise SnapJediToolNotFoundError('ImageMagick not found. Install ImageMagick 6 or 7.', tool_name='ImageMagick')
