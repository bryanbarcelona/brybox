<p align="center">
  <img src="images/banner.gif" alt="Header GIF">
</p>

# brybox

A personal automation toolkit for PC organization. Brybox replaces a pile of
one-off scripts with a single, cohesive library that sorts PDFs, normalizes
photo and video libraries, triages an email inbox, and pulls documents out of
web portals that don't offer a real API — all driven by config files instead
of hardcoded paths.

It is not a general-purpose framework: several subsystems are wired to
specific, personal accounts (a Gmail inbox, a handful of German insurance /
banking / utility portals, Amazon.de). Treat it as a working example of the
architecture as much as a tool to run as-is.

## What it does

| Subsystem | Problem it solves |
|---|---|
| **PixelPorter** / **MotionPorter** | Ingest a camera-roll dump: stage → dedup → normalize filenames/metadata for photos and videos in one pass. |
| **SnapJedi** | Convert HEIC/HEIF to JPG and rename to a timestamped, timezone-aware filename. Deletes Apple sidecar files (`.aae`, `.xmp`, `._*`). |
| **VideoSith** | Convert MOV to MP4 (stream-copy, falls back to re-encode), rewrite EXIF/GPS/creation-date metadata, rename by timestamp. |
| **Doctopus** | Classify PDFs (bills, statements, ...) by keyword triggers, extract a date and invoice ID, file them into category folders. |
| **DoiSmith** | Resolve an academic PDF's DOI against the CrossRef API and rename it `Author (Year) - Title.pdf`. |
| **Audiora** | Sort loose audio recordings into `category/date session_name.ext` using trigger-word rules and EXIF-style metadata. |
| **ZipWarden** | Extract and flatten ZIP archives (e.g. bank statement bundles) before handing the contents to another processor. |
| **InboxKraken** | Poll a Gmail inbox over IMAP, classify messages by rule, and dispatch to a handler: download a PDF/attachment, grab a Dropbox link, trigger a web scraper, or delete. |
| **web_marionette** | Playwright-driven browser automation that logs into real portals (Gothaer, KfW, Techem, Amazon.de) and downloads documents a plain HTTP scraper couldn't reach. |

Every file-mutating operation across these subsystems publishes to an
internal event bus; `DirectoryVerifier` subscribes to it and can diff the
events a batch job claimed to perform against what's actually on disk —
useful for confirming a pipeline run did what it said it did.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) for dependency management
- System binaries on `PATH`: `exiftool`, ImageMagick, `ffmpeg`
- Playwright's Chromium build (not installed by `uv sync` — see below)

## Installation

```bash
git clone https://github.com/bryanbarcelona/brybox.git
cd brybox
uv sync
uv run playwright install chromium
```

## Configuration

Brybox is entirely config- and env-var-driven; nothing is hardcoded to a
path or account.

**Config files** — copy each template under `configs/` and drop the
`.example`, then fill in real values:

| Template | Feeds |
|---|---|
| `audiora_rules.example.json` | Audiora category/trigger rules |
| `doctopus_sorting_rules.example.json` | Doctopus category/trigger rules |
| `extraction_rules.example.json` | Doctopus date/invoice-ID extraction regexes |
| `metadata_triggers.example.json` | Doctopus metadata trigger keywords |
| `email_rules.example.json` | InboxKraken classification rules |
| `email_delete_list.example.json` / `.example.csv` | InboxKraken unconditional-delete senders |
| `paths.example.json` | Email save directory, DoiSmith literature directory |
| `pixelporter_paths.example.json` | PixelPorter / MotionPorter source and target folders |

Files are resolved in priority order: an explicit path, then the OS user
config directory (`platformdirs.user_config_dir('brybox')`), then
`./configs` relative to the working directory. A single logical config can
be split across multiple files/formats (e.g. both `.json` and `.csv`) — the
loader merges them and the most recently modified source wins on conflicts.

**Environment variables** — create a `.env` file (loaded via
`python-dotenv`):

```env
# Gmail IMAP (InboxKraken) — required, needs a Google App Password
EMAIL=
APP_PWD=
IMAP_SERVER=imap.gmail.com
IMAP_PORT=993

# web_marionette portal logins — only required for the scrapers you use
USER_MAIN=
TECHEM_PWD=
USER_KFW=
KFW_PWD=
USER_GOTHAER=
GOTHAER_PWD=
USER_AMAZON=
AMAZON_PWD=
AMAZON_TOTP_SECRET=
```

## Usage

Everything is re-exported from the package root:

```python
from brybox import push_photos, push_videos, SnapJedi, Doctopus, InboxKraken

# Ingest a camera-roll dump: stage, dedup, normalize
push_photos('D:/Camera Uploads', 'D:/Photos')
push_videos('D:/Camera Uploads', 'D:/Videos')

# Sort a single PDF into its category folder
DoctopusPrime('D:/Downloads/invoice.pdf').process()

# Triage the inbox without touching anything (dry_run is the default)
with InboxKraken() as kraken:
    kraken.preview()
```

Batch variants follow a `<Thing>Nexus` naming pattern
(`AudioraNexus`, `DoctopusPrimeNexus`, `ZipWardenNexus`, ...) — same
processing logic, applied to every file in a directory, with per-file error
isolation so one bad file doesn't abort the run.

## Development

```bash
uv sync --all-extras --dev
uv run ruff check .
uv run ruff format .
uv run ty check
uv run pytest
```

Commits follow [Conventional Commits](https://www.conventionalcommits.org/);
`commitizen` derives the version bump and changelog entry from commit
messages, and releases to PyPI are cut automatically from `main` via GitHub
Actions.
