"""Profile aggregate research-category reconstruction without exposing event text."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_platform.services.research_categories import (  # noqa: E402
    classify_research_category,
    load_category_config,
)


SCHEMA_VERSION = 1
REQUIRED_TABLES = {"market_event", "market_tag", "market_tag_map"}
SAFE_EVIDENCE_SOURCES = {"raw_category", "tag", "title", "description"}
RESEARCH_CATEGORIES = {"politics", "crypto", "finance", "technology", "geopolitics"}


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate aggregate-only evidence for research-category reconstruction."
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL", ""),
        help="PostgreSQL SQLAlchemy URL. Defaults to DATABASE_URL.",
    )
    parser.add_argument("--output-json", default="", help="Optional JSON evidence path.")
    parser.add_argument("--output-markdown", default="", help="Optional Markdown evidence path.")
    return parser.parse_args()


def _value(result: Any, name: str, default: Any = None) -> Any:
    """Read one classifier result field from a dataclass-like object or mapping."""
    if isinstance(result, dict):
        return result.get(name, default)
    return getattr(result, name, default)


def _confidence_bucket(value: Any) -> str:
    """Return a stable aggregate confidence bucket."""
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return "not_reported"
    if confidence >= 0.80:
        return "high"
    if confidence >= 0.60:
        return "medium"
    return "low"


def _safe_sources(result: Any) -> set[str]:
    """Return only approved source names, never matched source content."""
    raw_sources = _value(result, "matched_sources", ()) or ()
    if isinstance(raw_sources, str):
        raw_sources = (raw_sources,)
    normalized: set[str] = set()
    for source in raw_sources:
        if isinstance(source, dict):
            raw_name = source.get("field", "")
        else:
            raw_name = getattr(source, "field", "")
        name = str(raw_name).strip().lower().replace("-", "_")
        if name.startswith("tag[") or name == "tags":
            name = "tag"
        if name in SAFE_EVIDENCE_SOURCES:
            normalized.add(name)
    return normalized


def profile_category_reconstruction(database_url: str) -> dict[str, Any]:
    """Classify event evidence in memory and return aggregate-only coverage."""
    if not database_url:
        raise ValueError("A database URL is required via --database-url or DATABASE_URL.")

    # Validate the versioned configuration even when the source database is empty.
    load_category_config()
    engine = create_engine(database_url, future=True, pool_pre_ping=True)
    try:
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
            with connection.begin():
                connection.execute(text("SET TRANSACTION READ ONLY"))
                found = set(
                    connection.execute(
                        text(
                            """
                            SELECT table_name
                            FROM information_schema.tables
                            WHERE table_schema = 'analytics'
                            """
                        )
                    ).scalars()
                )
                missing = sorted(REQUIRED_TABLES - found)
                if missing:
                    raise RuntimeError(
                        "Category profiling requires these missing analytics tables: "
                        + ", ".join(missing)
                    )

                rows = connection.execute(
                    text(
                        """
                        SELECT
                          event.event_id,
                          event.category,
                          event.title,
                          event.description,
                          COALESCE(
                            ARRAY_AGG(DISTINCT tag_value.value)
                              FILTER (WHERE tag_value.value IS NOT NULL),
                            ARRAY[]::varchar[]
                          ) AS tags
                        FROM analytics.market_event AS event
                        LEFT JOIN analytics.market_tag_map AS tag_map
                          ON tag_map.event_id = event.event_id
                        LEFT JOIN analytics.market_tag AS tag
                          ON tag.tag_id = tag_map.tag_id
                        LEFT JOIN LATERAL (
                          VALUES (tag.tag_label), (tag.tag_slug)
                        ) AS tag_value(value) ON TRUE
                        GROUP BY event.event_id, event.category, event.title, event.description
                        ORDER BY event.event_id
                        """
                    )
                ).mappings()

                total = 0
                category_counts: Counter[str] = Counter()
                status_counts: Counter[str] = Counter()
                confidence_counts: Counter[str] = Counter()
                evidence_counts: Counter[str] = Counter()
                category_status_counts: dict[str, Counter[str]] = defaultdict(Counter)
                for row in rows:
                    total += 1
                    result = classify_research_category(
                        raw_category=row.get("category"),
                        tags=tuple(row.get("tags") or ()),
                        title=row.get("title"),
                        description=row.get("description"),
                    )
                    category = str(_value(result, "category", "") or "").strip().lower()
                    status = str(_value(result, "status", "review") or "review").strip().lower()
                    if category and category not in RESEARCH_CATEGORIES:
                        raise RuntimeError(f"Classifier returned unsupported category: {category}")
                    aggregate_category = category or "unassigned"
                    category_counts[aggregate_category] += 1
                    status_counts[status] += 1
                    category_status_counts[aggregate_category][status] += 1
                    confidence_counts[_confidence_bucket(_value(result, "confidence"))] += 1
                    sources = _safe_sources(result)
                    if not sources:
                        evidence_counts["none"] += 1
                    else:
                        for source in sources:
                            evidence_counts[source] += 1

        assigned = total - int(category_counts["unassigned"])
        review_count = int(status_counts.get("review", 0))
        unmapped_count = int(status_counts.get("unmapped", 0))
        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "privacy": {
                "aggregate_only": True,
                "event_identifiers_emitted": False,
                "source_text_emitted": False,
                "wallet_identifiers_emitted": False,
            },
            "coverage": {
                "total_events": total,
                "assigned_events": assigned,
                "assigned_rate": round(assigned / total, 6) if total else None,
                "classified_events": int(status_counts.get("classified", 0)),
                "classified_rate": (
                    round(int(status_counts.get("classified", 0)) / total, 6)
                    if total
                    else None
                ),
                "review_events": review_count,
                "review_rate": round(review_count / total, 6) if total else None,
                "unmapped_events": unmapped_count,
                "unmapped_rate": round(unmapped_count / total, 6) if total else None,
            },
            "category_counts": dict(sorted(category_counts.items())),
            "status_counts": dict(sorted(status_counts.items())),
            "confidence_buckets": dict(sorted(confidence_counts.items())),
            "evidence_source_counts": dict(sorted(evidence_counts.items())),
            "category_status_counts": {
                category: dict(sorted(counts.items()))
                for category, counts in sorted(category_status_counts.items())
            },
            "interpretation": {
                "status": "descriptive_reconstruction_profile",
                "category_level_modelling_approved": False,
                "review_required": True,
                "warning": (
                    "Coverage is generated by deterministic rules and must be independently reviewed; "
                    "review and unmapped events remain excluded from category-level modelling."
                ),
            },
        }
    finally:
        engine.dispose()


def render_markdown(profile: dict[str, Any]) -> str:
    """Render an aggregate-only Markdown summary."""
    coverage = profile["coverage"]
    lines = [
        "# Category Reconstruction Profile",
        "",
        f"Generated: `{profile['generated_at']}`",
        "",
        "This evidence is aggregate-only. It contains no event identifiers, source text, tags, slugs, or wallet data.",
        "",
        "## Coverage",
        "",
        f"- Total events: {coverage['total_events']:,}",
        f"- Assigned events: {coverage['assigned_events']:,} ({coverage['assigned_rate']})",
        f"- Classified events: {coverage['classified_events']:,} ({coverage['classified_rate']})",
        f"- Review events: {coverage['review_events']:,} ({coverage['review_rate']})",
        f"- Unmapped events: {coverage['unmapped_events']:,} ({coverage['unmapped_rate']})",
        "",
        "## Category Counts",
        "",
        "| Category | Events |",
        "| --- | ---: |",
    ]
    lines.extend(
        f"| {category} | {int(count):,} |"
        for category, count in profile["category_counts"].items()
    )
    lines.extend(
        [
            "",
            "## Decision Status",
            "",
            "| Status | Events |",
            "| --- | ---: |",
        ]
    )
    lines.extend(
        f"| {status} | {int(count):,} |"
        for status, count in profile["status_counts"].items()
    )
    lines.extend(
        [
            "",
            "## Category and Decision Status",
            "",
            "| Category | Status | Events |",
            "| --- | --- | ---: |",
        ]
    )
    for category, status_counts in profile["category_status_counts"].items():
        lines.extend(
            f"| {category} | {status} | {int(count):,} |"
            for status, count in status_counts.items()
        )
    lines.extend(
        [
            "",
            "## Evidence Sources",
            "",
            "Counts indicate events with at least one match from the source; an event may appear in more than one row.",
            "",
            "| Evidence source | Events |",
            "| --- | ---: |",
        ]
    )
    lines.extend(
        f"| {source} | {int(count):,} |"
        for source, count in profile["evidence_source_counts"].items()
    )
    lines.extend(
        [
            "",
            "Deterministic reconstruction does not approve category-level modelling. Review and unmapped events remain excluded until an independent category-quality gate passes.",
            "",
        ]
    )
    return "\n".join(lines)


def _write(path_value: str, content: str) -> None:
    """Write one optional evidence artifact."""
    if not path_value:
        return
    path = Path(path_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> int:
    """CLI entry point."""
    args = parse_args()
    try:
        profile = profile_category_reconstruction(args.database_url)
        json_text = json.dumps(profile, indent=2, sort_keys=True) + "\n"
        _write(args.output_json, json_text)
        _write(args.output_markdown, render_markdown(profile))
    except (FileNotFoundError, OSError, RuntimeError, SQLAlchemyError, ValueError) as exc:
        print(f"category reconstruction profile failed: {exc}", file=sys.stderr)
        return 2
    print(json_text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
