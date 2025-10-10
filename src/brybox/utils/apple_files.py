"""Apple sidecar file management utilities.

Handles Apple-specific companion files that travel with photos:
- .xmp (metadata)
- .aae (Apple Photos adjustments, with _O pattern variants)
- .mov (Live Photo video component)
- .heif (alternate HEIC extension)
- ._ prefixed files (resource fork metadata on non-Mac filesystems)
"""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import List, ClassVar

from .logging import log_and_display, get_configured_logger
from ..events.bus import publish_file_deleted

logger = get_configured_logger("AppleFiles")

@dataclass(frozen=True)
class SidecarRename:
    """
    Represents a sidecar file and its correctly renamed target filename.
    
    `new_filename` is just the filename (e.g., "safe.mov"), NOT a full path.
    """
    original: Path
    new_filename: str


@dataclass(frozen=True)
class RenamedSidecarGroup:
    """
    Result of renaming all sidecars associated with an image.
    
    Provides a flat list of renames. If future logic requires categorization
    (e.g., hidden vs. regular), add helper methods — do not split the list now.
    """
    renames: List[SidecarRename]


class AppleSidecarManager:
    """
    Encapsulates Apple-specific sidecar file discovery and renaming logic.
    
    Handles:
      - Regular sidecars: IMG_1234.mov, IMG_1234.aae
      - Hidden resource forks: ._IMG_1234.HEIC, ._IMG_1234.aae
      - _O edited AAEs: IMG_O1234.aae
      - Hidden _O edited AAEs: ._IMG_O1234.aae
    
    This class is stateless and thread-safe.
    """
    
    # Known Apple sidecar extensions (case-insensitive)
    SIDECAR_EXTENSIONS: ClassVar[set[str]] = {'.aae', '.mov', '.xmp'}


    @staticmethod
    def find_sidecars(image_path: Path) -> List[Path]:
        """Return *unique* existing sidecar paths for `image_path`."""
        sidecars: set[Path] = set()          # canonical paths
        stem = image_path.stem
        parent = image_path.parent

        # helper: add only if it exists and is not the image itself
        def _add(candidate: Path) -> None:
            if candidate.exists() and candidate != image_path:
                sidecars.add(candidate.resolve())

        # 1. Regular sidecars (case-insensitive filesystems will auto-dedup via resolve)
        for ext in AppleSidecarManager.SIDECAR_EXTENSIONS:
            _add(parent / f"{stem}{ext.lower()}")
            _add(parent / f"{stem}{ext.upper()}")

        # 2. _O edited AAE files
        if '_' in stem:
            o_stem = stem.replace('_', '_O', 1)
            _add(parent / f"{o_stem}.aae")
            _add(parent / f"{o_stem}.AAE")

        # 3. Hidden resource forks (original stem)
        for hidden in parent.glob(f"._{stem}.*"):
            _add(hidden)

        # 4. Hidden resource forks (_O stem)
        if '_' in stem:
            for hidden in parent.glob(f"._{o_stem}.*"):
                _add(hidden)

        return list(sidecars)

    @staticmethod
    def get_renamed_sidecars(image_path: Path, new_stem: str) -> RenamedSidecarGroup:
        """
        Compute correct renamed filenames for all sidecars of an image.
        
        Renaming preserves Apple's naming conventions:
          - IMG_1234.mov          → new_stem.mov
          - ._IMG_1234.HEIC       → ._new_stem.HEIC
          - IMG_O1234.aae         → new_stem_O1234.aae
          - ._IMG_O1234.aae       → ._new_stem_O1234.aae
        
        Args:
            image_path: Path to the main image file (e.g., IMG_1234.HEIC)
            new_stem: The new base name to use (e.g., "pixelporter_temp_xyz")
            
        Returns:
            RenamedSidecarGroup containing original → new filename mappings.
            
        Raises:
            ValueError: If a sidecar doesn't match any known pattern.
        """
        original_stem = image_path.stem
        sidecars = AppleSidecarManager.find_sidecars(image_path)
        renames = []

        # Precompute _O stems if applicable
        o_stem = original_stem.replace('_', '_O', 1) if '_' in original_stem else None
        new_o_stem = new_stem.replace('_', '_O', 1) if o_stem else None

        for sidecar in sidecars:
            name = sidecar.name

            # Case 1: Hidden original (._IMG_1234.xxx)
            if name.startswith(f"._{original_stem}"):
                new_name = f"._{new_stem}{name[len(f'._{original_stem}'):]}"
            
            # Case 2: Hidden _O edited (._IMG_O1234.xxx)
            elif o_stem and name.startswith(f"._{o_stem}"):
                new_name = f"._{new_o_stem}{name[len(f'._{o_stem}'):]}"
            
            # Case 3: Non-hidden _O edited (IMG_O1234.aae)
            elif o_stem and name.startswith(o_stem):
                new_name = f"{new_o_stem}{name[len(o_stem):]}"
            
            # Case 4: Regular sidecar (IMG_1234.xxx)
            elif name.startswith(original_stem):
                new_name = f"{new_stem}{name[len(original_stem):]}"
            
            else:
                # This should not occur if find_sidecars is correct,
                # but guard against future Apple surprises.
                raise ValueError(
                    f"Unrecognized sidecar pattern: {name} "
                    f"(original stem: {original_stem})"
                )

            renames.append(SidecarRename(sidecar, new_name))

        return RenamedSidecarGroup(renames)
    
    @staticmethod
    def delete_sidecars(image_path: Path) -> list[Path]:
        """
        Delete all Apple sidecar files associated with an image.
        
        Args:
            image_path: Path to the primary image file
            
        Returns:
            List of deleted sidecar file paths
            
        Example:
            >>> deleted = AppleSidecarManager.delete_sidecars(Path("IMG_1234.jpg"))
            >>> print(f"Deleted {len(deleted)} sidecars")
        """
        sidecars = AppleSidecarManager.find_sidecars(image_path)
        deleted = []
        
        for sidecar in sidecars:
            try:
                size = sidecar.stat().st_size
                sidecar.unlink()
                publish_file_deleted(str(sidecar), size)
                deleted.append(sidecar)
                log_and_display(f"Deleted sidecar: {sidecar.name}")
            except Exception as e:
                log_and_display(f"Failed to delete sidecar {sidecar.name}: {e}")
        
        return deleted
    
    @staticmethod
    def delete_image_with_sidecars(
        image_path: Path,
    ) -> list[Path]:
        """
        Delete an image file and all its Apple sidecars.
        
        Args:
            image_path: Path to the primary image file
            publish_events: If True, publish file_deleted events for each deletion
            
        Returns:
            List of all deleted file paths (image + sidecars)
            
        Example:
            >>> deleted = AppleSidecarManager.delete_image_with_sidecars(
            ...     Path("source/IMG_1234.HEIC"),
            ...     publish_events=True
            ... )
            >>> print(f"Deleted {len(deleted)} files")
        """
        deleted = []
        
        # Find all sidecars first
        sidecars = AppleSidecarManager.find_sidecars(image_path)
        
        # Delete sidecars
        for sidecar in sidecars:
            try:
                size = sidecar.stat().st_size
                sidecar.unlink()
                deleted.append(sidecar)
                publish_file_deleted(str(sidecar), size)
                log_and_display(f"Deleted sidecar: {sidecar.name}")
            except Exception as e:
                log_and_display(f"Failed to delete sidecar {sidecar.name}: {e}")

        # Delete primary image
        try:
            size = image_path.stat().st_size
            image_path.unlink()
            deleted.append(image_path)
            publish_file_deleted(str(image_path), size)
            log_and_display(f"Deleted image: {image_path.name}")
        except Exception as e:
            log_and_display(f"Failed to delete image {image_path.name}: {e}")

        return deleted