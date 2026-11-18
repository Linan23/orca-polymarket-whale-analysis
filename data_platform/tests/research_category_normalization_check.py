"""Independently verify deterministic research-category reconstruction."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from analysis import profile_category_reconstruction as category_profile  # noqa: E402
from data_platform.services.research_categories import (  # noqa: E402
    DEFAULT_CONFIG_PATH,
    classify_research_category,
    load_category_config,
)


EXPECTED_CATEGORIES = {"politics", "crypto", "finance", "technology", "geopolitics"}
EXPECTED_STATUSES = {"classified", "review", "unmapped", "excluded"}


class _FakeRows:
    """Minimal SQLAlchemy result stand-in for aggregate privacy testing."""

    def __init__(self, values: list[Any]) -> None:
        self.values = values

    def scalars(self) -> list[Any]:
        return self.values

    def mappings(self) -> list[Any]:
        return self.values


class _FakeConnection:
    """Serve synthetic table metadata and event rows to the real profiler."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def execution_options(self, **_kwargs: Any) -> _FakeConnection:
        return self

    def begin(self) -> _FakeConnection:
        return self

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def execute(self, statement: Any) -> _FakeRows:
        sql = str(statement)
        if "information_schema.tables" in sql:
            return _FakeRows(sorted(category_profile.REQUIRED_TABLES))
        if "FROM analytics.market_event" in sql:
            return _FakeRows(self.rows)
        return _FakeRows([])


