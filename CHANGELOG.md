All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- **PixelPorter**: Photo ingestion module (refactored from pre-repo legacy DropBoss code)
  - Protocol-based architecture with `FileProcessor` and `Deduplicator` interfaces
  - Dry-run mode, collision detection, and automatic filename resolution
  - Full Apple sidecar support:
    - Discovers and migrates regular, hidden (`._`), `_O` edited, and hidden `_O` sidecars
    - Preserves Apple naming conventions during staging (e.g., `._IMG_1234.HEIC` → `._new.HEIC`)
    - Encapsulated in `AppleSidecarManager` with discovery, renaming, and deletion utilities
  - Module-specific config via `configs/pixelporter_paths.json`
  - Public API: `from brybox import push_photos`
  - now publishes `FileCopiedEvent` after successful copy + verification
- `models.py`: new `FileCopiedEvent` dataclass enforcing dual-path, dual-size and
  dual-health validation; only instantiated after copy & verification succeed.
- `bus.py`: `publish_file_copied()` convenience wrapper so callers can emit the
  event in one line while guaranteeing health/size checks are done upstream.
- `verifier.py`: `DirectoryVerifier` now subscribes/unsubscribes to copy events.
- `FileCopiedEvent`, updating expected state (source preserved, destination added) while remaining
  path-only—health & size fields are ignored by design.

### Technical
- Added `core/pixelporter/` submodule:
  - `protocols.py`: Interface definitions
  - `pixelporter.py`: Orchestration logic
  - `adapters.py`: Temporary `SnapJediAdapter`
  - `apple_files.py`: Apple sidecar handling (discovery, renaming, deletion)
- Supports pluggable processors via protocol injection

### Fixed
- Sidecar helper loop now appends `target_path` unconditionally, yielding correct
  counts in both dry-run and live modes; remaining `print()` calls migrated to
  `log_and_display()` for consistent user output.
  

## [0.1.0] - 2025-10-01

### Added
- `sticky` parameter in `log_and_display()` to display persistent terminal messages
- `final_message` option in `trackerator()` to show completion text after iteration
- `ConsoleLogger.finalize_progress()` for explicit progress bar shutdown with final message
- **web_marionette/models.py**: DownloadResult dataclass for structured results
- **web_marionette/__init__.py**: Package initialization with proper exports
- Constants for configuration values (URLs, timeouts, poll intervals)
- `_create_browser_context()` for consistent browser setup
- `_failure_result()` and `_build_result()` helper methods
- Better separation between critical and non-critical operations (e.g., cookie banner)
- Automatic retry for failed document downloads (KFW only, 1 retry attempt)
- `_failure_result()` and `__build_result()` helper method for consistent result construction

### Changed
- Non-sticky log messages now correctly overwrite the current terminal line without artifacts
- Sticky messages automatically advance to a new line and remain visible after progress updates
- **web_marionette**: Restructured as dedicated package with scrapers.py module
  - Complete refactor from functions to class-based architecture
  - New `BaseScraper` abstract base class with common scraping patterns
  - `TechemScraper` and `KfwScraper` as concrete implementations
  - Separation of configuration (init) from execution (download method)
- **KFW downloads**: Now downloads all available documents instead of just the first one
- **Error handling**: Replace boolean returns with structured DownloadResult objects
  - Track total found, downloaded, failed counts
  - Capture specific error messages for each failure
  - Maintains backward compatibility via `__bool__` method- **Request capture**: Dynamic polling (100ms intervals, 10s timeout) replaces static 3s wait
  - Granular error reporting with specific failure context
  - Distinguish between login failures, navigation issues, and download problems
  - Each failure type logged with specific error message for easier debugging
- **Logging**: Refined for better UX
  - Ephemeral progress updates (not logged to file)
  - Persistent success/failure logs with details
  - Handlers report detailed outcomes (e.g., "Downloaded 3/5 documents")
- **Success semantics**: Stricter definition of success
  - Now requires ALL documents downloaded successfully (was: at least one)
  - Partial success (e.g., 3/5 docs) now returns `success=False`
  - Prevents premature email deletion on partial failures
- **Code organization**: Extracted procedural logic into focused private methods
  - `_login()`, `_download_pdf()`, `_capture_download_request()`, etc.
  - `_execute_download_workflow()`, `_attempt_login()`, `_attempt_navigation()` for flat control flow
  - Keeps main `download()` method readable while handling complex flows
  - Error handling remains visible in main orchestration method

#### Removed
- Dead code: unused download_kfw_single_document helper function
- Unused imports: DoctopusPrime, os, dotenv, dataclasses
- Commented-out development code

#### Fixed
- Browser resources now always cleaned up via try/finally pattern