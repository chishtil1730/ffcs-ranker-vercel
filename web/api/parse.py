"""Vercel serverless function, parse VIT FFCS registration PDFs and merge
faculty's ratings. Exposes a Flask `app` (the entrypoint Vercel's Python
runtime looks for) this file is deployable as-is under /api/parse.
"""
from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from itertools import permutations
from pathlib import Path

import pandas as pd
import pdfplumber
from flask import Flask, jsonify, request
from rapidfuzz import fuzz, process
from unidecode import unidecode

logger = logging.getLogger(__name__)
app = Flask(__name__)

# ---------------------------------------------------------------- constants
SLOT_RE = re.compile(r"^[A-Z]{1,3}\d{1,2}(\+[A-Z]{1,3}\d{1,2})?$")
JUNK_FACULTY = {"course option", "register go back", "regular", "register", "go back"}
TITLES = {"dr", "prof", "professor", "mr", "mrs", "ms"}
_PUNCT_RE = re.compile(r"[^\w\s]")
_SPACE_RE = re.compile(r"\s+")

EXACT_MATCH = 100
AUTOMATIC_MATCH = 90
MANUAL_REVIEW = 75

# api/parse.py -> project root -> ratings/ratings-final.xlsx
RATINGS_PATH = Path(__file__).resolve().parent.parent / "ratings" / "ratings-final.xlsx"


# ------------------------------------------------------------ name matching
@lru_cache(maxsize=4096)
def normalize_name(name: str) -> str:
    if not name:
        return ""
    text = unidecode(str(name)).lower()
    text = _PUNCT_RE.sub(" ", text)
    tokens = [t for t in text.split() if t not in TITLES]
    return _SPACE_RE.sub(" ", " ".join(tokens)).strip()


@lru_cache(maxsize=4096)
def tokens_of(name: str) -> tuple[str, ...]:
    return tuple(normalize_name(name).split())


def token_sorted(name: str) -> str:
    return " ".join(sorted(tokens_of(name)))


def _token_or_initial_equal(a: str, b: str) -> bool:
    if a == b:
        return True
    if len(a) == 1:
        return b.startswith(a)
    if len(b) == 1:
        return a.startswith(b)
    return False


def initials_match_score(name_a: str, name_b: str):
    ta, tb = tokens_of(name_a), tokens_of(name_b)
    if len(ta) != len(tb) or not ta:
        return None
    best_exact = 0
    for perm in permutations(tb):
        if all(_token_or_initial_equal(x, y) for x, y in zip(ta, perm)):
            exact = sum(1 for x, y in zip(ta, perm) if x == y)
            best_exact = max(best_exact, exact)
    if best_exact == 0:
        return None
    return 90 + int(9 * (best_exact / len(ta)))


@dataclass
class MatchResult:
    pdf_name: str
    matched_name: str | None
    score: float
    method: str
    candidates: list = field(default_factory=list)


def match_name(pdf_name: str, candidate_names: list[str]) -> MatchResult:
    if not candidate_names:
        return MatchResult(pdf_name, None, 0.0, "no_candidates")

    norm_target = normalize_name(pdf_name)
    sorted_target = token_sorted(pdf_name)

    for cand in candidate_names:
        if normalize_name(cand) == norm_target:
            return MatchResult(pdf_name, cand, EXACT_MATCH, "exact_normalized")

    for cand in candidate_names:
        if token_sorted(cand) == sorted_target:
            return MatchResult(pdf_name, cand, EXACT_MATCH, "token_order_ignored")

    best_initial = None
    for cand in candidate_names:
        score = initials_match_score(pdf_name, cand)
        if score is not None and (best_initial is None or score > best_initial[1]):
            best_initial = (cand, score)
    if best_initial:
        return MatchResult(pdf_name, best_initial[0], float(best_initial[1]), "initial_expansion")

    norm_map = {cand: normalize_name(cand) for cand in candidate_names}
    scorers = (fuzz.WRatio, fuzz.token_sort_ratio, fuzz.token_set_ratio)
    best_overall = None
    alternates: dict[str, float] = {}
    for scorer in scorers:
        result = process.extractOne(norm_target, norm_map, scorer=scorer)
        if result is None:
            continue
        _, score, cand_key = result
        alternates[cand_key] = max(alternates.get(cand_key, 0), score)
        if best_overall is None or score > best_overall[1]:
            best_overall = (cand_key, score)

    top_alternates = sorted(alternates.items(), key=lambda kv: kv[1], reverse=True)[:3]
    if best_overall:
        return MatchResult(pdf_name, best_overall[0], best_overall[1], "fuzzy", top_alternates)

    return MatchResult(pdf_name, None, 0.0, "unmatched")


