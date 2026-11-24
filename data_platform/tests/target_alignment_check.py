"""Regression checks for the exporter and prediction validator's movement labels."""

from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sqlite3
import sys
from tempfile import TemporaryDirectory
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_platform.jobs import validate_ml_market_predictions as validator
from data_platform.ml import market_baseline_model as baseline
from data_platform.ml.market_dataset_builder import _future_price_summary


CUTOFF = datetime(2025, 4, 1, 12, tzinfo=timezone.utc)
MICROSECOND = timedelta(microseconds=1)


def _trade(
    trade_id: int,
    observed_at: datetime,
    price: float | None,
    *,
    contract: int = 10,
    platform: int = 1,
    outcome: str = "Yes",
    kind: str = "trade",
) -> dict:
    return {
        "transaction_id": trade_id,
        "transaction_time": observed_at,
        "market_contract_id": contract,
        "platform_id": platform,
        "outcome_label": outcome,
        "transaction_type": kind,
        "price": price,
    }


def _export_summary(trades: list[dict], horizon: int) -> dict:
    return _future_price_summary(
        condition_transactions=trades,
        market_contract_id=10,
        side_label=" yes ",
        observation_time=CUTOFF,
        market_end_time=CUTOFF + timedelta(hours=4),
        window_hours=horizon,
    )


class ExporterTargetAlignmentCheck(unittest.TestCase):
    def test_uses_exact_side_latest_as_of_and_earliest_forward(self) -> None:
        for horizon in (12, 24):
            with self.subTest(horizon=horizon):
                target = CUTOFF + timedelta(hours=horizon)
                rows = [
                    _trade(2, CUTOFF - timedelta(minutes=5), 0.9),
                    _trade(4, CUTOFF, 0.4, outcome="YES "),
                    _trade(5, CUTOFF, 0.5),
                    _trade(6, CUTOFF + MICROSECOND, 0.8),
                    _trade(7, target - MICROSECOND, 0.7),
                    _trade(9, target, 0.2),
                    _trade(8, target, 0.0, outcome=" yes"),
                    _trade(10, target + MICROSECOND, 0.8),
                    _trade(1, target, 0.1, contract=11),
                    _trade(3, target, 0.3, outcome="No"),
                ]
                result = _export_summary(list(reversed(rows)), horizon)
                self.assertEqual(result[f"movement_anchor_price_{horizon}h"], 0.4)
                self.assertEqual(result[f"future_price_side_{horizon}h"], 0.0)
                self.assertEqual(result[f"future_price_delta_{horizon}h"], -0.4)
                self.assertEqual(result[f"future_price_observed_{horizon}h"], 1)

    def test_accepts_upper_boundary_and_rejects_after_it(self) -> None:
        for horizon in (12, 24):
            with self.subTest(horizon=horizon):
                end = CUTOFF + timedelta(hours=horizon, minutes=60)
                base = _trade(1, CUTOFF, 0.0)
                found = _export_summary([base, _trade(2, end, 0.8)], horizon)
                self.assertEqual(found[f"future_price_delta_{horizon}h"], 0.8)
                missing = _export_summary([base, _trade(2, end + MICROSECOND, 0.8)], horizon)
                self.assertIsNone(missing[f"future_price_side_{horizon}h"])
                self.assertIsNone(missing[f"future_price_delta_{horizon}h"])
                self.assertEqual(missing[f"future_price_observed_{horizon}h"], 0)
                self.assertTrue(missing[f"future_price_missing_reason_{horizon}h"])

    def test_does_not_manufacture_missing_anchor_or_mix_horizons(self) -> None:
        twelve = CUTOFF + timedelta(hours=12)
        rows = [
            _trade(1, CUTOFF, 0.3, contract=11),
            _trade(2, CUTOFF, 0.3, outcome="No"),
            _trade(3, CUTOFF, None),
            _trade(4, CUTOFF, 1.1),
            _trade(5, CUTOFF, 0.4, kind="redeem"),
            _trade(6, twelve, 0.0),
        ]
        missing_anchor = _export_summary(rows, 12)
        self.assertIsNone(missing_anchor["movement_anchor_price_12h"])
        self.assertIsNone(missing_anchor["future_price_delta_12h"])
        self.assertEqual(missing_anchor["future_price_observed_12h"], 0)
        self.assertTrue(missing_anchor["future_price_missing_reason_12h"])
        eligible = [*rows, _trade(7, CUTOFF, 0.2)]
        self.assertEqual(_export_summary(eligible, 12)["future_price_observed_12h"], 1)
        self.assertEqual(_export_summary(eligible, 24)["future_price_observed_24h"], 0)


class _MappingResult:
    """Give the SQL fixture the subset of SQLAlchemy's result interface it uses."""

    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def mappings(self) -> _MappingResult:
        return self

    def first(self) -> dict | None:
        return self.rows[0] if self.rows else None

    def all(self) -> list[dict]:
        return self.rows


