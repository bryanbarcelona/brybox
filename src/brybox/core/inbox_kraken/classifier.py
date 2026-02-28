import re
from enum import Enum, auto
from typing import Any

from brybox.core.inbox_kraken.helpers import classify_link
from brybox.core.models.email import EmailMeta


class Tag(Enum):
    """Actions the Kraken can perform based on classification."""

    DELETE = auto()
    DOWNLOAD_PDF = auto()
    DOWNLOAD_ATTACH = auto()
    MANUAL_CLICK = auto()
    IGNORE = auto()
    DOWNLOAD_AUDIO = auto()
    TECHEM = auto()
    KFW = auto()


class EmailClassifier:
    """
    Matches EmailMeta against JSON rules using smart string/regex matching.
    """

    def __init__(self, rules: list[dict[str, Any]]):
        self.rules = rules

    def classify(self, meta: EmailMeta) -> Tag:
        """
        Returns the first matching Tag. Skips rules with invalid action names.
        """
        for rule in self.rules:
            if self._matches_rule(meta, rule):
                action_str = rule.get('action', '').upper()
                try:
                    return Tag[action_str]
                except KeyError:
                    # Skip rules with typos in 'action' to prevent engine crash
                    continue

        return Tag.IGNORE

    def _matches_rule(self, meta: EmailMeta, rule: dict[str, Any]) -> bool:
        """
        Checks all conditions. All present conditions must be True (AND logic).
        """
        # 1. Smart Sender Match (Regex support)
        if 'sender' in rule:
            if not self._smart_match(rule['sender'], meta.sender):
                return False

        # 2. Smart Subject Match (Regex support)
        if 'subject' in rule:
            if not self._smart_match(rule['subject'], meta.subject):
                return False

        # 3. PDF Attachment Requirement
        if rule.get('has_pdf_attachment'):
            if not any(a.lower().endswith('.pdf') for a in meta.attachments):
                return False

        # 4. Embedded Link Strictness (Only match if it's a direct PDF)
        if rule.get('embedded_link'):
            if not (meta.invoice_link and classify_link(meta.invoice_link) == 'PDF'):
                return False

        return True

    def _smart_match(self, pattern: str, text: str) -> bool:
        """
        Attempts a regex match. If pattern is not valid regex or no match,
        falls back to a simple case-insensitive substring check.
        """
        if not pattern or not text:
            return False

        pattern_lower = pattern.lower()
        text_lower = text.lower()

        # Try as Substring first (most common/intended case)
        if pattern_lower in text_lower:
            return True

        # Fallback to Regex for advanced rules
        try:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        except re.error:
            pass  # Not a valid regex, ignore

        return False

    def is_candidate(self, meta: EmailMeta) -> bool:
        """
        Kicks out any email whose sender isn't explicitly in our JSON rules.
        """
        for rule in self.rules:
            if 'sender' in rule and self._smart_match(rule['sender'], meta.sender):
                return True
        return False
