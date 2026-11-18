"""Deterministic category reconstruction for the whale-movement research scope."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "configs" / "categories.yaml"
VALID_STATUSES = frozenset({"classified", "review", "unmapped", "excluded"})
REQUIRED_WEIGHTS = frozenset(
    {
        "exact_raw_category",
        "exact_tag",
        "strong_raw_category",
        "strong_tag",
        "strong_title",
        "strong_description",
        "weak_raw_category",
        "weak_tag",
        "weak_title",
        "weak_description",
    }
)


@dataclass(frozen=True)
class CategoryMatch:
    """One auditable rule match used in a category decision."""

    category: str
    field: str
    strength: str
    term: str
    score: int
    excluded_scope: bool = False


@dataclass(frozen=True)
class ResearchCategoryResult:
    """One deterministic research-category decision and its supporting evidence."""

    category: str | None
    status: str
    score_margin_ratio: float
    scores: dict[str, int]
    exclusion_scores: dict[str, int]
    matched_sources: tuple[CategoryMatch, ...]
    reasons: tuple[str, ...]
    raw_evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation without changing the evidence."""
        payload = asdict(self)
        payload["matched_sources"] = [asdict(match) for match in self.matched_sources]
        return payload


def _normalize_text(value: Any) -> str:
    """Return a case-folded token string suitable for exact phrase matching."""
    text_value = str(value or "").casefold().replace("&", " and ")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text_value).split())


def _contains_phrase(text_value: str, phrase: str) -> bool:
    """Return whether a normalized phrase occurs on token boundaries."""
    if not text_value or not phrase:
        return False
    return f" {phrase} " in f" {text_value} "


def _phrase_span(text_value: str, phrase: str) -> tuple[int, int] | None:
    """Return the first token-boundary span for a normalized phrase."""
    match = re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", text_value)
    return match.span() if match else None


def _string_list(value: Any, *, field_name: str) -> tuple[str, ...]:
    """Validate and normalize a configured list of strings."""
    if not isinstance(value, list) or not value or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ValueError(f"{field_name} must be a non-empty string list")
    normalized = tuple(_normalize_text(item) for item in value)
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field_name} must not contain duplicate normalized values")
    return normalized


