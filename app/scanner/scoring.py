"""Candidate assembly and the scoring formula from the spec:

final_score = trend_score * competition_penalty
penalty: <1,000 -> 1.0 | <5,000 -> 0.6 | <20,000 -> 0.3 | else 0.1 | null -> 0.5
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.config import RELEVANCE_TERMS


@dataclass
class Candidate:
    keyword: str
    source: str  # google_trends | etsy_autocomplete
    trend_score: float
    competition_count: int | None = None
    final_score: float = 0.0
    rationale: str = ""
    extra: dict = field(default_factory=dict)


def competition_penalty(count: int | None) -> float:
    if count is None:
        return 0.5
    if count < 1_000:
        return 1.0
    if count < 5_000:
        return 0.6
    if count < 20_000:
        return 0.3
    return 0.1


def is_relevant(keyword: str) -> bool:
    kw = keyword.lower()
    return any(term in kw for term in RELEVANCE_TERMS)


def suggestion_score(position: int) -> float:
    """Autocomplete suggestions carry no numeric trend value; approximate
    demand from their rank in the suggestion list (earlier = more searched)."""
    return max(20.0, 65.0 - 5.0 * position)


def build_candidates(
    seed_trend_scores: dict[str, float],
    suggestions_by_seed: dict[str, list[str]],
) -> list[Candidate]:
    """Merge both sources, filter for relevance, dedupe (best score wins)."""
    merged: dict[str, Candidate] = {}

    for seed, score in seed_trend_scores.items():
        if is_relevant(seed):
            merged[seed] = Candidate(keyword=seed, source="google_trends", trend_score=score)

    for seed, suggestions in suggestions_by_seed.items():
        for pos, suggestion in enumerate(suggestions):
            if not is_relevant(suggestion):
                continue
            score = suggestion_score(pos)
            existing = merged.get(suggestion)
            if existing is None or score > existing.trend_score:
                merged[suggestion] = Candidate(
                    keyword=suggestion, source="etsy_autocomplete", trend_score=score
                )

    return sorted(merged.values(), key=lambda c: c.trend_score, reverse=True)


def finalize_scores(candidates: list[Candidate]) -> list[Candidate]:
    for cand in candidates:
        cand.final_score = round(cand.trend_score * competition_penalty(cand.competition_count), 2)
    return sorted(candidates, key=lambda c: c.final_score, reverse=True)
