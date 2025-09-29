"""
Doctopus PDF classification and filing system.
Production-grade, maintainable Python module with strict separation of concerns.
"""

import glob
import json
import logging
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from string import ascii_uppercase
from typing import Any, Dict, List, Optional, Type, Union

import pdfplumber
from dateutil import parser


from ..utils.health_check import is_healthy
from ..utils.logging import log_and_display, get_configured_logger, trackerator
from ..utils.config_loader import ConfigLoader as _ConfigLoader
from ..events.bus import publish_file_moved, publish_file_deleted

logger = get_configured_logger("DoctopusPrime")


def _load_doctopus_config(config_path: Optional[str] = None,
                          config: Optional[Dict] = None) -> Dict[str, Any]:
    """Return merged doctopus JSON configs."""
    if config is not None:
        return config
    config_path = config_path or "configs"
    return _ConfigLoader.load_configs(
        config_path=config_path,
        config_files={
            "categories": "doctopus_sorting_rules.json",
            "extraction_rules": "extraction_rules.json",
            "metadata_triggers": "metadata_triggers.json"
        }
    )

@dataclass
class _ProcessingContext:
    """Holds processing state for a single PDF."""
    pdf_filepath: str
    base_dir: str
    content: str = ""
    category: Optional[str] = None
    condensed_lines: List[str] = None
    document_date: Optional[str] = None
    invoice_id: Optional[str] = None
    output_filename: str = ""
    output_filepath: str = ""
    backup_path: Optional[str] = None
    is_new_file: bool = True


class _TextProcessor:
    """Handles PDF text extraction and line filtering."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
    def extract_content(self, pdf_path: str) -> str:
        """Extract text content from PDF."""
        try:
            with pdfplumber.open(pdf_path) as pdf:
                page = pdf.pages[0]
                text = page.extract_text()
            return text or ""
        except Exception:
            return ""
    
    def reduce_to_relevant_lines(self, content: str) -> List[str]:
        """Filter content to relevant lines based on extraction rules."""
        extraction_rules = self.config.get("extraction_rules", {})
        
        months = ["January", "Januar", "February", "Februar", "March", "März", "April", "May", "Mai", "June", "Juni", 
                 "July", "Juli", "August", "September", "October", "Oktober", "November", "December", "Dezember"]
        
        month_translations = {
            "January": "Januar", "February": "Februar", "March": "März", "May": "Mai", "June": "Juni", 
            "July": "Juli", "October": "Oktober", "Oct": "Okt", "December": "Dezember", "Dec": "Dez"
        }
        
        relevant_lines = []
        lines = content.split("\n")
        
        # Replace translated months
        for i, line in enumerate(lines):
            for key, value in month_translations.items():
                if key not in line:
                    lines[i] = lines[i].replace(value, key)
        
        for i, line in enumerate(lines):
            if any(substring in line for substring in month_translations.keys() | month_translations.values()):
                relevant_lines.append(line)
            
            for trigger_type, triggers in extraction_rules.items():
                for trigger in triggers:
                    if trigger in line:
                        if trigger_type == "same_line":
                            line = f"{trigger}{line.split(trigger)[-1]}"
                            relevant_lines.append(line.replace(trigger, "").replace(":", "").strip())
                            relevant_lines.append(line)
                        elif trigger_type == "previous_line" and i > 0:
                            relevant_lines.append(lines[i - 1])
                        elif trigger_type == "next_line" and i < len(lines) - 1:
                            relevant_lines.append(lines[i + 1])
            
            if any(month.lower() in line.lower() for month in months):
                relevant_lines.append(line)
        
        return relevant_lines if relevant_lines else lines


class _MetadataExtractor:
    """Extracts metadata like dates and invoice IDs."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
    def extract_date(self, lines: List[str]) -> Optional[str]:
        """Extract first valid date from lines."""
        date_patterns = self.config.get("metadata_triggers", {}).get("date_patterns", [])
        if not date_patterns:
            date_patterns = [r'\b(?:\d{1,2}(?:st|nd|rd|th)?[ ./-](?:\d{1,2}|[a-zA-Z]+)[ ./-]\d{2,4})\b']
        
        date_list = []
        for line in lines:
            for pattern in date_patterns:
                match = re.search(pattern, line)
                if match:
                    date_list.append(match.group())
        
        for date_str in date_list:
            try:
                parsed_date = self._parse_date(date_str)
                return parsed_date.strftime("%Y%m%d")
            except Exception:
                continue
        
        return None
    
    def _parse_date(self, line: str) -> Any:
        """Parse date string to datetime object."""
        line = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', line)
        
        if '.' in line:
            return parser.parse(line, dayfirst=True)
        elif '/' in line:
            return parser.parse(line, dayfirst=False)
        else:
            return parser.parse(line, dayfirst=True)
    
    def extract_invoice_id(self, lines: List[str]) -> Optional[str]:
        """Extract invoice ID from lines."""
        invoice_triggers = self.config.get("metadata_triggers", {}).get("invoice_id", [])
        
        for line in lines:
            for trigger in invoice_triggers:
                if trigger in line:
                    invoice_number = line.replace(trigger, "").replace(":", "").replace(". ", "").replace(")", "").strip()
                    invoice_number = invoice_number.split(" ")[0]
                    return invoice_number
        
        return None