def classify(result: MatchResult) -> str:
    if result.matched_name is None:
        return "unmatched"
    if result.score >= AUTOMATIC_MATCH:
        return "matched"
    if result.score >= MANUAL_REVIEW:
        return "review"
    return "unmatched"


# ------------------------------------------------------------- PDF parsing
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


def parse_pdf_bytes(data: bytes) -> list[dict]:
    """Extract Slot/Venue/Faculty rows from PDF bytes using the text layer.
    (No OCR fallback: OCR needs tesseract/poppler binaries that aren't
    available in Vercel's Python serverless runtime.)"""
    rows: list[dict] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            table = page.extract_table()
            if not table:
                continue
            for raw in table:
                if _looks_like_data_row(raw):
                    rows.append({
                        "slot": str(raw[0]).strip(),
                        "venue": str(raw[1]).strip(),
                        "faculty": str(raw[2]).strip(),
                    })
    return rows


# ----------------------------------------------------------------- ratings
def _clean(value):
    """Convert pandas/numpy scalars to plain JSON-safe python values."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


@lru_cache(maxsize=1)
def load_ratings() -> dict:
    df = pd.read_excel(RATINGS_PATH)
    ratings = {}
    for _, row in df.iterrows():
        name = str(row.get("Faculty Name", "")).strip()
        if not name:
            continue
        ratings[name] = {
            "rating": _clean(row.get("Overall")),
            "difficulty": _clean(row.get("Difficulty")) if "Difficulty" in df.columns else None,
            "review_count": _clean(row.get("Review Count")) if "Review Count" in df.columns else None,
        }
    return ratings


# ------------------------------------------------------------------ route
@app.route("/api/parse", methods=["POST"])
def parse_endpoint():
    files = request.files.getlist("pdfs")
    if not files:
        return jsonify({"error": "No PDF files uploaded."}), 400

    try:
        ratings = load_ratings()
    except Exception:
        logger.exception("Failed to load ratings file")
        return jsonify({"error": "Faculty ratings data could not be loaded."}), 500

    candidate_names = list(ratings.keys())
    output = []

    for f in files:
        try:
            rows = parse_pdf_bytes(f.read())
            results = []
            seen_faculty = set()
            not_found = 0

            for row in rows:
                match = match_name(row["faculty"], candidate_names)
                bucket = classify(match)
                found = bucket in ("matched", "review")
                if found:
                    info = ratings[match.matched_name]
                    results.append({
                        "slot": row["slot"],
                        "venue": row["venue"],
                        "faculty_pdf": row["faculty"],
                        "matched_faculty": match.matched_name,
                        "rating": info["rating"],
                        "difficulty": info["difficulty"],
                        "review_count": info["review_count"],
                        "found": True,
                    })
                    seen_faculty.add(match.matched_name)
                else:
                    not_found += 1
                    results.append({
                        "slot": row["slot"],
                        "venue": row["venue"],
                        "faculty_pdf": row["faculty"],
                        "matched_faculty": None,
                        "rating": None,
                        "difficulty": None,
                        "review_count": None,
                        "found": False,
                    })
                    seen_faculty.add(row["faculty"])

            output.append({
                "filename": f.filename,
                "results": results,
                "stats": {
                    "total_slots": len(results),
                    "unique_faculty": len(seen_faculty),
                    "not_found": not_found,
                },
            })
        except Exception as exc:
            logger.exception("Failed to process %s", f.filename)
            output.append({"filename": f.filename, "error": str(exc)})

    return jsonify({"files": output})
