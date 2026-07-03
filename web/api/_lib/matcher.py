"""Match PDF faculty names against a ratings dataset with a graded pipeline."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from rapidfuzz import fuzz, process

from normalizer import initials_match_score, normalize_name, token_sorted

logger = logging.getLogger(__name__)

EXACT_MATCH = 100
AUTOMATIC_MATCH = 90
MANUAL_REVIEW = 75


@dataclass
class MatchResult:
    pdf_name: str
    matched_name: str | None
    score: float
    method: str
    candidates: list[tuple[str, float]] = field(default_factory=list)  # top alternates for review


def match_name(pdf_name: str, candidate_names: list[str]) -> MatchResult:
    """Run the graded matching pipeline for a single faculty name."""
    if not candidate_names:
        return MatchResult(pdf_name, None, 0.0, "no_candidates")

    norm_target = normalize_name(pdf_name)
    sorted_target = token_sorted(pdf_name)

    # Step 1: exact normalized match
    for cand in candidate_names:
        if normalize_name(cand) == norm_target:
            logger.debug("Exact match: %s -> %s", pdf_name, cand)
            return MatchResult(pdf_name, cand, EXACT_MATCH, "exact_normalized")

    # Step 2: ignore word order
    for cand in candidate_names:
        if token_sorted(cand) == sorted_target:
            logger.debug("Token-order match: %s -> %s", pdf_name, cand)
            return MatchResult(pdf_name, cand, EXACT_MATCH, "token_order_ignored")

    # Step 3: initial expansion
    best_initial: tuple[str, int] | None = None
    for cand in candidate_names:
        score = initials_match_score(pdf_name, cand)
        if score is not None and (best_initial is None or score > best_initial[1]):
            best_initial = (cand, score)
    if best_initial:
        logger.debug("Initial match: %s -> %s (%d)", pdf_name, *best_initial)
        return MatchResult(pdf_name, best_initial[0], float(best_initial[1]), "initial_expansion")

    # Step 4/5: fuzzy matching + confidence scoring
    norm_map = {cand: normalize_name(cand) for cand in candidate_names}
    scorers = (fuzz.WRatio, fuzz.token_sort_ratio, fuzz.token_set_ratio)
    best_overall: tuple[str, float] | None = None
    alternates: dict[str, float] = {}
    for scorer in scorers:
        result = process.extractOne(norm_target, norm_map, scorer=scorer)
        if result is None:
            continue
        _, score, cand_key = result
        cand_name = candidate_names[list(norm_map.keys()).index(cand_key)] if cand_key not in candidate_names else cand_key
        # process.extractOne with a dict returns the *key* as the match; norm_map keys are original names
        cand_name = cand_key
        alternates[cand_name] = max(alternates.get(cand_name, 0), score)
        if best_overall is None or score > best_overall[1]:
            best_overall = (cand_name, score)

    top_alternates = sorted(alternates.items(), key=lambda kv: kv[1], reverse=True)[:3]
    if best_overall:
        logger.debug("Fuzzy match: %s -> %s (%.1f)", pdf_name, *best_overall)
        return MatchResult(pdf_name, best_overall[0], best_overall[1], "fuzzy", top_alternates)

    return MatchResult(pdf_name, None, 0.0, "unmatched")


def classify(result: MatchResult) -> str:
    """Bucket a match result into 'matched', 'review', or 'unmatched'."""
    if result.matched_name is None:
        return "unmatched"
    if result.score >= AUTOMATIC_MATCH:
        return "matched"
    if result.score >= MANUAL_REVIEW:
        return "review"
    return "unmatched"
