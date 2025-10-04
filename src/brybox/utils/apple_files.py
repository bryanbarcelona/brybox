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
        """
        Discover all Apple sidecar files associated with the given image.
        
        Returns:
            List of existing sidecar file paths (empty if none found).
            Includes regular, hidden, _O, and hidden _O variants.
        """
        sidecars = []
        stem = image_path.stem
        parent = image_path.parent

        # 1. Regular sidecars (non-hidden, same stem)
        for ext in AppleSidecarManager.SIDECAR_EXTENSIONS:
            for variant in [ext.lower(), ext.upper()]:
                candidate = parent / f"{stem}{variant}"
                if candidate.exists() and candidate != image_path:
                    sidecars.append(candidate)

        # 2. _O edited AAE files (non-hidden)
        o_stem = None
        if '_' in stem:
            o_stem = stem.replace('_', '_O', 1)
            for variant in ['.aae', '.AAE']:
                candidate = parent / f"{o_stem}{variant}"
                if candidate.exists():
                    sidecars.append(candidate)

        # 3. Hidden resource forks for original stem (._IMG_1234.*)
        for hidden in parent.glob(f"._{stem}.*"):
            if hidden.exists() and hidden != image_path and hidden not in sidecars:
                sidecars.append(hidden)

        # 4. Hidden resource forks for _O stem (._IMG_O1234.*)
        if o_stem:
            for hidden in parent.glob(f"._{o_stem}.*"):
                if hidden.exists() and hidden not in sidecars:
                    sidecars.append(hidden)

        return sidecars

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
                sidecar.unlink()
                deleted.append(sidecar)
                logger.debug(f"Deleted sidecar: {sidecar.name}")
            except Exception as e:
                logger.warning(f"Failed to delete sidecar {sidecar.name}: {e}")
        
        return deleted