from __future__ import annotations

import csv
from pathlib import Path

from brybox.core.inbox_kraken.classifier import EmailClassifier, Tag
from brybox.core.inbox_kraken.fetcher import EmailFetcher
from brybox.utils.logging import log_and_display

# ---------------------------------------------------------------------------
# Internal classification
# ---------------------------------------------------------------------------


def _classify_light(sender: str, subject: str, rules: list[dict]) -> Tag:
    """
    Classifies an email using sender/subject only — no attachment or link checks.
    Rules are already fully normalized by the config pipe (delete list entries
    included as standard DELETE rule dicts). Iterates in rule order, first match wins.
    """
    for rule in rules:
        if _rule_matches_light(sender, subject, rule):
            action_str = rule.get('action', '').upper()
            try:
                return Tag[action_str]
            except KeyError:
                continue

    return Tag.IGNORE


def _rule_matches_light(sender: str, subject: str, rule: dict) -> bool:
    """
    Evaluates only sender and subject conditions from a rule.
    Intentionally skips has_pdf_attachment and embedded_link — light fetch only.
    Reuses EmailClassifier._smart_match for consistent case/regex behaviour.
    """
    if 'sender' in rule and not EmailClassifier._smart_match(rule['sender'], sender):
        return False
    return 'subject' not in rule or EmailClassifier._smart_match(rule['subject'], subject)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def preview_inbox(
    fetcher: EmailFetcher,
    rules: list[dict],
    mailbox: str = 'INBOX',
    limit: int | None = None,
    only_uids: list[int] | None = None,
) -> list[dict[str, str]]:
    """
    Fetches inbox headers in a single IMAP round trip and classifies each
    email using sender/subject rules only. No handlers are executed, no
    messages are modified or deleted.

    Args:
        fetcher:    Initialised EmailFetcher bound to an active IMAP connection.
        rules:      Fully normalized rule list from the config pipe — includes
                    migrated delete list entries as standard rule dicts.
        mailbox:    IMAP mailbox to inspect (default: 'INBOX').
        limit:      Optional cap — takes the last N UIDs, consistent with run().
        only_uids:  Optional explicit UID subset to restrict to.

    Returns:
        List of dicts with keys: uid, handler, sender, subject.
    """
    uids = fetcher.fetch_uids(mailbox=mailbox)
    if not uids:
        return []

    metas = fetcher.get_light_meta_batch(uids, limit=limit, only_uids=only_uids)
    if not metas:
        return []

    rows: list[dict[str, str]] = []
    for meta in metas:
        tag = _classify_light(meta.sender, meta.subject, rules)
        rows.append({
            'uid': str(meta.uid),
            'handler': tag.name,
            'sender': meta.sender,
            'subject': meta.subject,
        })

    return rows


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

_FIELDNAMES = ['uid', 'handler', 'sender', 'subject']


def write_preview_csv(rows: list[dict[str, str]], path: Path | str) -> Path:
    """Writes preview rows to a CSV file. Returns the resolved absolute path."""
    resolved = Path(path).resolve()
    with resolved.open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=_FIELDNAMES, delimiter=';')
        writer.writeheader()
        writer.writerows(rows)
    return resolved


def print_preview(rows: list[dict[str, str]]) -> None:
    """Prints preview rows as a tabular list to stdout."""
    print(f'{"UID":<8} {"HANDLER":<16} {"SENDER"} | {"SUBJECT"}')
    print('-' * 80)
    for row in rows:
        print(f'{row["uid"]:<8} {row["handler"]:<16} {row["sender"]} | {row["subject"]}')


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_preview(
    fetcher: EmailFetcher,
    rules: list[dict],
    mailbox: str = 'INBOX',
    limit: int | None = None,
    only_uids: list[int] | None = None,
    *,
    output_csv: Path | str | None = None,
    print_console: bool = False,
) -> list[dict[str, str]]:
    """
    Full preview pipeline: fetch, classify, output.

    Output behaviour:
        - No arguments               → console only
        - output_csv set             → file only
        - output_csv + print_console → both

    Args:
        fetcher:       Initialised EmailFetcher bound to an active IMAP connection.
        rules:         Fully normalized rule list from the config pipe.
        mailbox:       IMAP mailbox to inspect (default: 'INBOX').
        limit:         Optional cap on number of emails to preview.
        only_uids:     Optional explicit UID subset to preview.
        output_csv:    Path to write CSV output. Relative paths resolve to CWD.
        print_console: If True and output_csv is set, also print to stdout.

    Returns:
        List of row dicts with keys: uid, handler, sender, subject.
    """
    rows = preview_inbox(
        fetcher=fetcher,
        rules=rules,
        mailbox=mailbox,
        limit=limit,
        only_uids=only_uids,
    )

    if not rows:
        log_and_display('Preview: no emails found.')
        return rows

    if output_csv:
        resolved = write_preview_csv(rows, output_csv)
        log_and_display(f'Preview written to {resolved}')
        if print_console:
            print_preview(rows)
    else:
        print_preview(rows)

    return rows