@lru_cache(maxsize=4)
def load_category_config(config_path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """Load and minimally validate the versioned category rules."""
    path = Path(config_path).resolve()
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    if int(payload.get("schema_version") or 0) < 2:
        raise ValueError("Category configuration schema_version must be at least 2")

    scope = payload.get("scope")
    normalization = payload.get("normalization")
    exclusions = payload.get("exclusions")
    scoring = payload.get("scoring")
    if not all(isinstance(value, dict) for value in (scope, normalization, exclusions, scoring)):
        raise ValueError("Category configuration is missing scope, normalization, exclusions, or scoring")

    included = _string_list(scope.get("included_categories"), field_name="included_categories")
    if set(included) != {_normalize_text(category) for category in normalization}:
        raise ValueError("Each included research category must define exactly one normalization rule")
    excluded = _string_list(scope.get("excluded_categories"), field_name="excluded_categories")
    if set(excluded) != {_normalize_text(category) for category in exclusions}:
        raise ValueError("Each excluded category must define exactly one exclusion rule")
    deterministic_order = _string_list(scoring.get("deterministic_order"), field_name="deterministic_order")
    if set(deterministic_order) != set(included):
        raise ValueError("deterministic_order must contain every included category exactly once")

    weights = scoring.get("weights")
    if (
        not isinstance(weights, dict)
        or set(weights) != REQUIRED_WEIGHTS
        or not all(isinstance(value, int) and value > 0 for value in weights.values())
    ):
        raise ValueError("scoring.weights must contain positive integer values")
    for setting in (
        "classification_minimum_score",
        "classification_minimum_margin",
        "exclusion_minimum_score",
    ):
        value = scoring.get(setting)
        if not isinstance(value, int) or value <= 0:
            raise ValueError(f"scoring.{setting} must be a positive integer")
    for group_name, group in {**normalization, **exclusions}.items():
        if not isinstance(group, dict):
            raise ValueError(f"Category rule {group_name!r} must be a mapping")
        for rule_name in ("aliases", "strong_keywords", "weak_keywords"):
            _string_list(group.get(rule_name), field_name=f"{group_name}.{rule_name}")
    return payload


def _add_match(
    matches: list[CategoryMatch],
    *,
    category: str,
    field: str,
    strength: str,
    term: str,
    score: int,
    excluded_scope: bool,
) -> None:
    """Append one match unless the identical rule evidence is already present."""
    candidate = CategoryMatch(category, field, strength, term, score, excluded_scope)
    if candidate not in matches:
        matches.append(candidate)


def _score_rule_group(
    *,
    category: str,
    rule: Mapping[str, Any],
    fields: tuple[tuple[str, str], ...],
    weights: Mapping[str, int],
    excluded_scope: bool,
) -> tuple[int, list[CategoryMatch]]:
    """Score one included or excluded rule group across normalized input fields."""
    aliases = _string_list(rule.get("aliases"), field_name=f"{category}.aliases")
    strong_terms = _string_list(rule.get("strong_keywords"), field_name=f"{category}.strong_keywords")
    weak_terms = _string_list(rule.get("weak_keywords"), field_name=f"{category}.weak_keywords")
    matches: list[CategoryMatch] = []

    for field_name, field_value in fields:
        if not field_value:
            continue
        exact_weight_name = "exact_raw_category" if field_name == "raw_category" else "exact_tag"
        exact_matched = False
        if field_name == "raw_category" or field_name.startswith("tag["):
            for alias in aliases:
                if field_value == alias:
                    _add_match(
                        matches,
                        category=category,
                        field=field_name,
                        strength="exact",
                        term=alias,
                        score=int(weights[exact_weight_name]),
                        excluded_scope=excluded_scope,
                    )
                    exact_matched = True

        # A whole-field alias is the strongest evidence for this category and
        # must not also collect nested keyword points from the same text.
        if exact_matched:
            continue

        source_kind = "tag" if field_name.startswith("tag[") else field_name
        candidates: list[tuple[int, int, str, str]] = []
        for strength, terms in (("strong", strong_terms), ("weak", weak_terms)):
            for term in terms:
                span = _phrase_span(field_value, term)
                if span is not None:
                    candidates.append((span[0], span[1], strength, term))

        # Prefer the longest phrase when configured phrases overlap in one
        # source field. Independent, non-overlapping evidence may still add.
        selected_spans: list[tuple[int, int]] = []
        candidates.sort(
            key=lambda item: (-(item[1] - item[0]), 0 if item[2] == "strong" else 1, item[0], item[3])
        )
        for start, end, strength, term in candidates:
            if any(start < chosen_end and end > chosen_start for chosen_start, chosen_end in selected_spans):
                continue
            weight_name = f"{strength}_{source_kind}"
            _add_match(
                matches,
                category=category,
                field=field_name,
                strength=strength,
                term=term,
                score=int(weights[weight_name]),
                excluded_scope=excluded_scope,
            )
            selected_spans.append((start, end))
    return sum(match.score for match in matches), matches


def _score_margin_ratio(top_score: int, competing_score: int) -> float:
    """Return a transparent score margin, never a calibrated probability."""
    if top_score <= 0:
        return 0.0
    return round(max(0.0, min(1.0, (top_score - competing_score) / top_score)), 4)


def classify_research_category(
    *,
    raw_category: str | None = None,
    tags: Iterable[str] | None = (),
    title: str | None = None,
    description: str | None = None,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> ResearchCategoryResult:
    """Classify one market into the research scope without forcing weak conflicts."""
    config = load_category_config(config_path)
    normalization = config["normalization"]
    exclusions = config["exclusions"]
    scoring = config["scoring"]
    weights = scoring["weights"]
    order = tuple(scoring["deterministic_order"])

    if isinstance(tags, str):
        raw_tags: tuple[Any, ...] = (tags,)
    else:
        raw_tags = tuple(tags or ())
    clean_tags = tuple(str(tag).strip() for tag in raw_tags if str(tag).strip())
    fields = (
        ("raw_category", _normalize_text(raw_category)),
        *((f"tag[{index}]", _normalize_text(tag)) for index, tag in enumerate(clean_tags)),
        ("title", _normalize_text(title)),
        ("description", _normalize_text(description)),
    )

    scores: dict[str, int] = {}
    exclusion_scores: dict[str, int] = {}
    all_matches: list[CategoryMatch] = []
    for category in order:
        score, matches = _score_rule_group(
            category=category,
            rule=normalization[category],
            fields=fields,
            weights=weights,
            excluded_scope=False,
        )
        scores[category] = score
        all_matches.extend(matches)
    for category, rule in exclusions.items():
        score, matches = _score_rule_group(
            category=category,
            rule=rule,
            fields=fields,
            weights=weights,
            excluded_scope=True,
        )
        exclusion_scores[category] = score
        all_matches.extend(matches)

    ranked = sorted(order, key=lambda category: (-scores[category], order.index(category)))
    top_category = ranked[0]
    top_score = scores[top_category]
    second_score = scores[ranked[1]] if len(ranked) > 1 else 0
    excluded_category = max(exclusion_scores, key=exclusion_scores.get) if exclusion_scores else None
    excluded_score = exclusion_scores.get(excluded_category, 0) if excluded_category else 0
    minimum_score = int(scoring["classification_minimum_score"])
    minimum_margin = int(scoring["classification_minimum_margin"])
    exclusion_minimum = int(scoring["exclusion_minimum_score"])
    top_has_strong_evidence = any(
        match.category == top_category
        and not match.excluded_scope
        and match.strength in {"exact", "strong"}
        for match in all_matches
    )

    reasons: list[str] = []
    if top_score == 0 and excluded_score < exclusion_minimum:
        status = "unmapped"
        category: str | None = None
        score_margin_ratio = 0.0
        reasons.append("No configured in-scope or exclusion evidence matched.")
    elif excluded_score >= exclusion_minimum and top_score < minimum_score:
        status = "excluded"
        category = None
        score_margin_ratio = _score_margin_ratio(excluded_score, top_score)
        reasons.append(f"Out-of-scope evidence matched {excluded_category!r} without sufficient in-scope evidence.")
    elif excluded_score >= exclusion_minimum:
        status = "review"
        category = None
        score_margin_ratio = 0.0
        reasons.append(
            f"Conflicting in-scope {top_category!r} and out-of-scope {excluded_category!r} evidence requires review."
        )
    elif top_score < minimum_score:
        status = "review"
        category = None
        score_margin_ratio = _score_margin_ratio(top_score, second_score)
        reasons.append(f"Top score {top_score} is below the classification minimum {minimum_score}.")
    elif bool(scoring.get("require_exact_or_strong_evidence")) and not top_has_strong_evidence:
        status = "review"
        category = None
        score_margin_ratio = _score_margin_ratio(top_score, second_score)
        reasons.append("Only weak keyword evidence matched; exact or strong evidence is required.")
    elif second_score > 0 and top_score - second_score < minimum_margin:
        status = "review"
        category = None
        score_margin_ratio = _score_margin_ratio(top_score, second_score)
        reasons.append(
            f"Top categories {top_category!r} and {ranked[1]!r} are separated by less than {minimum_margin} points."
        )
    else:
        status = "classified"
        category = top_category
        score_margin_ratio = _score_margin_ratio(top_score, max(second_score, excluded_score))
        reasons.append(f"{top_category!r} has sufficient exact/strong evidence and a deterministic score margin.")

    if status not in VALID_STATUSES:  # pragma: no cover - defensive invariant
        raise RuntimeError(f"Unexpected category status: {status}")
    return ResearchCategoryResult(
        category=category,
        status=status,
        score_margin_ratio=score_margin_ratio,
        scores=scores,
        exclusion_scores=exclusion_scores,
        matched_sources=tuple(all_matches),
        reasons=tuple(reasons),
        raw_evidence={
            "raw_category": raw_category,
            "tags": list(raw_tags),
            "title": title,
            "description": description,
        },
    )