class _TradeFixture:
    """Execute the validator's actual trade selection against in-memory rows."""

    def __init__(self, trades: list[dict]) -> None:
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.create_function("btrim", 1, lambda value: value.strip() if value is not None else None)
        self.db.create_function("isfinite", 1, lambda value: value is not None)
        self.db.create_function(
            "add_hours",
            2,
            lambda value, hours: (datetime.fromisoformat(value) + timedelta(hours=hours)).isoformat(
                timespec="microseconds"
            ),
        )
        self.db.execute("ATTACH DATABASE ':memory:' AS analytics")
        self.db.execute(
            """
            CREATE TABLE analytics.transaction_fact (
                transaction_id INTEGER, transaction_time TEXT, market_contract_id INTEGER,
                platform_id INTEGER, outcome_label TEXT, transaction_type TEXT, price REAL
            )
            """
        )
        self.db.executemany(
            """
            INSERT INTO analytics.transaction_fact VALUES (
                :transaction_id, :transaction_time, :market_contract_id, :platform_id,
                :outcome_label, :transaction_type, :price
            )
            """,
            [self._params(trade) for trade in trades],
        )

    @staticmethod
    def _params(values: dict) -> dict:
        return {
            key: value.isoformat(timespec="microseconds") if isinstance(value, datetime) else value
            for key, value in values.items()
        }

    def execute(self, query, params) -> _MappingResult:
        sql = re.sub(
            r"s\.observation_time\s*\+\s*s\.prediction_window_hours\s*\*\s*INTERVAL '1 hour'",
            "add_hours(s.observation_time, s.prediction_window_hours)",
            str(query),
        )
        rows = [dict(row) for row in self.db.execute(sql, self._params(params))]
        for row in rows:
            for name in ("transaction_time", "observed_at"):
                if name in row:
                    row[name] = datetime.fromisoformat(row[name])
        return _MappingResult(rows)


