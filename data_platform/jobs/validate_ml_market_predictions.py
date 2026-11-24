"""Validate matured ML market predictions against observed Polymarket trade prices."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import sys
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from data_platform.db.session import session_scope
from data_platform.models import MlMarketPredictionValidation
from data_platform.models.base import utc_now


DEFAULT_LIMIT = 1000
DEFAULT_TARGET_TOLERANCE_MINUTES = 60
VALIDATION_MODEL_VERSION = "market_profile_prediction_validation_v2"


@dataclass(frozen=True)
class ActualOutcome:
    """Actual target-time probability for one predicted market side."""

    actual_future_odds_pct: float
    actual_source: str
    actual_source_detail: str
    actual_observed_at: datetime | None
    target_delay_seconds: int | None
    payload: dict[str, Any]


def _parse_as_of(value: str | None) -> datetime:
    """Return the scoring timestamp."""
    if not value:
        return utc_now()
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _effective_tolerance(minutes: int) -> int:
    """Keep caller-supplied tolerance within the supported forward window."""
    return min(max(minutes, 0), DEFAULT_TARGET_TOLERANCE_MINUTES)


def _safe_float(value: Any) -> float | None:
    """Return a finite float for DB numeric values."""
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _round(value: float | None, places: int = 6) -> float | None:
    """Round nullable floats for stable DB payloads."""
    return None if value is None else round(float(value), places)


def _direction_from_delta(delta: float | None) -> str | None:
    """Return the dashboard direction bucket for a percentage-point delta."""
    if delta is None:
        return None
    if delta > 0.25:
        return "up"
    if delta < -0.25:
        return "down"
    return "flat"


def _table_exists(session: Session, schema: str, table_name: str) -> bool:
    """Return whether a database table exists."""
    row = session.execute(
        text("SELECT to_regclass(:qualified_name) IS NOT NULL AS table_exists"),
        {"qualified_name": f"{schema}.{table_name}"},
    ).mappings().first()
    return bool(row and row.get("table_exists"))


def _candidate_rows(
    session: Session,
    *,
    platform_name: str,
    as_of: datetime,
    limit: int,
    revalidate: bool,
    tolerance_minutes: int = DEFAULT_TARGET_TOLERANCE_MINUTES,
) -> list[dict[str, Any]]:
    """Return snapshots after their entire forward window has matured."""
    tolerance_minutes = _effective_tolerance(tolerance_minutes)
    stale_validation = """
        v.validation_payload ->> 'validation_model_version' IS DISTINCT FROM :validation_model_version
        OR v.validation_payload ->> 'target_tolerance_minutes' IS DISTINCT FROM :target_tolerance_minutes
    """
    validation_filter = ""
    if not revalidate:
        validation_filter = f"""
          AND (
            ({stale_validation})
            OR v.validation_status IN ('missing_actual', 'awaiting_actual')
          )
        """
    limit_clause = "" if limit <= 0 else "LIMIT :limit"
    query = text(
        f"""
        SELECT
          s.ml_market_prediction_snapshot_id,
          s.platform_id,
          s.market_contract_id,
          s.market_slug,
          s.side_label,
          s.prediction_window_hours,
          s.observation_time,
          s.prediction_target_time,
          s.prediction_generated_at,
          s.current_odds_pct,
          s.predicted_future_odds_pct,
          s.predicted_delta_pts,
          s.prediction_payload,
          mc.outcome_a_label,
          mc.outcome_b_label,
          mc.condition_ref
        FROM analytics.ml_market_prediction_snapshot s
        JOIN analytics.market_contract mc
          ON mc.market_contract_id = s.market_contract_id
         AND mc.platform_id = s.platform_id
        JOIN analytics.platform p
          ON p.platform_id = s.platform_id
        LEFT JOIN analytics.ml_market_prediction_validation v
          ON v.ml_market_prediction_snapshot_id = s.ml_market_prediction_snapshot_id
        WHERE p.platform_name = :platform_name
          AND s.prediction_window_hours IN (12, 24)
          AND s.prediction_target_time = s.observation_time
              + s.prediction_window_hours * INTERVAL '1 hour'
          AND s.prediction_generated_at < s.prediction_target_time
          AND s.prediction_target_time <= :matured_through
          AND s.prediction_generated_at <= :as_of
          AND s.predicted_future_odds_pct IS NOT NULL
          {validation_filter}
        ORDER BY CASE WHEN ({stale_validation}) THEN 0 ELSE 1 END,
                 v.validated_at ASC NULLS FIRST,
                 s.prediction_target_time ASC, s.ml_market_prediction_snapshot_id ASC
        {limit_clause}
        """
    )
    params: dict[str, Any] = {
        "platform_name": platform_name,
        "as_of": as_of,
        "matured_through": as_of - timedelta(minutes=tolerance_minutes),
        "validation_model_version": VALIDATION_MODEL_VERSION,
        "target_tolerance_minutes": str(tolerance_minutes),
    }
    if limit > 0:
        params["limit"] = limit
    return [dict(row) for row in session.execute(query, params).mappings().all()]


ACTUAL_TRADE_SQL = text(
    """
    SELECT transaction_id, transaction_time, price
    FROM analytics.transaction_fact
    WHERE market_contract_id = :market_contract_id
      AND platform_id = :platform_id
      AND transaction_type = 'trade'
      AND LOWER(BTRIM(outcome_label)) = LOWER(BTRIM(:side_label))
      AND price BETWEEN 0 AND 1
      AND transaction_time >= :target_time
      AND transaction_time <= :window_end
    ORDER BY transaction_time ASC, transaction_id ASC
    LIMIT 1
    """
)


def _actual_outcome(
    session: Session,
    row: dict[str, Any],
    *,
    tolerance_minutes: int,
) -> ActualOutcome | None:
    """Select the earliest eligible trade for the exact contract and side."""
    target_time = row.get("prediction_target_time")
    side_label = str(row.get("side_label") or "").strip()
    if target_time is None or not side_label:
        return None

    tolerance_minutes = _effective_tolerance(tolerance_minutes)
    trade = session.execute(
        ACTUAL_TRADE_SQL,
        {
            "market_contract_id": int(row["market_contract_id"]),
            "platform_id": int(row["platform_id"]),
            "side_label": side_label,
            "target_time": target_time,
            "window_end": target_time + timedelta(minutes=tolerance_minutes),
        },
    ).mappings().first()
    if trade is None:
        return None
    observed_at = trade["transaction_time"]
    source_price = float(trade["price"])
    return ActualOutcome(
        actual_future_odds_pct=source_price * 100.0,
        actual_source="transaction_fact",
        actual_source_detail=f"transaction_fact:{trade['transaction_id']}",
        actual_observed_at=observed_at,
        target_delay_seconds=int((observed_at - target_time).total_seconds()),
        payload={"source_price": _round(source_price), "target_tolerance_minutes": tolerance_minutes},
    )


def _validation_row(
    session: Session,
    row: dict[str, Any],
    *,
    tolerance_minutes: int,
) -> dict[str, Any]:
    """Return an upsert-ready validation row for one prediction snapshot."""
    now = utc_now()
    tolerance_minutes = _effective_tolerance(tolerance_minutes)
    actual = _actual_outcome(session, row, tolerance_minutes=tolerance_minutes)
    current_pct = _safe_float(row.get("current_odds_pct"))
    predicted_future_pct = _safe_float(row.get("predicted_future_odds_pct"))
    predicted_delta = _safe_float(row.get("predicted_delta_pts"))
    if predicted_delta is None and predicted_future_pct is not None and current_pct is not None:
        predicted_delta = predicted_future_pct - current_pct
    predicted_direction = _direction_from_delta(predicted_delta)
    prediction_payload = row.get("prediction_payload") if isinstance(row.get("prediction_payload"), dict) else {}

    actual_future_pct = actual.actual_future_odds_pct if actual else None
    actual_delta = None if actual_future_pct is None or current_pct is None else actual_future_pct - current_pct
    actual_direction = _direction_from_delta(actual_delta)
    signed_error = None
    absolute_error = None
    squared_error = None
    direction_match = None
    validation_status = "missing_actual"
    if predicted_future_pct is not None and actual_future_pct is not None:
        signed_error = predicted_future_pct - actual_future_pct
        absolute_error = abs(signed_error)
        squared_error = signed_error * signed_error
        direction_match = predicted_direction == actual_direction
        validation_status = "validated"

    validation_payload = {
        "validation_model_version": VALIDATION_MODEL_VERSION,
        "target_tolerance_minutes": tolerance_minutes,
        "market_contract_id": row.get("market_contract_id"),
        "condition_ref": row.get("condition_ref"),
        "outcome_a_label": row.get("outcome_a_label"),
        "outcome_b_label": row.get("outcome_b_label"),
        "prediction_status": prediction_payload.get("prediction_status"),
        "prediction_source": prediction_payload.get("prediction_source"),
        "direction_signal_tier": prediction_payload.get("direction_signal_tier"),
        "display_tier": prediction_payload.get("display_tier"),
        "whale_anchor": prediction_payload.get("whale_anchor") or {},
        "actual": actual.payload if actual else {
            "reason": "no eligible same-outcome trade in the forward target window"
        },
    }

    return {
        "ml_market_prediction_snapshot_id": int(row["ml_market_prediction_snapshot_id"]),
        "platform_id": int(row["platform_id"]),
        "market_contract_id": int(row["market_contract_id"]),
        "market_slug": str(row["market_slug"]),
        "side_label": str(row["side_label"]),
        "prediction_window_hours": int(row["prediction_window_hours"]),
        "observation_time": row["observation_time"],
        "prediction_target_time": row["prediction_target_time"],
        "prediction_generated_at": row["prediction_generated_at"],
        "current_odds_pct": _round(current_pct),
        "predicted_future_odds_pct": _round(predicted_future_pct),
        "predicted_delta_pts": _round(predicted_delta),
        "actual_future_odds_pct": _round(actual_future_pct),
        "actual_delta_pts": _round(actual_delta),
        "signed_error_pts": _round(signed_error),
        "absolute_error_pts": _round(absolute_error),
        "squared_error_pts": _round(squared_error),
        "predicted_direction": predicted_direction,
        "actual_direction": actual_direction,
        "direction_match": direction_match,
        "validation_status": validation_status,
        "actual_source": actual.actual_source if actual else None,
        "actual_source_detail": actual.actual_source_detail if actual else None,
        "actual_observed_at": actual.actual_observed_at if actual else None,
        "target_delay_seconds": actual.target_delay_seconds if actual else None,
        "validation_payload": validation_payload,
        "validated_at": now,
        "created_at": now,
        "updated_at": now,
    }


def _upsert_validations(session: Session, rows: list[dict[str, Any]]) -> None:
    """Persist validation rows idempotently."""
    if not rows:
        return
    statement = pg_insert(MlMarketPredictionValidation).values(rows)
    statement = statement.on_conflict_do_update(
        constraint="uq_ml_market_prediction_validation_snapshot",
        set_={
            "actual_future_odds_pct": statement.excluded.actual_future_odds_pct,
            "actual_delta_pts": statement.excluded.actual_delta_pts,
            "signed_error_pts": statement.excluded.signed_error_pts,
            "absolute_error_pts": statement.excluded.absolute_error_pts,
            "squared_error_pts": statement.excluded.squared_error_pts,
            "predicted_direction": statement.excluded.predicted_direction,
            "actual_direction": statement.excluded.actual_direction,
            "direction_match": statement.excluded.direction_match,
            "validation_status": statement.excluded.validation_status,
            "actual_source": statement.excluded.actual_source,
            "actual_source_detail": statement.excluded.actual_source_detail,
            "actual_observed_at": statement.excluded.actual_observed_at,
            "target_delay_seconds": statement.excluded.target_delay_seconds,
            "validation_payload": statement.excluded.validation_payload,
            "validated_at": statement.excluded.validated_at,
            "updated_at": statement.excluded.updated_at,
        },
    )
    session.execute(statement)


def _empty_metric_summary() -> dict[str, Any]:
    """Return an empty metrics object."""
    return {
        "validated_count": 0,
        "missing_actual_count": 0,
        "mae_pts": None,
        "rmse_pts": None,
        "direction_accuracy": None,
    }


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Return compact validation metrics from rows processed in this run."""
    by_window: dict[str, dict[str, Any]] = {}
    by_source: dict[str, int] = {}
    validated_rows = [row for row in rows if row.get("validation_status") == "validated"]
    for row in rows:
        window_name = f"{int(row['prediction_window_hours'])}h"
        bucket = by_window.setdefault(window_name, _empty_metric_summary())
        if row.get("validation_status") == "validated":
            bucket["validated_count"] += 1
        else:
            bucket["missing_actual_count"] += 1
        source = str(row.get("actual_source") or row.get("validation_status") or "unknown")
        by_source[source] = by_source.get(source, 0) + 1

    for window_name, bucket in by_window.items():
        window_rows = [
            row
            for row in rows
            if f"{int(row['prediction_window_hours'])}h" == window_name and row.get("validation_status") == "validated"
        ]
        if not window_rows:
            continue
        abs_errors = [float(row["absolute_error_pts"]) for row in window_rows if row.get("absolute_error_pts") is not None]
        squared_errors = [float(row["squared_error_pts"]) for row in window_rows if row.get("squared_error_pts") is not None]
        direction_values = [bool(row["direction_match"]) for row in window_rows if row.get("direction_match") is not None]
        bucket["mae_pts"] = round(sum(abs_errors) / len(abs_errors), 6) if abs_errors else None
        bucket["rmse_pts"] = round(math.sqrt(sum(squared_errors) / len(squared_errors)), 6) if squared_errors else None
        bucket["direction_accuracy"] = (
            round(sum(1 for value in direction_values if value) / len(direction_values), 6)
            if direction_values
            else None
        )

    return {
        "candidate_count": len(rows),
        "validated_count": len(validated_rows),
        "missing_actual_count": len(rows) - len(validated_rows),
        "by_window": by_window,
        "by_source": by_source,
    }


