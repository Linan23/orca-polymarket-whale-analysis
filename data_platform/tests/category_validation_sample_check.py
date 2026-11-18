"""Independently verify the local-only category validation sample workflow."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import copy
import csv
from fractions import Fraction
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from typing import Any
from unittest.mock import patch

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from analysis import build_category_validation_sample as sample_builder  # noqa: E402


EXPECTED_LABELS = {
    "politics",
    "crypto",
    "finance",
    "technology",
    "geopolitics",
    "out_of_scope",
    "insufficient_evidence",
}


class _FakeRows:
    """Minimal SQLAlchemy result used to inspect the real source query."""

    def __init__(self, values: list[Any]) -> None:
        self.values = values

    def scalars(self) -> list[Any]:
        return self.values

    def mappings(self) -> list[Any]:
        return self.values


class _FakeConnection:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.source_sql = ""

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
            return _FakeRows(sorted(sample_builder.REQUIRED_TABLES))
        if "FROM analytics.market_event" in sql:
            self.source_sql = sql
            return _FakeRows(self.rows)
        return _FakeRows([])


class _FakeEngine:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.connection = _FakeConnection(rows)
        self.disposed = False

    def connect(self) -> _FakeConnection:
        return self.connection

    def dispose(self) -> None:
        self.disposed = True


def _row(event_id: str, title: str, **extra: Any) -> dict[str, Any]:
    """Return one synthetic event with sentinels for prohibited source fields."""
    return {
        "event_id": event_id,
        "category": extra.pop("category", ""),
        "title": title,
        "description": extra.pop("description", f"Public context for {title}"),
        "tags": extra.pop("tags", []),
        "slug": extra.pop("slug", f"RAW_SLUG_{event_id}"),
        "condition_id": extra.pop("condition_id", f"RAW_CONDITION_{event_id}"),
        "wallet_address": extra.pop("wallet_address", f"RAW_WALLET_{event_id}"),
        **extra,
    }


def _fixture_rows() -> list[dict[str, Any]]:
    """Cover all categories, abstentions, and multiple exclusion reasons."""
    rows: list[dict[str, Any]] = []
    classified_titles = {
        "politics": "Will the Senate pass legislation before the election?",
        "crypto": "Will Bitcoin activity increase on the blockchain?",
        "finance": "Will the Federal Reserve announce an interest rate cut?",
        "technology": "Will OpenAI release a new large language model?",
        "geopolitics": "Will NATO negotiate a ceasefire in the military conflict?",
    }
    for category, title in classified_titles.items():
        for index in range(3):
            rows.append(
                _row(
                    f"RAW_EVENT_CLASSIFIED_{category.upper()}_{index}",
                    title,
                    tags=[category],
                )
            )

    rows.extend(
        [
            _row("RAW_EVENT_REVIEW_POLITICS", "Will Trump make an announcement?"),
            _row("RAW_EVENT_REVIEW_TECH", "Will Nvidia make an announcement?"),
            _row("RAW_EVENT_REVIEW_GEO", "Will Ukraine make an announcement?"),
            _row(
                "RAW_EVENT_REVIEW_TIE",
                "Will Bitcoin react to a Federal Reserve announcement?",
            ),
            _row("RAW_EVENT_UNMAPPED_0", "Will the city open a new park?"),
            _row("RAW_EVENT_UNMAPPED_1", "Will a local museum change its hours?"),
            _row("RAW_EVENT_UNMAPPED_2", "Will the library acquire a manuscript?"),
            _row("RAW_EVENT_SPORTS_0", "Will the NBA team win the basketball game?"),
            _row("RAW_EVENT_SPORTS_1", "Will the NFL team win the football game?"),
            _row("RAW_EVENT_SPORTS_2", "Will the tennis player win the tennis match?"),
            _row("RAW_EVENT_ENTERTAINMENT_0", "Will the film win at the Academy Awards?"),
            _row("RAW_EVENT_ENTERTAINMENT_1", "Will the movie lead the box office?"),
            _row("RAW_EVENT_WEATHER_0", "Will the weather forecast predict rainfall?"),
            _row("RAW_EVENT_WEATHER_1", "Will the hurricane make landfall?"),
            _row(
                "RAW_EVENT_FORMULA",
                "=HYPERLINK(\"https://example.invalid\",\"OpenAI release\")",
                tags=["@formula-tag", "technology"],
            ),
        ]
    )
    return rows


def _test_config() -> dict[str, Any]:
    """Use small quotas while preserving the production protocol shape."""
    config = copy.deepcopy(sample_builder.load_validation_config())
    config["sample"].update(
        {
            "classified_per_category": 2,
            "review_total": 4,
            "unmapped": 2,
            "excluded_total": 3,
            "physical_sports_excluded": 2,
        }
    )
    return config


def _csv_rows(value: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(value)))


def main() -> int:
    """Run deterministic, privacy, stratification, and failure-path checks."""
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

    config = _test_config()
    reviewers = tuple(config["review_export"]["reviewers"])
    check(
        "protocol_config_is_blinded_and_blocking",
        len(reviewers) == 2
        and set(config["review_export"]["allowed_labels"]) == EXPECTED_LABELS
        and config["gate"]["modelling_approved"] is False
        and all(
            config["privacy"][field] is False
            for field in (
                "include_event_identifiers",
                "include_contract_identifiers",
                "include_slugs",
                "include_wallet_identifiers",
            )
        )
        and config["gate"]["minimum_inter_reviewer_agreement"] == 0.90
        and config["gate"]["minimum_cohens_kappa"] == 0.80
        and config["gate"]["minimum_reference_positive_support"] == 50
        and config["gate"]["minimum_classifier_positive_support"] == 50
        and config["gate"]["minimum_per_category_precision"] == 0.85
        and config["gate"]["minimum_per_category_recall"] == 0.75
        and config["gate"]["minimum_macro_f1"] == 0.80
        and config["gate"]["bootstrap_replicates"] >= 2000,
        reviewers=reviewers,
        allowed_labels=config["review_export"]["allowed_labels"],
    )

    rows = _fixture_rows()
    salt_a = b"category-validation-test-salt-a-2026"
    salt_b = b"category-validation-test-salt-b-2026"
    captured_out = io.StringIO()
    captured_err = io.StringIO()
    with redirect_stdout(captured_out), redirect_stderr(captured_err):
        files_a1, metadata_a1 = sample_builder.build_sample_from_rows(
            rows, config, salt=salt_a
        )
    files_a2, metadata_a2 = sample_builder.build_sample_from_rows(
        rows, config, salt=salt_a
    )
    files_reordered, metadata_reordered = sample_builder.build_sample_from_rows(
        list(reversed(rows)), config, salt=salt_a
    )
    files_b, metadata_b = sample_builder.build_sample_from_rows(
        rows, config, salt=salt_b
    )

    check(
        "fixed_seed_and_salt_are_deterministic",
        files_a1 == files_a2 == files_reordered
        and metadata_a1 == metadata_a2 == metadata_reordered,
        run_id=metadata_a1["run_id"],
        membership_hash=metadata_a1["sampling_membership_sha256"],
    )

    reference_a = _csv_rows(files_a1["prediction_reference.csv"])
    reference_b = _csv_rows(files_b["prediction_reference.csv"])
    keys_a = {row["review_key"] for row in reference_a}
    keys_b = {row["review_key"] for row in reference_b}
    check(
        "pseudonyms_are_stable_but_salt_scoped",
        keys_a
        and keys_a == {
            row["review_key"] for row in _csv_rows(files_a2["prediction_reference.csv"])
        }
        and keys_a.isdisjoint(keys_b)
        and metadata_a1["sampling_membership_sha256"]
        != metadata_b["sampling_membership_sha256"],
        selected_count=len(keys_a),
        pseudonym_length=sorted({len(value) for value in keys_a}),
    )

    strata = metadata_a1["strata"]
    classified_ok = all(
        strata.get(f"classified:{category}", {}).get("selected") == 2
        for category in sample_builder.RESEARCH_CATEGORIES
    )
    review_selected = sum(
        int(values["selected"])
        for name, values in strata.items()
        if name.startswith("review:")
    )
    excluded_selected = sum(
        int(values["selected"])
        for name, values in strata.items()
        if name.startswith("excluded:")
    )
    check(
        "stratified_quotas_and_minority_censuses",
        classified_ok
        and review_selected == 4
        and strata["unmapped"]["selected"] == 2
        and strata["excluded:physical_sports"]["selected"] == 2
        and excluded_selected == 3,
        classified={
            category: strata.get(f"classified:{category}", {}).get("selected")
            for category in sample_builder.RESEARCH_CATEGORIES
        },
        review_selected=review_selected,
        excluded_selected=excluded_selected,
    )

    selected_from_strata = sum(int(values["selected"]) for values in strata.values())
    probabilities_valid = all(
        int(values["selected"]) <= int(values["population"])
        and abs(
            float(values["inclusion_probability"])
            - int(values["selected"]) / int(values["population"])
        )
        < 1e-8
        for values in strata.values()
    )
    check(
        "aggregate_counts_and_inclusion_probabilities_reconcile",
        metadata_a1["source_event_count"] == len(rows)
        and metadata_a1["selected_event_count"] == selected_from_strata
        and len(reference_a) == selected_from_strata
        and probabilities_valid,
        source_count=metadata_a1["source_event_count"],
        selected_count=metadata_a1["selected_event_count"],
        stratum_selected_total=selected_from_strata,
    )

    repeating_config = copy.deepcopy(config)
    repeating_config["sample"]["classified_per_category"] = 1
    repeating_rows = [
        _row(
            f"RAW_EVENT_REPEATING_{index}",
            "Will the Senate pass legislation before the election?",
        )
        for index in range(11)
    ]
    repeating_files, repeating_metadata = sample_builder.build_sample_from_rows(
        repeating_rows, repeating_config, salt=salt_a
    )
    repeating_reference = _csv_rows(repeating_files["prediction_reference.csv"])
    repeating_row = repeating_reference[0]
    exact_probability = Fraction(repeating_row["inclusion_probability_exact"])
    represented_from_counts = Fraction(
        int(repeating_row["selected_in_stratum"]),
        int(repeating_row["population_in_stratum"]),
    )
    rounded_probability = Fraction(repeating_row["inclusion_probability"])
    repeating_stratum = repeating_metadata["strata"]["classified:politics"]
    check(
        "reference_preserves_exact_inclusion_probability",
        len(repeating_reference) == 1
        and exact_probability == represented_from_counts == Fraction(1, 11)
        and repeating_stratum["inclusion_probability_exact"] == "1/11"
        and rounded_probability != exact_probability,
        exact=str(exact_probability),
        decimal=repeating_row["inclusion_probability"],
        selected=repeating_row["selected_in_stratum"],
        population=repeating_row["population_in_stratum"],
    )

    reviewer_rows: dict[str, list[dict[str, str]]] = {}
    reviewer_header_ok = True
    reviewer_keys_ok = True
    reviewer_blind_ok = True
    for reviewer in reviewers:
        file_name = f"{reviewer}.csv"
        parsed = _csv_rows(files_a1[file_name])
        reviewer_rows[reviewer] = parsed
        fields = set(parsed[0]) if parsed else set()
        reviewer_header_ok = reviewer_header_ok and fields == set(sample_builder.REVIEW_FIELDS)
        reviewer_keys_ok = reviewer_keys_ok and {row["review_key"] for row in parsed} == keys_a
        reviewer_blind_ok = reviewer_blind_ok and not fields.intersection(
            {
                "decision_status",
                "predicted_category",
                "top_candidate_category",
                "excluded_candidate",
                "score_margin_ratio",
                "sampling_stratum",
                "inclusion_probability",
            }
        )
        reviewer_blind_ok = reviewer_blind_ok and all(
            not row["reviewed_label"]
            and not row["reviewer_confidence"]
            and not row["uncertainty_reason"]
            and not row["rationale"]
            for row in parsed
        )
    reviewer_orders = [
        tuple(row["review_key"] for row in reviewer_rows[reviewer])
        for reviewer in reviewers
    ]
    check(
        "reviewer_exports_are_separate_complete_and_blinded",
        reviewer_header_ok
        and reviewer_keys_ok
        and reviewer_blind_ok
        and reviewer_orders[0] != reviewer_orders[1],
        reviewer_files=[f"{reviewer}.csv" for reviewer in reviewers],
        rows_per_reviewer={name: len(value) for name, value in reviewer_rows.items()},
        orders_differ=reviewer_orders[0] != reviewer_orders[1],
    )

    slug_only_source = {
        "event_id": "RAW_EVENT_SLUG_ONLY",
        "category": "",
        "title": "Will the market move?",
        "description": "Public evidence with no category keyword.",
        "review_tags": ["Digital assets"],
        "classification_tags": ["Digital assets", "bitcoin"],
    }
    fake_engine = _FakeEngine([slug_only_source])
    original_create_engine = sample_builder.create_engine
    sample_builder.create_engine = lambda *_args, **_kwargs: fake_engine
    try:
        queried_rows = sample_builder._source_rows("synthetic://tag-evidence")
    finally:
        sample_builder.create_engine = original_create_engine
    slug_candidates = sample_builder.build_candidates(queried_rows)
    slug_files, _ = sample_builder.build_sample_from_rows(
        queried_rows, config, salt=salt_a
    )
    slug_reviewer_text = "\n".join(
        slug_files[f"{reviewer}.csv"] for reviewer in reviewers
    )
    check(
        "tag_slugs_classify_but_never_enter_reviewer_exports",
        "tag.tag_slug" in fake_engine.connection.source_sql
        and "classification_tags" in fake_engine.connection.source_sql
        and "review_tags" in fake_engine.connection.source_sql
        and fake_engine.disposed
        and len(slug_candidates) == 1
        and slug_candidates[0].decision_status == "classified"
        and slug_candidates[0].predicted_category == "crypto"
        and "Digital assets" in slug_reviewer_text
        and "bitcoin" not in slug_reviewer_text.casefold(),
        query_includes_tag_slug="tag.tag_slug" in fake_engine.connection.source_sql,
        observed_status=slug_candidates[0].decision_status,
        observed_category=slug_candidates[0].predicted_category,
        slug_leaked="bitcoin" in slug_reviewer_text.casefold(),
    )

    combined_output = "\n".join(files_a1.values()) + json.dumps(metadata_a1, sort_keys=True)
    forbidden_values = {
        str(row[field])
        for row in rows
        for field in ("event_id", "slug", "condition_id", "wallet_address")
    }
    leaked_values = sorted(value for value in forbidden_values if value in combined_output)
    log_text = captured_out.getvalue() + captured_err.getvalue()
    logged_sensitive_values = sorted(
        value
        for row in rows
        for value in (str(row["event_id"]), str(row["title"]), str(row["description"]))
        if value in log_text
    )
    check(
        "exports_and_logs_omit_raw_identifiers_and_source_rows",
        not leaked_values and not logged_sensitive_values and not log_text,
        leaked_values=leaked_values,
        logged_sensitive_values=logged_sensitive_values,
        captured_log_characters=len(log_text),
    )

    formula_files, _ = sample_builder.build_sample_from_rows(
        [
            _row(
                "RAW_EVENT_FORMULA_ONLY",
                "=HYPERLINK(\"https://example.invalid\",\"OpenAI release\")",
                tags=["@formula-tag", "technology"],
            )
        ],
        config,
        salt=salt_a,
    )
    all_review_rows = [
        row
        for reviewer in reviewers
        for row in _csv_rows(formula_files[f"{reviewer}.csv"])
    ]
    formula_titles = [row["title"] for row in all_review_rows if "HYPERLINK" in row["title"]]
    formula_tags = [row["tags"] for row in all_review_rows if "formula-tag" in row["tags"]]
    check(
        "spreadsheet_formulas_are_neutralized",
        formula_titles
        and all(value.startswith("'") for value in formula_titles)
        and formula_tags
        and all("'@formula-tag" in value for value in formula_tags),
        formula_title_count=len(formula_titles),
        formula_tag_count=len(formula_tags),
    )

    rejected_outside = False
    try:
        sample_builder.validate_output_dir(REPO_ROOT / "reports" / "category-review")
    except ValueError:
        rejected_outside = True
    allowed_path = sample_builder.validate_output_dir(
        REPO_ROOT / "data_platform" / "runtime" / "category-validation" / "fixture-run"
    )
    path_component_rejected = False
    try:
        sample_builder.write_artifacts(
            allowed_path,
            {"../escape.csv": "must not be written"},
        )
    except ValueError:
        path_component_rejected = True
    check(
        "output_directory_is_confined_to_ignored_runtime_root",
        rejected_outside
        and path_component_rejected
        and allowed_path.is_relative_to(sample_builder.DEFAULT_OUTPUT_ROOT.resolve()),
        rejected_outside=rejected_outside,
        path_component_rejected=path_component_rejected,
        allowed_path=str(allowed_path.relative_to(REPO_ROOT)),
    )

    sample_builder.DEFAULT_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(
        prefix="fixture-parent-", dir=sample_builder.DEFAULT_OUTPUT_ROOT
    ) as parent:
        permission_dir = Path(parent) / "fixture-run"
        creation_modes: list[int] = []
        original_fchmod = os.fchmod

        def observe_creation_mode(descriptor: int, mode: int) -> None:
            creation_modes.append(stat.S_IMODE(os.fstat(descriptor).st_mode))
            original_fchmod(descriptor, mode)

        previous_umask = os.umask(0)
        try:
            with patch.object(sample_builder.os, "fchmod", observe_creation_mode):
                sample_builder.write_artifacts(
                    permission_dir,
                    {"reviewer_a.csv": "review_key,title\nabc,public title\n"},
                )
        finally:
            os.umask(previous_umask)
        directory_mode = stat.S_IMODE(permission_dir.stat().st_mode)
        file_mode = stat.S_IMODE((permission_dir / "reviewer_a.csv").stat().st_mode)
        temporary_files = list(permission_dir.glob(".*.tmp"))
    check(
        "local_review_artifacts_are_owner_only",
        creation_modes
        and all(mode == 0o600 for mode in creation_modes)
        and directory_mode == 0o700
        and file_mode == 0o600
        and not temporary_files,
        creation_modes=[oct(mode) for mode in creation_modes],
        directory_mode=oct(directory_mode),
        file_mode=oct(file_mode),
        temporary_file_count=len(temporary_files),
    )

    salt_variable = config["privacy"]["salt_environment_variable"]
    with patch.dict(os.environ, {}, clear=True):
        missing_salt_rejected = False
        missing_salt_error = ""
        try:
            sample_builder.salt_from_environment(config)
        except ValueError as exc:
            missing_salt_rejected = True
            missing_salt_error = str(exc)
    check(
        "missing_secret_salt_fails_closed",
        missing_salt_rejected and salt_variable in missing_salt_error,
        error=missing_salt_error,
    )

    invalid_config = copy.deepcopy(config)
    invalid_config["privacy"]["include_event_identifiers"] = True
    invalid_rejected = False
    invalid_error = ""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", encoding="utf-8") as handle:
        yaml.safe_dump(invalid_config, handle)
        handle.flush()
        try:
            sample_builder.load_validation_config(handle.name)
        except ValueError as exc:
            invalid_rejected = True
            invalid_error = str(exc)
    check(
        "invalid_privacy_config_fails_closed",
        invalid_rejected and "include_event_identifiers" in invalid_error,
        error=invalid_error,
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