class _SpecialCaseHandler:
    """Handles special case processing for specific categories."""
    
    def handle_special_cases(self, category: str, lines: List[str]) -> List[str]:
        """Apply special case handling based on category."""
        if category == "McDonalds Rechnung":
            return self._handle_mcdonalds(lines)
        
        return lines
    
    def _handle_mcdonalds(self, lines: List[str]) -> List[str]:
        """Handle McDonald's specific date format."""
        date_pattern = r'\b(0[1-9]|[12][0-9]|3[01])/(0[1-9]|1[0-2])/(19|20)\d{2}\b'
        
        for i, line in enumerate(lines):
            match = re.search(date_pattern, line)
            if match:
                lines[i] = match.group(0).replace("/", ".")
        
        return lines


class _FileMover:
    """Handles file operations and path management."""
    
    def __init__(self, base_dir: str, dry_run: bool = False):
        self.base_dir = base_dir
        self.dry_run = dry_run
        
    def get_backup_path(self, output_filepath: str) -> Optional[str]:
        """Generate backup path if backup drive exists."""
        for drive in ascii_uppercase:
            if os.path.exists(f"{drive}:\\log.backup"):
                if output_filepath:
                    backup_path = f"{drive}:{output_filepath.split(':')[1]}"
                    return backup_path
                break
        return None
    
    def build_output_path(self, category: str, filename: str, config: Dict[str, Any], pdf_filepath: str) -> Optional[str]:
        """Build the complete output file path."""
        categories = config.get("categories", {})
        
        if category not in categories:
            return None
            
        relative_path = categories[category].get("output_path", "")
        filepath = os.path.join(self.base_dir, relative_path, filename).replace("/", "\\")
        
        if not os.path.isfile(filepath):
            return filepath
        
        # Check if files have same content
        try:
            if self._files_have_same_content(pdf_filepath, filepath):
                return filepath
        except Exception:
            pass
        
        # Handle filename conflicts
        return self._resolve_filename_conflict(filepath)
    
    def _files_have_same_content(self, file1: str, file2: str) -> bool:
        """Check if two PDF files have the same content."""
        try:
            with pdfplumber.open(file1) as pdf1, pdfplumber.open(file2) as pdf2:
                content1 = pdf1.pages[0].extract_text() if pdf1.pages else ""
                content2 = pdf2.pages[0].extract_text() if pdf2.pages else ""
                return content1 == content2
        except Exception:
            return False
    
    def _resolve_filename_conflict(self, filepath: str) -> str:
        """Resolve filename conflicts by adding number suffix."""
        i = 1
        base, ext = os.path.splitext(filepath)
        
        while os.path.isfile(f"{base}({i}){ext}"):
            i += 1
            
        return f"{base}({i}){ext}"
    
    def move_file(self, source: str, destination: str) -> tuple[bool, bool]:
        """Move file from source to destination. Returns (success, is_new_file)."""
        if not os.path.exists(source):
            logger.warning(f"Source file does not exist: {source}")
            return False, False

        file_size = os.path.getsize(source)

        output_dir = os.path.dirname(destination)
        
        if self.dry_run:
            log_and_display(f"Would create directory: {output_dir}")
            if os.path.exists(destination):
                log_and_display(f"Would delete source file: {source}")
                return True, False
            else:
                log_and_display(f"Would move {source} to {destination}")
                return True, True
        
        # Create directory if needed
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        # Handle existing destination
        if os.path.exists(destination) and is_healthy(destination):
            os.remove(source)
            log_and_display(f"Destination exists. Deleted source file: {source}")
            publish_file_deleted(source, file_size)
            return True, False
        else:
            shutil.move(source, destination)
            if not is_healthy(destination):
                log_and_display(f"Moved file is corrupted: {destination}", level="error")
                return False, False
            
            log_and_display(f"Moved {source} to {destination}.")
            publish_file_moved(source, destination, file_size, True)
            return True, True
    
    def backup_file(self, source: str, backup_path: str) -> bool:
        """Create backup copy of file."""
        if not backup_path or not os.path.exists(source):
            return False
            
        if self.dry_run:
            log_and_display(f"Would backup {source} to {backup_path}")
            return True
            
        try:
            backup_dir = os.path.dirname(backup_path)
            if not os.path.exists(backup_dir):
                os.makedirs(backup_dir)
            
            shutil.copy(source, backup_path)
            log_and_display(f"Backed up {source} to {backup_path}.")
            return True
        except Exception as e:
            logger.error(f"Failed to backup {source}: {e}")
            return False