def validate_predictions(
    session: Session,
    *,
    platform_name: str,
    as_of: datetime,
    limit: int,
    target_tolerance_minutes: int,
    create_table: bool,
    revalidate: bool,
) -> dict[str, Any]:
    """Validate matured prediction snapshots and persist actual-vs-predicted errors."""
    target_tolerance_minutes = _effective_tolerance(target_tolerance_minutes)
    if create_table:
        MlMarketPredictionValidation.__table__.create(bind=session.get_bind(), checkfirst=True)
    if not _table_exists(session, "analytics", "ml_market_prediction_validation"):
        return {
            "ok": False,
            "reason": "ml_market_prediction_validation_table_missing",
            "hint": "Run Alembic migration 20260506_1000 or pass --create-table for local testing.",
        }

    candidates = _candidate_rows(
        session,
        platform_name=platform_name,
        as_of=as_of,
        limit=limit,
        revalidate=revalidate,
        tolerance_minutes=target_tolerance_minutes,
    )
    validation_rows = [
        _validation_row(session, row, tolerance_minutes=target_tolerance_minutes)
        for row in candidates
    ]
    _upsert_validations(session, validation_rows)
    return {
        "ok": True,
        "as_of": as_of.isoformat(),
        "platform": platform_name,
        "target_tolerance_minutes": target_tolerance_minutes,
        "limit": limit,
        "revalidate": revalidate,
        **_summary(validation_rows),
    }


