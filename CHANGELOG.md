All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

## [0.2.0] - 2025-10-10

### Added
- **SnapJedi**: Image-normalization submodule (newly extracted from monolithic legacy codebase)
  - `ImageConverter` ABC + `ImageMagickConverter` implementation
    - Auto-detects ImageMagick 6 vs 7 CLI syntax
    - 30 s subprocess timeout, raises `ConversionError` on failure
    - Preserves EXIF, GPS, color profiles during HEIC→JPG conversion
  - `MetadataReader`
    - Wraps exiftool (bundled or PATH)
    - Returns `ImageMetadata` dataclass: creation date, GPS lat/lon/alt, timezone, UTC offset
  - `PathStrategy`
    - Generates timestamp-based filename (`%Y%m%d %H%M%S.jpg`) from creation date ± offset
    - Auto-resolves conflicts with `(1)`, `(2)`… suffixes
  - `SnapJedi` orchestrator
    - Single entry: `open(path)` → `process()` pipeline
    - Deletes Apple sidecars pre- and post-process
    - Converts HEIC/HEIF → JPG, health-checks result, deletes original on success
    - Deduplicates against existing target (byte-for-byte compare)
    - Renames to final timestamp name, publishes `FileRenamedEvent` / `FileDeletedEvent`
    - Returns `ProcessResult` (success, target_path, is_healthy, error_message)

  - **Module structure**: `core/snap_jedi/` submodule
    - `converter.py`: `ImageConverter` ABC and `ImageMagickConverter` implementation
    - `metadata.py`: `MetadataReader` class and `ImageMetadata` dataclass
    - `naming.py`: `PathStrategy` static utilities for timestamp-based filenames
    - `snapjedi.py`: Main `SnapJedi` orchestrator class
    - `__init__.py`: Clean public API exports

- **PixelPorter**: Photo ingestion module (refactored from pre-repo legacy DropBoss code)
  - Protocol-based architecture with `FileProcessor` and `Deduplicator` interfaces
  - Three-phase pipeline: staging → deduplication/timestamp fixing → processing/cleanup
  - Dry-run mode, collision detection, and automatic filename resolution
  - Module-specific config via `configs/pixelporter_paths.json`
  - Public API: `from brybox import push_photos`
  - Supports pluggable processors and deduplicators via protocol injection
  
  - **Phase 1**: Collision-safe staging with temporary filenames
    - Publishes `FileCopiedEvent` after successful copy + verification
  
  - **Phase 2**: Deduplication and timestamp uniqueness
    - `HashDeduplicator`: SHA-256 based duplicate detection (enabled by default)
    - Automatic EXIF timestamp adjustment to prevent filename collisions
    - Event publishing for duplicate deletions (DirectoryVerifier integration)
    - `deduplicator` parameter: `None` (default), custom instance, or `False` (disabled)
  
  - **Phase 3**: SnapJedi processing and source cleanup
    - `_process_and_cleanup()`: Orchestrates temp file processing through SnapJedi adapter
    - Validates `ProcessResult.success` and `ProcessResult.is_healthy` before deletions
    - Only deletes source files after confirmed successful processing of staged temps
    - Per-file error isolation: failures preserve both temp and source for debugging
    - Comprehensive exception handling with error accumulation in `PushResult.errors`
    - Publishes `FileRenamedEvent` for temp → final renames
    - Conditionally executes only if `processor_class` provided
    - Logs clear message when no processor specified: files remain staged with temp names
  
  - **Module structure**: `core/pixelporter/` submodule
    - `protocols.py`: `FileProcessor` and `Deduplicator` interface definitions
    - `orchestrator.py`: Main `push_photos()` entry point, `PushResult`, config/defaults
    - `staging.py`: Phase 1 implementation
    - `deduplication.py`: Phase 2a implementation
    - `timestamps.py`: Phase 2b implementation
    - `processing.py`: Phase 3 implementation
    - `adapters.py`: Temporary `SnapJediAdapter` (pre-refactor bridge)
    - `apple_files.py`: Apple sidecar handling utilities
    - `__init__.py`: Clean public API exports

- **Full Apple sidecar support**:
  - Discovers and migrates regular, hidden (`._`), `_O` edited, and hidden `_O` sidecars
  - Preserves Apple naming conventions during staging (e.g., `._IMG_1234.HEIC` → `._new.HEIC`)
  - Encapsulated in `AppleSidecarManager` with discovery, renaming, and deletion utilities
  - `AppleSidecarManager.delete_image_with_sidecars()`: Atomic deletion of image + sidecars
    - Publishes `file_deleted` events for each removed file with accurate sizes
    - Returns list of deleted paths for verification

- **Event System Enhancements**:
  - `FileCopiedEvent` dataclass: Enforces dual-path, dual-size, and dual-health validation
    - Only instantiated after copy & verification succeed
  - `FileRenamedEvent` dataclass: Atomic rename operations
    - Uses `old_path`/`new_path` semantics (vs source/destination) to reflect single-file nature
    - Validation ensures destination exists, is healthy, and has non-negative size
  - `publish_file_copied()` wrapper in `bus.py` for emitting copy events
  - `publish_file_renamed()` wrapper in `bus.py` for emitting rename events

- **HashDeduplicator** in `utils/deduplicator.py`: SHA-256-based content comparison

- **PushResult tracking**: `processed`, `failed`, and `errors` now populated across all phases
  - Summary logging at pipeline completion with error details (first 5 shown)

### Changed
- `DirectoryVerifier` now subscribes to copy and rename events, updating expected state
  - Remains path-only by design—health & size fields ignored
- Phase 3 skipped in dry-run mode (consistent with Phases 2a/2b - no files staged to process)

### Known Issues
- HEIC files use size-only health checks in Phase 1 staging
  - Not yet registered in `_FILETYPE_CHECKERS` mimetype dispatcher
  - Will be addressed when HEIC validation is implemented in health checker utilities


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