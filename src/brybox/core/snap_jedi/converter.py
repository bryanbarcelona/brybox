import shutil
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path

from ...utils.logging import get_configured_logger

logger = get_configured_logger('ImageConverter')


class ConversionError(Exception):
    """Raised when image conversion fails."""


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
            ConversionError: If conversion fails
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
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,  # Prevent hanging on large files
            )

            if result.returncode != 0:
                raise ConversionError(f'ImageMagick conversion failed: {result.stderr}')

            # mogrify creates source_name.jpg in same directory
            intermediate = source.with_suffix('.jpg')

            if not intermediate.exists():
                raise ConversionError(f'ImageMagick did not create expected output: {intermediate}')

            # Move to target if different from intermediate
            if intermediate != target:
                intermediate.rename(target)

        except subprocess.TimeoutExpired:
            raise ConversionError('Conversion timed out after 30 seconds')
        except Exception as e:
            raise ConversionError(f'Conversion failed: {e!s}')

    def _find_mogrify(self) -> str:
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

        raise RuntimeError('ImageMagick not found. Install ImageMagick 6 or 7.')
