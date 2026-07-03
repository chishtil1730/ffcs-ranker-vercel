"""Extract Slot / Venue / Faculty rows from VIT FFCS registration PDFs."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import pdfplumber

logger = logging.getLogger(__name__)

SLOT_RE = re.compile(r"^[A-Z]{1,3}\d{1,2}(\+[A-Z]{1,3}\d{1,2})?$")
JUNK_FACULTY = {"course option", "register go back", "regular", "register", "go back"}


@dataclass(frozen=True)
class SlotRow:
    slot: str
    venue: str
    faculty: str
    source_file: str


def _looks_like_data_row(row: list) -> bool:
    if not row or len(row) < 3:
        return False
    slot, venue, faculty = (str(row[0] or "").strip(), str(row[1] or "").strip(), str(row[2] or "").strip())
    if not slot or not venue or not faculty:
        return False
    if not SLOT_RE.match(slot.upper()):
        return False
    if faculty.lower() in JUNK_FACULTY:
        return False
    if not re.search(r"[A-Za-z]", faculty):
        return False
    return True


def parse_pdf(path: Path) -> list[SlotRow]:
    """Extract all Slot/Venue/Faculty rows from a single FFCS PDF, across pages,
    ignoring headers/footers and non-data rows (section labels, nav buttons)."""
    rows: list[SlotRow] = []
    try:
        with pdfplumber.open(path) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                table = page.extract_table()
                if not table:
                    continue
                for raw in table:
                    if _looks_like_data_row(raw):
                        slot, venue, faculty = str(raw[0]).strip(), str(raw[1]).strip(), str(raw[2]).strip()
                        rows.append(SlotRow(slot=slot, venue=venue, faculty=faculty, source_file=path.name))
                    else:
                        logger.debug("Skipped non-data row on %s p%d: %s", path.name, page_num, raw)
    except Exception:
        logger.exception("Failed to parse PDF %s", path)
    logger.info("Parsed %d slot rows from %s", len(rows), path.name)
    return rows


def parse_pdf_folder(folder: Path) -> list[SlotRow]:
    """Parse every PDF in a folder and combine into one dataset."""
    all_rows: list[SlotRow] = []
    for pdf_path in sorted(Path(folder).glob("*.pdf")):
        all_rows.extend(parse_pdf(pdf_path))
    return all_rows
