"""Document and feedback file parsing (spec 1 / 11).

Handles the uploaded-file half of universal intake. Every parser is defensive:
uploads are untrusted input, so size is capped before parsing, decoding never
raises, and a malformed file degrades to a clear error rather than an exception
that kills an analysis.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass, field

#: Uploads are capped well below anything that could exhaust memory. A 10MB
#: review export is already tens of thousands of rows.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_ITEMS_PER_BATCH = 5000
MIN_ITEM_LENGTH = 3
MAX_ITEM_LENGTH = 8000

SUPPORTED_TEXT = {".txt", ".md", ".log"}
SUPPORTED_TABULAR = {".csv", ".tsv"}
SUPPORTED_STRUCTURED = {".json", ".jsonl", ".ndjson"}
SUPPORTED_BINARY = {".pdf"}
SUPPORTED_EXTENSIONS = (
    SUPPORTED_TEXT | SUPPORTED_TABULAR | SUPPORTED_STRUCTURED | SUPPORTED_BINARY
)

#: Column names commonly holding the review text itself, in preference order.
_TEXT_COLUMNS = [
    "content", "text", "body", "review", "comment", "feedback", "message",
    "description", "response", "answer", "note", "notes", "verbatim", "quote",
]
_RATING_COLUMNS = ["rating", "score", "stars", "nps", "csat"]
_AUTHOR_COLUMNS = ["author", "user", "name", "customer", "reviewer", "username"]
_DATE_COLUMNS = ["date", "created_at", "timestamp", "time", "submitted_at", "reviewed_at"]


class DocumentError(ValueError):
    """The uploaded file could not be parsed."""


@dataclass
class FeedbackRecord:
    """One piece of customer feedback."""

    content: str
    author: str = ""
    rating: float | None = None
    occurred_at: str | None = None

    @property
    def content_hash(self) -> str:
        normalised = re.sub(r"\s+", " ", self.content.strip().lower())
        return hashlib.sha256(normalised.encode()).hexdigest()


@dataclass
class ParsedDocument:
    """A document parsed for either product context or customer feedback."""

    text: str = ""
    records: list[FeedbackRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    page_count: int = 0


def _decode(data: bytes) -> str:
    """Decode bytes without ever raising.

    Tries the common encodings in order; falls back to replacement characters
    rather than failing an upload over one bad byte.
    """
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _check_size(data: bytes) -> None:
    if len(data) > MAX_UPLOAD_BYTES:
        raise DocumentError(
            f"File is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)}MB. "
            "Split it or export a smaller range."
        )
    if not data:
        raise DocumentError("That file is empty.")


def extension_of(filename: str) -> str:
    match = re.search(r"(\.[A-Za-z0-9]+)$", filename or "")
    return match.group(1).lower() if match else ""


# ---------------------------------------------------------------------------
# Format parsers
# ---------------------------------------------------------------------------


def parse_pdf(data: bytes) -> ParsedDocument:
    _check_size(data)
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise DocumentError(
            "PDF support requires the 'pypdf' package. Install it with "
            "`pip install pypdf`."
        ) from exc

    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:
        raise DocumentError(f"That PDF could not be read: {exc}") from exc

    if getattr(reader, "is_encrypted", False):
        # Attempt the empty-password case, which covers most "protected" PDFs.
        try:
            reader.decrypt("")
        except Exception:
            raise DocumentError("That PDF is password-protected.") from None

    pages: list[str] = []
    warnings: list[str] = []
    for index, page in enumerate(reader.pages):
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            warnings.append(f"Page {index + 1} could not be read and was skipped.")

    text = re.sub(r"\n{3,}", "\n\n", "\n\n".join(pages)).strip()
    if not text:
        warnings.append(
            "No extractable text found. This may be a scanned PDF, which needs OCR."
        )
    return ParsedDocument(text=text, warnings=warnings, page_count=len(reader.pages))


def parse_text(data: bytes) -> ParsedDocument:
    _check_size(data)
    return ParsedDocument(text=_decode(data).strip())


def _pick_column(fieldnames: list[str], candidates: list[str]) -> str | None:
    lowered = {name.lower().strip(): name for name in fieldnames if name}
    for candidate in candidates:
        if candidate in lowered:
            return lowered[candidate]
    # Fall back to a partial match, e.g. "review_body".
    for candidate in candidates:
        for key, original in lowered.items():
            if candidate in key:
                return original
    return None


def parse_tabular(data: bytes, delimiter: str | None = None) -> ParsedDocument:
    """Parse CSV/TSV, auto-detecting which column holds the feedback text."""
    _check_size(data)
    text = _decode(data)

    if delimiter is None:
        try:
            delimiter = csv.Sniffer().sniff(text[:8000], delimiters=",;\t|").delimiter
        except csv.Error:
            delimiter = "\t" if text.count("\t") > text.count(",") else ","

    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    fieldnames = [f for f in (reader.fieldnames or []) if f]
    if not fieldnames:
        raise DocumentError("That file has no header row, so its columns cannot be read.")

    warnings: list[str] = []
    text_column = _pick_column(fieldnames, _TEXT_COLUMNS)
    if text_column is None:
        # No recognised name: use the column with the longest average content,
        # which is almost always the free-text one.
        text_column = _widest_column(text, delimiter, fieldnames)
        if text_column is None:
            raise DocumentError(
                "No text column found. Expected a column named one of: "
                + ", ".join(_TEXT_COLUMNS[:6])
            )
        warnings.append(f"Guessed '{text_column}' as the feedback column.")

    rating_column = _pick_column(fieldnames, _RATING_COLUMNS)
    author_column = _pick_column(fieldnames, _AUTHOR_COLUMNS)
    date_column = _pick_column(fieldnames, _DATE_COLUMNS)

    records: list[FeedbackRecord] = []
    for row in reader:
        content = (row.get(text_column) or "").strip()
        if len(content) < MIN_ITEM_LENGTH:
            continue
        records.append(
            FeedbackRecord(
                content=content[:MAX_ITEM_LENGTH],
                author=(row.get(author_column) or "").strip()[:120] if author_column else "",
                rating=_to_float(row.get(rating_column)) if rating_column else None,
                occurred_at=(row.get(date_column) or "").strip()[:40] if date_column else None,
            )
        )
        if len(records) >= MAX_ITEMS_PER_BATCH:
            warnings.append(
                f"Only the first {MAX_ITEMS_PER_BATCH} rows were read."
            )
            break

    if not records:
        raise DocumentError("No usable rows found in that file.")
    return ParsedDocument(records=records, warnings=warnings)


def _widest_column(text: str, delimiter: str, fieldnames: list[str]) -> str | None:
    """Return the column with the longest average value."""
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    totals: dict[str, int] = {name: 0 for name in fieldnames}
    counted = 0
    for row in reader:
        for name in fieldnames:
            totals[name] += len((row.get(name) or ""))
        counted += 1
        if counted >= 200:
            break
    if not counted:
        return None
    best = max(totals, key=lambda name: totals[name])
    return best if totals[best] / counted >= 15 else None


def parse_structured(data: bytes) -> ParsedDocument:
    """Parse JSON or JSON Lines."""
    _check_size(data)
    text = _decode(data).strip()
    if not text:
        raise DocumentError("That file is empty.")

    rows: list[dict] = []
    if text.startswith("["):
        try:
            loaded = json.loads(text)
        except json.JSONDecodeError as exc:
            raise DocumentError(f"Invalid JSON: {exc}") from exc
        rows = [item for item in loaded if isinstance(item, dict)]
    else:
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                rows.append(item)

    if not rows:
        raise DocumentError("No JSON objects found in that file.")

    keys = sorted({key for row in rows[:200] for key in row})
    text_key = _pick_column(keys, _TEXT_COLUMNS)
    if text_key is None:
        raise DocumentError(
            "No text field found. Expected one of: " + ", ".join(_TEXT_COLUMNS[:6])
        )
    rating_key = _pick_column(keys, _RATING_COLUMNS)
    author_key = _pick_column(keys, _AUTHOR_COLUMNS)
    date_key = _pick_column(keys, _DATE_COLUMNS)

    records: list[FeedbackRecord] = []
    for row in rows[:MAX_ITEMS_PER_BATCH]:
        content = str(row.get(text_key) or "").strip()
        if len(content) < MIN_ITEM_LENGTH:
            continue
        records.append(
            FeedbackRecord(
                content=content[:MAX_ITEM_LENGTH],
                author=str(row.get(author_key) or "")[:120] if author_key else "",
                rating=_to_float(row.get(rating_key)) if rating_key else None,
                occurred_at=str(row.get(date_key) or "")[:40] if date_key else None,
            )
        )
    if not records:
        raise DocumentError("No usable records found in that file.")
    return ParsedDocument(records=records)


def parse_pasted_feedback(text: str) -> ParsedDocument:
    """Split pasted text into individual feedback items.

    Blank-line separated blocks are treated as separate items; failing that,
    each non-empty line is one item.
    """
    text = (text or "").strip()
    if not text:
        raise DocumentError("Paste some feedback first.")

    blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
    if len(blocks) <= 1:
        blocks = [line.strip() for line in text.splitlines() if line.strip()]

    records = [
        FeedbackRecord(content=block[:MAX_ITEM_LENGTH])
        for block in blocks[:MAX_ITEMS_PER_BATCH]
        if len(block) >= MIN_ITEM_LENGTH
    ]
    if not records:
        raise DocumentError("No usable feedback items found in that text.")
    return ParsedDocument(records=records)


def _to_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).strip().split()[0])
    except (ValueError, IndexError):
        return None


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def parse_upload(filename: str, data: bytes, *, as_feedback: bool = False) -> ParsedDocument:
    """Parse an uploaded file by extension.

    ``as_feedback`` splits plain text and PDFs into individual items rather than
    returning one document blob.
    """
    extension = extension_of(filename)
    if extension not in SUPPORTED_EXTENSIONS:
        raise DocumentError(
            f"Unsupported file type '{extension or filename}'. Supported: "
            + ", ".join(sorted(SUPPORTED_EXTENSIONS))
        )

    if extension in SUPPORTED_TABULAR:
        return parse_tabular(data, delimiter="\t" if extension == ".tsv" else None)
    if extension in SUPPORTED_STRUCTURED:
        return parse_structured(data)

    document = parse_pdf(data) if extension in SUPPORTED_BINARY else parse_text(data)
    if as_feedback and document.text:
        split = parse_pasted_feedback(document.text)
        split.warnings = document.warnings + split.warnings
        split.page_count = document.page_count
        return split
    return document


def deduplicate(records: list[FeedbackRecord]) -> tuple[list[FeedbackRecord], int]:
    """Drop repeated feedback, returning the kept records and the drop count."""
    seen: set[str] = set()
    kept: list[FeedbackRecord] = []
    for record in records:
        digest = record.content_hash
        if digest in seen:
            continue
        seen.add(digest)
        kept.append(record)
    return kept, len(records) - len(kept)
