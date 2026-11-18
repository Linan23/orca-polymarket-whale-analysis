"""Profile aggregate historical Polymarket coverage without exposing row-level data."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection


SCHEMA_VERSION = 1
ANALYTICS_SCHEMA = "analytics"
REQUIRED_TABLES = (
    "market_event",
    "market_contract",
    "transaction_fact",
    "position_snapshot",
    "orderbook_snapshot",
    "user_account",
    "whale_score_snapshot",
    "resolved_condition",
    "ml_market_prediction_snapshot",
    "ml_market_prediction_validation",
)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate an aggregate, read-only profile of the historical analytics database."
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL", ""),
        help="PostgreSQL SQLAlchemy URL. Defaults to DATABASE_URL.",
    )
    parser.add_argument("--output-json", default="", help="Optional JSON evidence path.")
    parser.add_argument("--output-markdown", default="", help="Optional Markdown summary path.")
    return parser.parse_args()


def _rows(connection: Connection, query: str) -> list[dict[str, Any]]:
    """Execute one fixed aggregate query and return mapping dictionaries."""
    return [dict(row) for row in connection.execute(text(query)).mappings().all()]


def _scalar(connection: Connection, query: str) -> Any:
    """Execute one fixed aggregate query and return its scalar value."""
    return connection.execute(text(query)).scalar_one()


def _json_value(value: Any) -> Any:
    """Convert database values into stable JSON-compatible values."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _check_required_tables(connection: Connection) -> None:
    """Fail clearly when the historical schema is incomplete."""
    found = set(
        connection.execute(
            text(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = :schema_name
                """
            ),
            {"schema_name": ANALYTICS_SCHEMA},
        ).scalars()
    )
    missing = sorted(set(REQUIRED_TABLES) - found)
    if missing:
        raise RuntimeError(
            "Historical profiling requires these missing analytics tables: " + ", ".join(missing)
        )


def _table_counts(connection: Connection) -> dict[str, int]:
    """Return aggregate row counts for the approved analytical tables."""
    counts: dict[str, int] = {}
    for table_name in REQUIRED_TABLES:
        # Table names come only from the fixed REQUIRED_TABLES constant.
        counts[table_name] = int(_scalar(connection, f'SELECT COUNT(*) FROM "analytics"."{table_name}"'))
    return counts


def profile_database(database_url: str) -> dict[str, Any]:
    """Return an aggregate profile collected inside a read-only transaction."""
    if not database_url:
        raise ValueError("A database URL is required via --database-url or DATABASE_URL.")

    engine = create_engine(database_url, future=True, pool_pre_ping=True)
    try:
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
            with connection.begin():
                connection.execute(text("SET TRANSACTION READ ONLY"))
                _check_required_tables(connection)

                database_name = str(_scalar(connection, "SELECT current_database()"))
                server_version = str(_scalar(connection, "SHOW server_version"))
                table_counts = _table_counts(connection)

                transaction_coverage = dict(
                    connection.execute(
                        text(
                            """
                            SELECT
                              MIN(transaction_time) AS first_transaction_at,
                              MAX(transaction_time) AS last_transaction_at,
                              COUNT(DISTINCT user_id) AS distinct_traders,
                              COUNT(DISTINCT market_contract_id) AS traded_contracts,
                              COUNT(DISTINCT event_id) AS traded_events
                            FROM analytics.transaction_fact
                            """
                        )
                    ).mappings().one()
                )
                market_coverage = dict(
                    connection.execute(
                        text(
                            """
                            SELECT
                              MIN(start_time) AS first_market_start_at,
                              MAX(end_time) AS last_market_end_at,
                              COUNT(*) FILTER (WHERE is_closed) AS closed_contracts,
                              COUNT(*) FILTER (WHERE is_active) AS active_contracts,
                              COUNT(*) FILTER (WHERE condition_ref IS NULL OR condition_ref = '')
                                AS missing_condition_ref
                            FROM analytics.market_contract
                            """
                        )
                    ).mappings().one()
                )
                category_rows = _rows(
                    connection,
                    """
                    SELECT
                      COALESCE(NULLIF(BTRIM(category), ''), 'uncategorized') AS raw_category,
                      COUNT(*) AS event_count
                    FROM analytics.market_event
                    GROUP BY 1
                    ORDER BY event_count DESC, raw_category ASC
                    """,
                )
                categorized_events = sum(
                    int(row["event_count"])
                    for row in category_rows
                    if row["raw_category"] != "uncategorized"
                )
                total_events = int(table_counts["market_event"])
                category_coverage = {
                    "categorized_event_count": categorized_events,
                    "uncategorized_event_count": total_events - categorized_events,
                    "categorized_event_rate": (
                        round(categorized_events / total_events, 6) if total_events else None
                    ),
                    "raw_categories": category_rows,
                }
                resolved_coverage = dict(
                    connection.execute(
                        text(
                            """
                            SELECT
                              MIN(resolved_at) AS first_resolved_at,
                              MAX(resolved_at) AS last_resolved_at,
                              COUNT(*) FILTER (WHERE resolved_at IS NULL) AS missing_resolved_at,
                              MIN(confidence) AS minimum_confidence,
                              AVG(confidence) AS average_confidence,
                              MAX(confidence) AS maximum_confidence,
                              SUM(trade_count) AS supporting_trade_count
                            FROM analytics.resolved_condition
                            """
                        )
                    ).mappings().one()
                )
                resolver_methods = _rows(
                    connection,
                    """
                    SELECT resolver_method, COUNT(*) AS condition_count
                    FROM analytics.resolved_condition
                    GROUP BY resolver_method
                    ORDER BY condition_count DESC, resolver_method ASC
                    """,
                )
                prediction_coverage = dict(
                    connection.execute(
                        text(
                            """
                            SELECT
                              MIN(prediction_generated_at) AS first_prediction_at,
                              MAX(prediction_generated_at) AS last_prediction_at,
                              COUNT(DISTINCT market_contract_id) AS predicted_contracts
                            FROM analytics.ml_market_prediction_snapshot
                            """
                        )
                    ).mappings().one()
                )
                validation_statuses = _rows(
                    connection,
                    """
                    SELECT
                      prediction_window_hours,
                      validation_status,
                      COUNT(*) AS validation_count,
                      AVG(absolute_error_pts) AS mean_absolute_error_points,
                      AVG(CASE WHEN direction_match THEN 1.0 ELSE 0.0 END)
                        FILTER (WHERE direction_match IS NOT NULL) AS direction_match_rate
                    FROM analytics.ml_market_prediction_validation
                    GROUP BY prediction_window_hours, validation_status
                    ORDER BY prediction_window_hours, validation_status
                    """,
                )

        generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        profile = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": generated_at,
            "privacy": {
                "aggregation_only": True,
                "wallet_identifiers_emitted": False,
                "raw_transactions_emitted": False,
            },
            "source": {
                "database_name": database_name,
                "database_url_recorded": False,
                "server": "PostgreSQL",
                "server_version": server_version,
                "transaction_isolation": "REPEATABLE READ, READ ONLY",
            },
            "table_counts": table_counts,
            "transaction_coverage": transaction_coverage,
            "market_coverage": market_coverage,
            "category_coverage": category_coverage,
            "resolved_condition_coverage": {
                **resolved_coverage,
                "resolver_methods": resolver_methods,
            },
            "prediction_validation_coverage": {
                **prediction_coverage,
                "validation_statuses": validation_statuses,
            },
            "interpretation": {
                "status": "descriptive_source_profile",
                "causal_claim_supported": False,
                "model_performance_claim_supported": False,
                "authoritative_outcome_ground_truth_established": False,
                "resolution_label_warning": (
                    "Resolver outputs based on trade-price thresholds or fallback heuristics are candidate labels, "
                    "not authoritative final-outcome ground truth. Validate them against an approved resolution source "
                    "before outcome modelling or headline evaluation."
                ),
            },
        }
        return _json_value(profile)
    finally:
        engine.dispose()


def render_markdown(profile: dict[str, Any]) -> str:
    """Render the aggregate profile as a compact Markdown evidence summary."""
    counts = profile["table_counts"]
    transactions = profile["transaction_coverage"]
    markets = profile["market_coverage"]
    categories = profile["category_coverage"]
    resolved = profile["resolved_condition_coverage"]
    predictions = profile["prediction_validation_coverage"]
    interpretation = profile["interpretation"]
    lines = [
        "# Historical Data Profile",
        "",
        f"Generated: `{profile['generated_at']}`",
        "",
        "This is aggregate source evidence. It contains no wallet identifiers or raw transactions and does not support causal or model-performance claims.",
        "",
        "## Coverage",
        "",
        f"- Transactions: {counts['transaction_fact']:,}",
        f"- Distinct traders: {transactions['distinct_traders']:,}",
        f"- Traded contracts: {transactions['traded_contracts']:,}",
        f"- Transaction period: {transactions['first_transaction_at']} to {transactions['last_transaction_at']}",
        f"- Market events: {counts['market_event']:,}",
        f"- Market contracts: {counts['market_contract']:,}",
        f"- Resolved conditions: {counts['resolved_condition']:,}",
        f"- Prediction snapshots: {counts['ml_market_prediction_snapshot']:,}",
        f"- Prediction validations: {counts['ml_market_prediction_validation']:,}",
        "",
        "## Category Quality",
        "",
        f"- Categorized events: {categories['categorized_event_count']:,}",
        f"- Uncategorized events: {categories['uncategorized_event_count']:,}",
        f"- Categorized rate: {categories['categorized_event_rate']}",
        "",
        "| Raw category | Events |",
        "| --- | ---: |",
    ]
    lines.extend(
        f"| {row['raw_category']} | {int(row['event_count']):,} |"
        for row in categories["raw_categories"]
    )
    lines.extend(
        [
            "",
            "## Resolution and Validation",
            "",
            f"- Closed contracts: {markets['closed_contracts']:,}",
            f"- Resolved-condition rows: {counts['resolved_condition']:,}",
            f"- Resolution period: {resolved['first_resolved_at']} to {resolved['last_resolved_at']}",
            f"- Resolutions missing timestamps: {resolved['missing_resolved_at']:,}",
            f"- Resolver confidence range: {resolved['minimum_confidence']} to {resolved['maximum_confidence']}",
            f"- Average resolver confidence: {resolved['average_confidence']}",
            f"- Predicted contracts: {predictions['predicted_contracts']:,}",
            "",
            "| Resolver method | Conditions |",
            "| --- | ---: |",
        ]
    )
    lines.extend(
        f"| {row['resolver_method']} | {int(row['condition_count']):,} |"
        for row in resolved["resolver_methods"]
    )
    lines.extend(
        [
            "",
            f"**Outcome-label warning:** {interpretation['resolution_label_warning']}",
            "",
            "The low validation count or poor category coverage, when present, is a data-gate limitation rather than model evidence.",
            "",
        ]
    )
    return "\n".join(lines)


def _write_output(path_value: str, content: str) -> None:
    """Write one optional evidence output, creating parent directories."""
    if not path_value:
        return
    path = Path(path_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> int:
    """CLI entry point."""
    args = parse_args()
    profile = profile_database(args.database_url)
    json_text = json.dumps(profile, indent=2, sort_keys=True) + "\n"
    _write_output(args.output_json, json_text)
    _write_output(args.output_markdown, render_markdown(profile))
    print(json_text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
