"""Vercel Python serverless function: POST multiple PDFs, get back ranked ratings per PDF."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "_lib"))

import pandas as pd
from flask import Flask, jsonify, request

from matcher import classify, match_name
from normalizer import normalize_name
from pdf_parser import parse_pdf

app = Flask(__name__)

RATINGS_PATH = Path(__file__).parent.parent / "ratings" / "ratings-final.xlsx"

RATINGS_COLUMN_ALIASES = {
    "faculty": ["faculty name", "faculty", "name", "professor", "instructor"],
    "rating": ["overall", "rating", "avg rating", "average rating", "score"],
    "difficulty": ["difficulty"],
    "review_count": ["total raters", "review count", "reviews", "num reviews", "raters"],
    "department": ["department", "dept", "school"],
}

_ratings_cache: pd.DataFrame | None = None


def load_ratings() -> pd.DataFrame:
    global _ratings_cache
    if _ratings_cache is not None:
        return _ratings_cache
    df = pd.read_excel(RATINGS_PATH)
    lower_cols = {c.lower().strip(): c for c in df.columns}
    resolved = {}
    for field, aliases in RATINGS_COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in lower_cols:
                resolved[field] = lower_cols[alias]
                break
    df = df.rename(columns={orig: field for field, orig in resolved.items()})
    keep = [c for c in ("faculty", "rating", "difficulty", "review_count", "department") if c in df.columns]
    df = df[keep].copy()
    df["__norm"] = df["faculty"].astype(str).apply(normalize_name)
    df = df.drop_duplicates(subset="__norm", keep="first").drop(columns="__norm").reset_index(drop=True)
    _ratings_cache = df
    return df


def process_pdf(file_storage) -> dict:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        file_storage.save(tmp.name)
        tmp_path = Path(tmp.name)

    try:
        slot_rows = parse_pdf(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    ratings_df = load_ratings()
    candidate_names = ratings_df["faculty"].dropna().astype(str).unique().tolist()
    ratings_by_name = {row["faculty"]: row for _, row in ratings_df.iterrows()}

    unique_names = sorted({row.faculty for row in slot_rows})
    match_cache = {name: match_name(name, candidate_names) for name in unique_names}

    results, unmatched = [], []
    for row in slot_rows:
        result = match_cache[row.faculty]
        bucket = classify(result)
        if bucket == "matched":
            rdata = ratings_by_name.get(result.matched_name, {})
            rating = rdata.get("rating", None)
            results.append({
                "faculty_pdf": row.faculty,
                "matched_faculty": result.matched_name,
                "slot": row.slot,
                "venue": row.venue,
                "rating": None if pd.isna(rating) else round(float(rating), 2),
                "difficulty": None if pd.isna(rdata.get("difficulty")) else round(float(rdata.get("difficulty")), 2),
                "review_count": None if pd.isna(rdata.get("review_count")) else int(rdata.get("review_count")),
                "department": None if pd.isna(rdata.get("department")) else rdata.get("department"),
                "confidence": round(result.score, 1),
                "found": True,
            })
        else:
            results.append({
                "faculty_pdf": row.faculty,
                "matched_faculty": None,
                "slot": row.slot,
                "venue": row.venue,
                "rating": None,
                "difficulty": None,
                "review_count": None,
                "department": None,
                "confidence": round(result.score, 1) if result.matched_name else 0,
                "found": False,
            })

    results.sort(key=lambda r: (r["rating"] is None, -(r["rating"] or 0)))

    return {
        "filename": file_storage.filename,
        "results": results,
        "stats": {
            "total_slots": len(slot_rows),
            "unique_faculty": len(unique_names),
            "not_found": sum(1 for r in results if not r["found"]),
        },
    }


@app.route("/api/parse", methods=["POST"])
def parse():
    files = request.files.getlist("pdfs")
    if not files:
        return jsonify({"error": "No PDF files uploaded (field name 'pdfs')."}), 400

    output = []
    for f in files:
        if not f.filename.lower().endswith(".pdf"):
            continue
        try:
            output.append(process_pdf(f))
        except Exception as e:
            output.append({"filename": f.filename, "error": str(e)})

    return jsonify({"files": output})


@app.route("/api/parse", methods=["GET"])
def health():
    return jsonify({"status": "ok"})
