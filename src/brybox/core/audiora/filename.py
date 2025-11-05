"""
Filename processing: pattern matching, cleanup, and session name extraction.
"""

import re
from typing import Dict, List, Optional, Any

from ...utils.logging import get_configured_logger


class _FilenameProcessor:
    """Handles filename pattern matching and cleanup operations."""
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize filename processor.
        
        Args:
            config: Configuration dictionary with category rules
        """
        self.config = config
    
    def classify_audio(self, filename: str) -> Optional[str]:
        """
        Classify audio file based on filename triggers.
        
        Args:
            filename: Original filename
            
        Returns:
            Category name if matched, None otherwise
        """
        categories = self.config.get("categories", {})
        filename_lower = filename.lower()
        
        for category, rules in categories.items():
            triggers = rules.get("triggers", [])
            trigger_mode = rules.get("trigger_mode", "all")  # Default to "all" (AND)
            
            if trigger_mode == "any":
                # OR logic: at least one trigger must match
                if any(trigger.lower() in filename_lower for trigger in triggers):
                    return category
            else:
                # AND logic: all triggers must match (default, safer)
                if all(trigger.lower() in filename_lower for trigger in triggers):
                    return category
        
        return None
    
    def extract_session_name(self, filename: str, category: str) -> str:
        """
        Extract clean session name from filename based on category rules.
        
        Applies all cleanup rules from config:
        1. Remove patterns (case-insensitive)
        2. Apply normalization patterns (case-sensitive for numbers)
        3. Clean up extra whitespace
        
        Args:
            filename: Original filename (without extension)
            category: Category name for rule lookup
            
        Returns:
            Cleaned session name
        """
        categories = self.config.get("categories", {})
        
        if category not in categories:
            return filename
        
        rules = categories[category]
        cleanup = rules.get("filename_cleanup", {})
        
        session_name = filename
        
        # Apply removal patterns (case-insensitive)
        remove_patterns = cleanup.get("remove_patterns", [])
        for pattern in remove_patterns:
            session_name = re.sub(pattern, "", session_name, flags=re.IGNORECASE)
        
        # Apply normalization patterns (case-sensitive for precision)
        normalize_patterns = cleanup.get("normalize_patterns", {})
        for pattern, replacement in normalize_patterns.items():
            session_name = re.sub(pattern, replacement, session_name)
        
        # Clean up whitespace
        session_name = self._clean_whitespace(session_name)
        
        # Capitalize each word, preserving internal capitalization when possible
        session_name = " ".join(
            word[0].upper() + word[1:] if word else ""
            for word in session_name.split(" ")
        )

        return session_name
    
    def _clean_whitespace(self, text: str) -> str:
        """
        Clean up excessive whitespace in text.
        
        - Collapses multiple spaces to single space
        - Strips leading/trailing whitespace
        
        Args:
            text: Text to clean
            
        Returns:
            Cleaned text
        """
        # Collapse multiple spaces
        text = re.sub(r'\s+', ' ', text)
        # Strip leading/trailing
        text = text.strip()
        return text
    
    def build_filename(self, date: Optional[str], session_name: str, 
                      category: str, extension: str = ".m4a") -> str:
        """
        Build output filename from components.
        
        Args:
            date: Date in YYYYMMDD format
            session_name: Cleaned session name
            category: Category name for template lookup
            extension: File extension (default: .m4a)
            
        Returns:
            Complete filename with extension
        """
        categories = self.config.get("categories", {})
        
        if category not in categories:
            # Fallback: simple concatenation
            parts = [p for p in [date, session_name] if p]
            return f"{' '.join(parts)}{extension}"
        
        template = categories[category].get("rename_template", "{date} {session_name}")
        
        # Replace template variables
        filename = template.format(
            date=date or "",
            session_name=session_name or ""
        )
        
        # Clean up any double spaces from missing components
        filename = self._clean_whitespace(filename)
        
        return f"{filename}{extension}"