def parse_args() -> argparse.Namespace:
    """Parse CLI args."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL", ""))
    parser.add_argument("--platform-name", default=os.getenv("ML_PREDICTION_VALIDATION_PLATFORM", "polymarket"))
    parser.add_argument("--as-of", default="", help="Validation timestamp. Defaults to now.")
    parser.add_argument(
        "--limit",
        type=int,
        default=int(os.getenv("ML_PREDICTION_VALIDATION_LIMIT", str(DEFAULT_LIMIT))),
        help="Maximum matured prediction snapshots to validate. Use 0 for no cap.",
    )
    parser.add_argument(
        "--target-tolerance-minutes",
        type=int,
        default=int(os.getenv("ML_PREDICTION_VALIDATION_TARGET_TOLERANCE_MINUTES", str(DEFAULT_TARGET_TOLERANCE_MINUTES))),
        help="Maximum time after the 12h/24h target to match a same-outcome trade, capped at 60 minutes.",
    )
    parser.add_argument("--revalidate", action="store_true", help="Rescore already validated snapshots.")
    parser.add_argument("--create-table", action="store_true", help="Create the validation table when running locally.")
    return parser.parse_args()


def main() -> int:
    """CLI entrypoint."""
    args = parse_args()
    as_of = _parse_as_of(args.as_of)
    with session_scope(args.database_url or None) as session:
        summary = validate_predictions(
            session,
            platform_name=str(args.platform_name),
            as_of=as_of,
            limit=int(args.limit),
            target_tolerance_minutes=max(int(args.target_tolerance_minutes), 0),
            create_table=bool(args.create_table),
            revalidate=bool(args.revalidate),
        )
    print(json.dumps(summary, sort_keys=True, default=str))
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
