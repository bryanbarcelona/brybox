All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- `sticky` parameter in `log_and_display()` to display persistent terminal messages
- `final_message` option in `trackerator()` to show completion text after iteration
- `ConsoleLogger.finalize_progress()` for explicit progress bar shutdown with final message

### Changed
- Non-sticky log messages now correctly overwrite the current terminal line without artifacts
- Sticky messages automatically advance to a new line and remain visible after progress updates