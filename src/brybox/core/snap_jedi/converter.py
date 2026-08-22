from abc import ABC, abstractmethod
from pathlib import Path

import pillow_heif
from PIL import Image, ImageOps, UnidentifiedImageError

from brybox.exceptions.images import SnapJediConversionFailedError
from brybox.utils.logging import get_configured_logger

logger = get_configured_logger('ImageConverter')

_JPEG_QUALITY = 95

pillow_heif.register_heif_opener()


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


class PillowHeifConverter(ImageConverter):
    """
    Converts HEIC/HEIF images to JPG using pillow-heif.

    Preserves EXIF (including GPS), ICC color profile, and bakes the EXIF
    orientation into the pixel data so downstream viewers don't depend on
    respecting the orientation tag.
    """

    def convert_to_jpg(self, source: Path, target: Path) -> None:
        """
        Convert HEIC/HEIF to JPG preserving metadata and color profile.

        Args:
            source: Source image path (HEIC, HEIF, etc.)
            target: Target JPG path

        Raises:
            SnapJediConversionFailedError: If the image can't be decoded or saved
        """
        try:
            image = Image.open(source)
            icc_profile: bytes | None = image.info.get('icc_profile')
            image = ImageOps.exif_transpose(image).convert('RGB')

            image.save(target, quality=_JPEG_QUALITY, exif=image.getexif().tobytes(), icc_profile=icc_profile)
        except (UnidentifiedImageError, OSError) as e:
            raise SnapJediConversionFailedError(
                f'pillow-heif conversion failed: {e}', image_path=source, stderr=str(e)
            ) from e
