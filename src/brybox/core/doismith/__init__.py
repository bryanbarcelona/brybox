"""
DoiSmith — academic PDF renaming pipeline.

Resolves DOIs from PDF content, looks up metadata via CrossRef,
and renames files to '{title} - {author} ({year}).pdf'.
"""

from brybox.core.doismith.doismith import DoiSmithNexus, DoiSmithPrime

__all__ = ['DoiSmithPrime', 'DoiSmithNexus']