class _FakeEngine:
    """Minimal engine stand-in that records profiler cleanup."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.connection = _FakeConnection(rows)
        self.disposed = False

    def connect(self) -> _FakeConnection:
        return self.connection

    def dispose(self) -> None:
        self.disposed = True


def _forbidden_keys(value: Any, forbidden: set[str], path: str = "$") -> list[str]:
    """Return paths containing aggregate fields that could expose row-level evidence."""
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key).lower() in forbidden:
                found.append(child_path)
            found.extend(_forbidden_keys(child, forbidden, child_path))
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            found.extend(_forbidden_keys(child, forbidden, f"{path}[{index}]"))
    return found


def _aggregate_profile(rows: list[dict[str, Any]]) -> tuple[dict[str, Any], str, bool]:
    """Run the real aggregate profiler against deterministic synthetic rows."""
    engine = _FakeEngine(rows)
    original_create_engine = category_profile.create_engine
    category_profile.create_engine = lambda *_args, **_kwargs: engine
    try:
        profile = category_profile.profile_category_reconstruction("synthetic://category-check")
        markdown = category_profile.render_markdown(profile)
    finally:
        category_profile.create_engine = original_create_engine
    return profile, markdown, engine.disposed


def main() -> int:
    """Run category, ambiguity, determinism, configuration, and privacy checks."""
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, **details: Any) -> None:
        checks.append(
            {
                "name": name,
                "status": "PASS" if ok else "FAIL",
                "ok": bool(ok),
                "details": details,
            }
        )

    config = load_category_config()
    included = set(config["scope"]["included_categories"])
    normalized = set(config["normalization"])
    deterministic_order = config["scoring"]["deterministic_order"]
    exclusions = set(config["exclusions"])
    check(
        "config_exact_five_category_scope",
        included == EXPECTED_CATEGORIES
        and normalized == EXPECTED_CATEGORIES
        and set(deterministic_order) == EXPECTED_CATEGORIES
        and len(deterministic_order) == len(EXPECTED_CATEGORIES),
        included=sorted(included),
        normalization=sorted(normalized),
        deterministic_order=deterministic_order,
    )
    check(
        "config_review_and_evidence_controls",
        "physical_sports" in exclusions
        and config["scope"].get("unknown_category_policy") == "review"
        and config["review_rules"].get("retain_raw_labels") is True
        and config["review_rules"].get("retain_matched_evidence") is True
        and config["review_rules"].get("review_in_scope_ties") is True
        and config["review_rules"].get("review_in_scope_exclusion_conflicts") is True,
        exclusions=sorted(exclusions),
        review_rules=config["review_rules"],
    )

    invalid_config = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    invalid_config["scope"]["included_categories"] = ["politics", "crypto"]
    invalid_rejected = False
    invalid_error = ""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", encoding="utf-8") as handle:
        yaml.safe_dump(invalid_config, handle)
        handle.flush()
        try:
            load_category_config(handle.name)
        except ValueError as exc:
            invalid_rejected = True
            invalid_error = str(exc)
    check(
        "config_validator_rejects_incomplete_scope",
        invalid_rejected,
        error=invalid_error,
    )

    duplicate_config = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    duplicate_config["normalization"]["politics"]["aliases"].append("Politics")
    duplicate_rejected = False
    duplicate_error = ""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", encoding="utf-8") as handle:
        yaml.safe_dump(duplicate_config, handle)
        handle.flush()
        try:
            load_category_config(handle.name)
        except ValueError as exc:
            duplicate_rejected = True
            duplicate_error = str(exc)
    check(
        "config_validator_rejects_normalized_duplicates",
        duplicate_rejected and "duplicate normalized values" in duplicate_error,
        error=duplicate_error,
    )

    fixtures: dict[str, tuple[dict[str, Any], str, str | None]] = {
        "domestic_politics": (
            {"title": "Will the Senate pass legislation before the election?"},
            "classified",
            "politics",
        ),
        "geopolitics": (
            {"title": "Will NATO agree a ceasefire in the war in Ukraine?"},
            "classified",
            "geopolitics",
        ),
        "crypto": (
            {"title": "Will Bitcoin reach a new high after a crypto ETF approval?"},
            "classified",
            "crypto",
        ),
        "finance": (
            {"title": "Will the Federal Reserve announce an interest rate cut?"},
            "classified",
            "finance",
        ),
        "technology": (
            {"title": "Will OpenAI release a new large language model?"},
            "classified",
            "technology",
        ),
        "physical_sports": (
            {"title": "Will the NBA champion win the basketball game?"},
            "excluded",
            None,
        ),
        "weak_evidence": (
            {"title": "Will Trump make an announcement?"},
            "review",
            None,
        ),
        "crypto_finance_conflict": (
            {"title": "Will Bitcoin react to a Federal Reserve announcement?"},
            "review",
            None,
        ),
        "unmapped": (
            {"title": "Will the city open a new park?"},
            "unmapped",
            None,
        ),
        "presidential_election": (
            {"title": "Will the presidential election be held this year?"},
            "classified",
            "politics",
        ),
        "politics_geopolitics_conflict": (
            {"title": "Will the presidential election affect a military conflict?"},
            "review",
            None,
        ),
    }
    results: dict[str, Any] = {}
    for name, (inputs, expected_status, expected_category) in fixtures.items():
        result = classify_research_category(**inputs)
        results[name] = result
        check(
            f"fixture_{name}",
            result.status == expected_status
            and result.category == expected_category
            and set(result.scores) == EXPECTED_CATEGORIES
            and result.status in EXPECTED_STATUSES,
            expected_status=expected_status,
            observed_status=result.status,
            expected_category=expected_category,
            observed_category=result.category,
            scores=result.scores,
            exclusion_scores=result.exclusion_scores,
        )

    check(
        "geopolitics_is_distinct_from_domestic_politics",
        results["domestic_politics"].category == "politics"
        and results["domestic_politics"].scores["geopolitics"] == 0
        and results["geopolitics"].category == "geopolitics"
        and results["geopolitics"].scores["politics"] == 0,
        domestic_scores=results["domestic_politics"].scores,
        geopolitical_scores=results["geopolitics"].scores,
    )
    presidential = results["presidential_election"]
    presidential_terms = [
        match.term
        for match in presidential.matched_sources
        if match.category == "politics" and match.field == "title"
    ]
    check(
        "overlapping_phrases_count_once",
        presidential.scores["politics"] == 8
        and presidential_terms == ["presidential election"],
        politics_score=presidential.scores["politics"],
        matched_terms=presidential_terms,
    )
    mixed = results["politics_geopolitics_conflict"]
    check(
        "mixed_politics_geopolitics_is_not_forced",
        mixed.status == "review"
        and mixed.category is None
        and mixed.scores["politics"] == mixed.scores["geopolitics"] == 8,
        scores=mixed.scores,
        reasons=mixed.reasons,
    )
    conflict = results["crypto_finance_conflict"]
    check(
        "crypto_finance_tie_is_not_forced",
        conflict.status == "review"
        and conflict.category is None
        and conflict.scores["crypto"] == conflict.scores["finance"] > 0,
        scores=conflict.scores,
        reasons=conflict.reasons,
    )
    sports = results["physical_sports"]
    check(
        "physical_sports_is_excluded",
        sports.status == "excluded"
        and sports.category is None
        and sports.exclusion_scores.get("physical_sports", 0) > 0,
        exclusion_scores=sports.exclusion_scores,
    )

    evidence_inputs = {
        "raw_category": "Technology",
        "tags": ("AI", "software"),
        "title": "SENSITIVE_TITLE_OPENAI_RELEASE",
        "description": "SENSITIVE_DESCRIPTION_MODEL_LAUNCH",
    }
    first = classify_research_category(**evidence_inputs)
    second = classify_research_category(**evidence_inputs)
    check(
        "deterministic_output",
        first.to_dict() == second.to_dict(),
        first=first.to_dict(),
        second=second.to_dict(),
    )
    check(
        "row_level_audit_evidence_retained",
        first.raw_evidence
        == {
            "raw_category": "Technology",
            "tags": ["AI", "software"],
            "title": "SENSITIVE_TITLE_OPENAI_RELEASE",
            "description": "SENSITIVE_DESCRIPTION_MODEL_LAUNCH",
        }
        and bool(first.matched_sources),
        retained_fields=sorted(first.raw_evidence),
        matched_source_count=len(first.matched_sources),
    )

    aggregate_rows = [
        {
            "event_id": 910001,
            "category": "Technology",
            "tags": ["AI", "software"],
            "title": "SENSITIVE_TITLE_OPENAI_RELEASE",
            "description": "SENSITIVE_DESCRIPTION_MODEL_LAUNCH",
        },
        {
            "event_id": 910002,
            "category": "Sports",
            "tags": ["NBA"],
            "title": "SENSITIVE_TITLE_BASKETBALL_FINAL",
            "description": "SENSITIVE_DESCRIPTION_SPORTS_RESULT",
        },
    ]
    profile, markdown, engine_disposed = _aggregate_profile(aggregate_rows)
    serialized_aggregate = json.dumps(profile, sort_keys=True)
    raw_sentinels = {
        "SENSITIVE_TITLE_OPENAI_RELEASE",
        "SENSITIVE_DESCRIPTION_MODEL_LAUNCH",
        "SENSITIVE_TITLE_BASKETBALL_FINAL",
        "SENSITIVE_DESCRIPTION_SPORTS_RESULT",
    }
    leaked_sentinels = sorted(
        sentinel
        for sentinel in raw_sentinels
        if sentinel in serialized_aggregate or sentinel in markdown
    )
    forbidden_paths = _forbidden_keys(
        profile,
        {"raw_evidence", "event_id", "event_ids", "events", "matched_sources"},
    )
    privacy = profile.get("privacy", {})
    score_margin_total = sum(profile.get("classified_score_margin_buckets", {}).values())
    check(
        "aggregate_profile_has_no_raw_evidence",
        not leaked_sentinels
        and not forbidden_paths
        and privacy.get("aggregate_only") is True
        and privacy.get("event_identifiers_emitted") is False
        and privacy.get("source_text_emitted") is False
        and engine_disposed,
        leaked_sentinels=leaked_sentinels,
        forbidden_paths=forbidden_paths,
        privacy=privacy,
        engine_disposed=engine_disposed,
    )
    check(
        "score_margin_buckets_cover_classified_only",
        score_margin_total == profile["coverage"]["classified_events"] == 1,
        score_margin_total=score_margin_total,
        classified_events=profile["coverage"]["classified_events"],
        total_events=profile["coverage"]["total_events"],
    )

    ok = all(item["ok"] for item in checks)
    print(
        json.dumps(
            {
                "status": "PASS" if ok else "FAIL",
                "ok": ok,
                "check_count": len(checks),
                "checks": checks,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
