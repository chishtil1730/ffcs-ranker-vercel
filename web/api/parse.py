"""Extract Slot / Venue / Faculty rows from VIT FFCS registration PDFs."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import pdfplumber
import pytesseract
from pdf2image import convert_from_path
from PIL import Image

logger = logging.getLogger(__name__)

SLOT_RE = re.compile(r"^[A-Z]{1,3}\d{1,2}(\+[A-Z]{1,3}\d{1,2})?$")
JUNK_FACULTY = {"course option", "register go back", "regular", "register", "go back"}
OCR_DPI = 200


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


def _ocr_crop(image: Image.Image, box: tuple[int, int, int, int]) -> str:
    """OCR a single column/row cell: crop, upscale, and read as one text line."""
    crop = image.crop(box).convert("L")
    crop = crop.resize((crop.width * 3, crop.height * 3), Image.LANCZOS)
    text = pytesseract.image_to_string(crop, config="--psm 6").strip()
    return re.sub(r"\s+", " ", text)


def _parse_page_via_ocr(image: Image.Image, page_num: int, source_file: str) -> list[SlotRow]:
    """Fallback for PDFs where the table is embedded as an image (no extractable text).
    Locates the SLOT/VENUE/FACULTY header cells, then OCRs each row band per column."""
    rows: list[SlotRow] = []
    data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
    words = [(data["left"][i], data["top"][i], data["text"][i].strip())
             for i in range(len(data["text"])) if data["text"][i].strip()]

    def header_x(label: str) -> int | None:
        return next((l for l, t, txt in words if txt.upper() == label and t < 250), None)

    slot_x, venue_x, faculty_x, mode_x = (header_x(l) for l in ("SLOT", "VENUE", "FACULTY", "MODE"))
    if slot_x is None or venue_x is None or faculty_x is None:
        return rows
    mode_x = mode_x or (faculty_x + 400)

    slot_words = sorted(
        [w for w in words if slot_x - 40 <= w[0] < venue_x - 40 and SLOT_RE.match(w[2].upper())],
        key=lambda w: w[1],
    )
    for idx, (_, top, slot) in enumerate(slot_words):
        prev_top = slot_words[idx - 1][1] if idx > 0 else top - 200
        next_top = slot_words[idx + 1][1] if idx + 1 < len(slot_words) else top + 200
        y0, y1 = int((prev_top + top) / 2) - 5, int((top + next_top) / 2) + 5
        venue = _ocr_crop(image, (venue_x - 30, y0, faculty_x - 30, y1))
        faculty = _ocr_crop(image, (faculty_x - 30, y0, mode_x - 30, y1))
        if venue and faculty and re.search(r"[A-Za-z]", faculty):
            rows.append(SlotRow(slot=slot, venue=venue, faculty=faculty, source_file=source_file))
        else:
            logger.debug("Skipped OCR row on %s p%d: %s/%s/%s", source_file, page_num, slot, venue, faculty)
    return rows


def parse_pdf(path: Path) -> list[SlotRow]:
    """Extract all Slot/Venue/Faculty rows from a single FFCS PDF, across pages,
    ignoring headers/footers and non-data rows (section labels, nav buttons).
    Falls back to OCR for pages where the table is a rendered image rather than text
    (e.g. print-to-PDF screenshots), rather than requiring a real text layer."""
    rows: list[SlotRow] = []
    try:
        with pdfplumber.open(path) as pdf:
            ocr_page_nums = []
            for page_num, page in enumerate(pdf.pages, start=1):
                table = page.extract_table()
                page_rows = []
                if table:
                    for raw in table:
                        if _looks_like_data_row(raw):
                            slot, venue, faculty = str(raw[0]).strip(), str(raw[1]).strip(), str(raw[2]).strip()
                            page_rows.append(SlotRow(slot=slot, venue=venue, faculty=faculty, source_file=path.name))
                        else:
                            logger.debug("Skipped non-data row on %s p%d: %s", path.name, page_num, raw)
                if page_rows:
                    rows.extend(page_rows)
                else:
                    ocr_page_nums.append(page_num)

            if ocr_page_nums:
                images = convert_from_path(
                    path, dpi=OCR_DPI, first_page=min(ocr_page_nums), last_page=max(ocr_page_nums)
                )
                offset = min(ocr_page_nums)
                for page_num in ocr_page_nums:
                    image = images[page_num - offset]
                    rows.extend(_parse_page_via_ocr(image, page_num, path.name))
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