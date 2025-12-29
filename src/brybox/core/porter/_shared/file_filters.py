from pathlib import Path


class ImageFileFilter:
    """Filter for image files (JPG, JPEG, HEIC, HEIF, PNG)."""

    def is_valid(self, path: Path) -> bool:
        # Skip system files
        if path.name.startswith('._'):
            return False
        return path.suffix.lower() in self.get_extensions()

    def get_extensions(self) -> set[str]:
        return {'.jpg', '.jpeg', '.heic', '.heif', '.png'}


class VideoFileFilter:
    """Filter for video files (MOV, MP4)."""

    def is_valid(self, path: Path) -> bool:
        if path.name.startswith('._'):
            return False
        return path.suffix.lower() in self.get_extensions()

    def get_extensions(self) -> set[str]:
        return {'.mov', '.mp4', '.3gp', '.3g2', '.m4v'}