class DoctopusPrime:
    """Single PDF processor with configurable classification and filing."""
    
    def __init__(
        self,
        pdf_filepath: str,
        base_dir: Optional[str] = None,
        config_path: Optional[str] = None,
        config: Optional[Dict] = None,
        dry_run: bool = False
    ):
        """
        Initialize PDF processor.
        
        Args:
            pdf_filepath: Path to PDF file to process
            base_dir: Override target base directory
            config_path: Path to config directory
            config: Pre-loaded config dict
            dry_run: If True, no files are moved or deleted
        """
        self.pdf_filepath = pdf_filepath
        self.dry_run = dry_run

        # Load configuration
        self.config = _load_doctopus_config(config_path, config)

        # Determine base directory
        if base_dir:
            self.base_dir = base_dir
        elif "target_dir" in self.config:
            self.base_dir = self.config["target_dir"]
        else:
            self.base_dir = str(Path.home() / "BryBoxPDFs")
            
        # Initialize processors
        self.text_processor = _TextProcessor(self.config)
        self.metadata_extractor = _MetadataExtractor(self.config)
        self.special_handler = _SpecialCaseHandler()
        self.file_mover = _FileMover(self.base_dir, dry_run)
    
    def process(self) -> _ProcessingContext:
        """
        Process the PDF file through the complete pipeline.
        
        Returns:
            ProcessingContext with all extracted information
        """
        context = _ProcessingContext(
            pdf_filepath=self.pdf_filepath,
            base_dir=self.base_dir
        )
        
        # Extract text
        context.content = self.text_processor.extract_content(self.pdf_filepath)
        
        # Classify document
        context.category = self._classify_document(context.content)
        
        # Filter to relevant lines
        context.condensed_lines = self.text_processor.reduce_to_relevant_lines(context.content)
        
        # Handle special cases
        if context.category:
            context.condensed_lines = self.special_handler.handle_special_cases(
                context.category, context.condensed_lines
            )
        
        # Extract metadata
        context.document_date = self.metadata_extractor.extract_date(context.condensed_lines)
        context.invoice_id = self.metadata_extractor.extract_invoice_id(context.condensed_lines)
        
        filename_stem = self._get_filename_component(context.category)

        # Build output paths
        context.output_filename = self._build_filename(
            context.document_date, filename_stem, context.invoice_id
        )
        
        if context.category:
            context.output_filepath = self.file_mover.build_output_path(
                context.category, context.output_filename, self.config, self.pdf_filepath
            )
            context.backup_path = self.file_mover.get_backup_path(context.output_filepath)
        
        return context
    
    def _classify_document(self, content: str) -> Optional[str]:
        """Classify document based on content triggers."""
        categories = self.config.get("categories", {})
        
        for category, rules in categories.items():
            triggers = rules.get("triggers", [])
            if all(trigger in content for trigger in triggers):
                return category
        
        return None
    
    def _get_filename_component(self, category: str) -> str:
      """Return the filename associated with the given category."""
      categories = self.config.get("categories", {})
      category_config = categories.get(category, {})
      return category_config.get("filename", category)
        
    
    def _build_filename(self, date: Optional[str], category: Optional[str], invoice_id: Optional[str]) -> str:
        """Build output filename from components."""
        filename_parts = []
        
        if date:
            filename_parts.append(date)
        if category:
            filename_parts.append(category)
        if invoice_id:
            filename_parts.append(invoice_id)
            
        filename = " ".join(filename_parts).strip()
        return f"{filename}.pdf"
    
    def shuttle_service(self, include_backup: bool = False) -> bool:
        """
        Move file to organized location.
        
        Args:
            include_backup: Whether to create backup copy
            
        Returns:
            True if file was successfully processed
        """
        context = self.process()
        
        if not context.category or not context.output_filepath:
            return False
            
        # Move main file
        success, is_new = self.file_mover.move_file(
            context.pdf_filepath, context.output_filepath
        )
        
        if not success:
            return False
            
        context.is_new_file = is_new
        
        # Create backup if requested
        if include_backup and context.backup_path and not self.dry_run:
            self.file_mover.backup_file(context.output_filepath, context.backup_path)
        
        return True
    
    @property
    def category(self) -> Optional[str]:
        """Get document category."""
        context = self.process()
        return context.category
    
    @property
    def document_date(self) -> Optional[str]:
        """Get document date."""
        context = self.process()
        return context.document_date
    
    @property
    def invoice_id(self) -> Optional[str]:
        """Get invoice ID."""
        context = self.process()
        return context.invoice_id