class ValidatorTargetAlignmentCheck(unittest.TestCase):
    def _actual(self, trades: list[dict], target: datetime):
        session = _TradeFixture(trades)
        self.addCleanup(session.db.close)
        return validator._actual_outcome(
            session,
            {
                "market_contract_id": 10,
                "platform_id": 1,
                "side_label": " Yes ",
                "prediction_target_time": target,
                "winning_outcome_label": "Yes",
                "resolved_at": CUTOFF,
            },
            tolerance_minutes=60,
        )

    def test_selects_first_valid_exact_contract_platform_and_side_trade(self) -> None:
        for horizon in (12, 24):
            with self.subTest(horizon=horizon):
                target = CUTOFF + timedelta(hours=horizon)
                actual = self._actual(
                    [
                        _trade(1, target - MICROSECOND, 0.3),
                        _trade(2, target, 0.4, contract=11),
                        _trade(3, target, 0.5, platform=2),
                        _trade(4, target, 0.6, outcome="No"),
                        _trade(5, target, 0.7, kind="redeem"),
                        _trade(6, target, None),
                        _trade(7, target, 1.1),
                        _trade(10, target, 0.8),
                        _trade(8, target, 0.0, outcome="yes"),
                        _trade(9, target + MICROSECOND, 0.9),
                    ],
                    target,
                )
                self.assertIsNotNone(actual)
                self.assertEqual(actual.actual_future_odds_pct, 0.0)
                self.assertEqual(actual.actual_observed_at, target)
                self.assertEqual(actual.target_delay_seconds, 0)

    def test_neither_resolution_nor_out_of_window_trade_can_fill_target(self) -> None:
        target = CUTOFF + timedelta(hours=24)
        end = target + timedelta(minutes=60)
        actual = self._actual([_trade(1, end, 0.75)], target)
        self.assertIsNotNone(actual)
        self.assertEqual(actual.actual_future_odds_pct, 75.0)
        self.assertEqual(actual.target_delay_seconds, 3600)
        missing = self._actual(
            [_trade(1, target - MICROSECOND, 0.2), _trade(2, end + MICROSECOND, 0.5)],
            target,
        )
        self.assertIsNone(missing)

    def test_candidate_maturity_as_of_and_validation_version(self) -> None:
        session = _TradeFixture([])
        self.addCleanup(session.db.close)
        session.db.executescript(
            """
            CREATE TABLE analytics.platform (platform_id INTEGER, platform_name TEXT);
            INSERT INTO analytics.platform VALUES (1, 'polymarket');
            CREATE TABLE analytics.market_contract (
                market_contract_id INTEGER, platform_id INTEGER,
                outcome_a_label TEXT, outcome_b_label TEXT, condition_ref TEXT
            );
            INSERT INTO analytics.market_contract VALUES (10, 1, 'Yes', 'No', 'fixture');
            CREATE TABLE analytics.ml_market_prediction_snapshot (
                ml_market_prediction_snapshot_id INTEGER, platform_id INTEGER,
                market_contract_id INTEGER, market_slug TEXT, side_label TEXT,
                prediction_window_hours INTEGER, observation_time TEXT,
                prediction_target_time TEXT, prediction_generated_at TEXT,
                current_odds_pct REAL, predicted_future_odds_pct REAL,
                predicted_delta_pts REAL, prediction_payload TEXT
            );
            CREATE TABLE analytics.ml_market_prediction_validation (
                ml_market_prediction_snapshot_id INTEGER, validation_status TEXT,
                validation_payload TEXT, validated_at TEXT
            );
            """
        )
        target = CUTOFF + timedelta(hours=12)
        as_of = target + timedelta(minutes=60)
        snapshots = [
            (1, target, CUTOFF, 12, timedelta(0)),  # Exactly mature, no previous validation.
            (2, target + MICROSECOND, CUTOFF, 12, timedelta(0)),  # Window still open.
            (3, target, as_of + MICROSECOND, 12, timedelta(0)),  # Not yet generated.
            (4, target, CUTOFF, 24, timedelta(0)),  # Prior validator version.
            (5, target, CUTOFF, 24, timedelta(0)),  # Current validation.
            (6, target, CUTOFF, 6, timedelta(0)),  # Outside the study horizons.
            (7, target, CUTOFF, 24, timedelta(0)),  # Current version, different tolerance.
            (8, target, target, 12, timedelta(0)),  # Generated at horizon.
            (9, target, CUTOFF, 24, timedelta(hours=1)),  # Incorrect target for its cutoff.
        ]
        session.db.executemany(
            """
            INSERT INTO analytics.ml_market_prediction_snapshot VALUES
                (:id, 1, 10, 'fixture', 'Yes', :horizon, :cutoff, :target, :generated,
                 40.0, 50.0, 10.0, '{}')
            """,
            [
                session._params({
                    "id": row_id,
                    "horizon": horizon,
                    "cutoff": row_target - timedelta(hours=horizon) + cutoff_offset,
                    "target": row_target,
                    "generated": generated,
                })
                for row_id, row_target, generated, horizon, cutoff_offset in snapshots
            ],
        )
        version = validator.VALIDATION_MODEL_VERSION
        session.db.executemany(
            """
            INSERT INTO analytics.ml_market_prediction_validation
                VALUES (?, 'validated', ?, ?)
            """,
            [
                (row_id, json.dumps({
                    "validation_model_version": model_version,
                    "target_tolerance_minutes": tolerance,
                }), as_of.isoformat())
                for row_id, model_version, tolerance in (
                    (4, "market_profile_prediction_validation_v1", "60"),
                    (5, version, "60"),
                    (7, version, "45"),
                )
            ],
        )
        result = validator._candidate_rows(
            session, platform_name="polymarket", as_of=as_of, limit=0,
            revalidate=False, tolerance_minutes=90,
        )
        self.assertEqual([row["ml_market_prediction_snapshot_id"] for row in result], [1, 4, 7])


class MissingLabelCheck(unittest.TestCase):
    def test_csv_loader_preserves_blank_and_filters_each_horizon_independently(self) -> None:
        columns = (
            "market_end_time", "condition_ref", baseline.TARGET_COLUMN,
            "future_price_delta_12h", "future_price_observed_12h", "movement_anchor_price_12h",
            "future_price_delta_24h", "future_price_observed_24h", "movement_anchor_price_24h",
        )
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "targets.csv"
            with path.open("w", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(columns)
                writer.writerow((CUTOFF.isoformat(), "twelve", 1, 0, 1, 0, "", 0, ""))
                writer.writerow((CUTOFF.isoformat(), "twenty-four", 0, "", 0, "", -0.2, 1, 0.5))
                writer.writerow((CUTOFF.isoformat(), "invalid", 0, "nan", 1, 0.5, 0.3, 0, 0.5))
            rows = baseline._load_training_rows(path)
            self.assertEqual(rows[0]["future_price_delta_12h"], 0.0)
            self.assertIsNone(rows[1]["future_price_delta_12h"])
            self.assertEqual([row[baseline.TARGET_COLUMN] for row in rows], [1, 0, 0])
            for task, expected_condition in (
                (baseline.TASK_MARKET_MOVEMENT_12H, "twelve"),
                (baseline.TASK_MARKET_MOVEMENT_24H, "twenty-four"),
            ):
                eligible = baseline._require_valid_movement_targets(dataset_path=path, rows=rows, task=task)
                self.assertEqual([row["condition_ref"] for row in eligible], [expected_condition])


if __name__ == "__main__":
    unittest.main()