class DoctopusPrimeNexus:
    """Batch PDF processor with shared configuration."""
    
    def __init__(
        self,
        dir_path: str,
        base_dir: Optional[str] = None,
        config_path: Optional[str] = None,
        config: Optional[Dict] = None,
        dry_run: bool = False,
        processor_class: Type[DoctopusPrime] = DoctopusPrime
    ):
        """
        Initialize batch processor.
        
        Args:
            dir_path: Directory containing PDFs to process
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
        self.config = _load_doctopus_config(config_path, config)

    def process_all(
        self,
        include_backup: bool = False,
        progress_bar: bool = True,
    ) -> Dict[str, bool]:
        """
        Process all PDF files in directory.

        Args:
            include_backup: Whether to create backup copies
            progress_bar: Whether to show progress bar

        Returns:
            Dict mapping file paths to success status
        """
        pdf_files = glob.glob(os.path.join(self.dir_path, "*.pdf"))
        results = {}

        log_and_display(f"Processing {len(pdf_files)} PDF file(s) in {self.dir_path}", sticky=True)
        pdf_files = trackerator(pdf_files, description="Processing PDFs", final_message="All PDFs processed!") if progress_bar else pdf_files

        for pdf_file in pdf_files:
            
            try:
                processor = self.processor_class(
                    pdf_filepath=pdf_file,
                    base_dir=self.base_dir,
                    config=self.config,
                    dry_run=self.dry_run
                )
                
                success = processor.shuttle_service(include_backup=include_backup)
                results[pdf_file] = success
                
            except Exception as e:
                if progress_bar:
                    log_and_display(f"Error processing {pdf_file}: {e}")
                else:
                    log_and_display(f"Error processing {pdf_file}: {e}")
                results[pdf_file] = False

        return results