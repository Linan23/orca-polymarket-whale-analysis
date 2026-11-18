"""Validate the repository's analytical data and leakage-control contract."""

from __future__ import annotations

import json
import math
import subprocess
import sys
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover - dependency guard
    raise SystemExit("PyYAML is required. Install the repository requirements first.") from exc


REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "configs"
EXPECTED_CATEGORIES = {"politics", "crypto", "finance", "technology", "geopolitics"}
EXPECTED_COMPONENTS = {"volume", "profitability", "consistency", "history"}
REQUIRED_MANIFEST_SECTIONS = {
    "schema_version",
    "dataset",
    "source_snapshot",
    "coverage",
    "resolution_label_quality",
    "category_quality",
    "privacy",
    "artifacts",
    "reproduction",
    "targets",
    "target_alignment",
    "feature_contract",
    "split_contract",
    "release_gates",
    "known_limitations",
}
PROHIBITED_TRACKED_PREFIXES = (
    "artifacts/",
    "data/",
    "data_platform/runtime/",
    "polymarket_data/",
    "releases/snapshots/",
)
PROHIBITED_TRACKED_SUFFIXES = (
    ".arrow",
    ".backup",
    ".bin",
    ".ckpt",
    ".db",
    ".dump",
    ".feather",
    ".gz",
    ".h5",
    ".joblib",
    ".jsonl",
    ".keras",
    ".lgb",
    ".model",
    ".ndjson",
    ".npy",
    ".npz",
    ".onnx",
    ".parquet",
    ".pgdump",
    ".pickle",
    ".pkl",
    ".pt",
    ".pth",
    ".sqlite",
    ".sqlite3",
    ".zip",
)
PROHIBITED_TABULAR_SUFFIXES = (".csv", ".tsv")
ALLOWED_TRACKED_SQL = {"data_platform/sql/deliverable_queries.sql"}
ALLOWED_TRACKED_JSON_PATTERNS = (
    "data_platform/config/*.json",
    "data_platform/ml/*_config.json",
    "experiments/registry.json",
    "my-app/package.json",
    "my-app/package-lock.json",
    "my-app/tsconfig*.json",
)
ALLOWED_AGGREGATE_TABLE_PATTERNS = ("reports/tables/*.csv", "reports/tables/*.tsv")


def _load_yaml(path: Path) -> dict[str, Any]:
    """Return one YAML document as a mapping."""
    with path.open(encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"{path.relative_to(REPO_ROOT)} must contain a YAML mapping")
    return payload


def _get(payload: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """Return a nested value without raising for a missing key."""
    value: Any = payload
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            return default
        value = value[key]
    return value


def _bounds_equal(value: Any, expected: tuple[float, float]) -> bool:
    """Return whether a two-value sequence matches numeric bounds."""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return False
    try:
        observed = (float(value[0]), float(value[1]))
    except (TypeError, ValueError):
        return False
    return all(math.isclose(item, target, abs_tol=1e-12) for item, target in zip(observed, expected, strict=True))


def _target_horizon(target: Any) -> int | None:
    """Return a target horizon from its mapping or scalar value."""
    if not isinstance(target, dict):
        return None
    value = target.get("horizon_hours")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _tracked_files() -> list[str]:
    """Return Git-tracked paths for repository data-policy enforcement."""
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    return sorted(path for path in result.stdout.decode("utf-8").split("\0") if path)


def _matches_any(path: str, patterns: tuple[str, ...]) -> bool:
    """Return whether a repository-relative path matches an allowlist pattern."""
    return any(fnmatch(path, pattern) for pattern in patterns)


def _tracked_policy_violations(paths: list[str]) -> list[dict[str, str]]:
    """Return prohibited tracked data, dump, runtime, and model artifacts."""
    violations: list[dict[str, str]] = []
    for path in paths:
        lower = path.lower()
        reason: str | None = None
        if lower.startswith(PROHIBITED_TRACKED_PREFIXES):
            reason = "prohibited generated/raw artifact directory"
        elif lower.endswith(".sql") and path not in ALLOWED_TRACKED_SQL:
            reason = "database dump or unapproved SQL artifact"
        elif lower.endswith(".json") and not _matches_any(path, ALLOWED_TRACKED_JSON_PATTERNS):
            reason = "JSON is allowed only in approved source/configuration paths"
        elif lower.endswith(PROHIBITED_TABULAR_SUFFIXES) and not _matches_any(
            path, ALLOWED_AGGREGATE_TABLE_PATTERNS
        ):
            reason = "raw/tabular dataset outside the aggregate report-table allowlist"
        elif lower.endswith(PROHIBITED_TRACKED_SUFFIXES):
            reason = "prohibited dataset, database, archive, or trained-model artifact"
        if reason:
            violations.append({"path": path, "reason": reason})
    return violations


def main() -> int:
    """Run contract checks and emit structured JSON evidence."""
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, **details: Any) -> None:
        checks.append({"name": name, "ok": bool(ok), "details": details})

    paths = {
        "manifest": CONFIG_DIR / "data-manifest.yaml",
        "categories": CONFIG_DIR / "categories.yaml",
        "splits": CONFIG_DIR / "splits.yaml",
        "whale_score": CONFIG_DIR / "whale-score.yaml",
    }
    configs: dict[str, dict[str, Any]] = {}
    for name, path in paths.items():
        try:
            configs[name] = _load_yaml(path)
            check(f"{name}_yaml_loads", True, path=str(path.relative_to(REPO_ROOT)))
        except (OSError, ValueError, yaml.YAMLError) as exc:
            check(f"{name}_yaml_loads", False, path=str(path.relative_to(REPO_ROOT)), error=str(exc))

    if len(configs) != len(paths):
        result = {"ok": False, "checks": checks}
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1

    manifest = configs["manifest"]
    categories = configs["categories"]
    splits = configs["splits"]
    whale_score = configs["whale_score"]

    try:
        tracked_paths = _tracked_files()
        tracked_violations = _tracked_policy_violations(tracked_paths)
        check(
            "git_tracked_artifact_policy",
            not tracked_violations,
            tracked_file_count=len(tracked_paths),
            violations=tracked_violations,
            allowlist={
                "sql": sorted(ALLOWED_TRACKED_SQL),
                "json_patterns": list(ALLOWED_TRACKED_JSON_PATTERNS),
                "aggregate_table_patterns": list(ALLOWED_AGGREGATE_TABLE_PATTERNS),
            },
        )
    except (OSError, subprocess.CalledProcessError, UnicodeDecodeError) as exc:
        check("git_tracked_artifact_policy", False, error=str(exc))

    included = set(_get(categories, "scope", "included_categories", default=[]) or [])
    normalized = set(_get(categories, "normalization", default={}) or {})
    excluded = set(_get(categories, "scope", "excluded_categories", default=[]) or [])
    check("five_research_categories", included == EXPECTED_CATEGORIES, observed=sorted(included))
    check("all_categories_have_normalization", normalized == EXPECTED_CATEGORIES, observed=sorted(normalized))
    check("category_scopes_do_not_overlap", not (included & excluded), overlap=sorted(included & excluded))
    check(
        "unknown_categories_require_review",
        _get(categories, "scope", "unknown_category_policy") == "review",
        policy=_get(categories, "scope", "unknown_category_policy"),
    )

    fractions = _get(splits, "partitions", default={}) or {}
    fraction_values = [fractions.get(name) for name in ("train_fraction", "validation_fraction", "test_fraction")]
    numeric_fractions = all(isinstance(value, (int, float)) and 0 < float(value) < 1 for value in fraction_values)
    fraction_sum = sum(float(value) for value in fraction_values) if numeric_fractions else None
    check(
        "grouped_chronological_split",
        splits.get("strategy") == "grouped_chronological"
        and bool(splits.get("group_key"))
        and bool(splits.get("time_key")),
        strategy=splits.get("strategy"),
        group_key=splits.get("group_key"),
        time_key=splits.get("time_key"),
    )
    check(
        "split_fractions_valid",
        numeric_fractions and math.isclose(float(fraction_sum), 1.0, abs_tol=1e-12),
        fractions=fractions,
        total=fraction_sum,
    )
    split_constraints = _get(splits, "constraints", default={}) or {}
    check(
        "final_test_locked",
        split_constraints.get("final_test_is_locked") is True
        and split_constraints.get("preprocessing_fit_on_training_only") is True
        and split_constraints.get("feature_selection_fit_on_training_only") is True,
        constraints=split_constraints,
    )
    check(
        "markets_do_not_cross_partitions",
        split_constraints.get("market_may_cross_partitions") is False,
        configured=split_constraints.get("market_may_cross_partitions"),
    )
    check(
        "rolling_evaluation_is_chronological",
        _get(splits, "rolling_evaluation", "enabled") is True
        and int(_get(splits, "rolling_evaluation", "minimum_folds", default=0) or 0) >= 5
        and _get(splits, "rolling_evaluation", "preserve_time_order") is True,
        rolling_evaluation=_get(splits, "rolling_evaluation", default={}),
    )

    components = _get(whale_score, "components", default={}) or {}
    component_names = set(components)
    weights = {
        name: component.get("weight") if isinstance(component, dict) else None
        for name, component in components.items()
    }
    numeric_weights = all(isinstance(value, (int, float)) and float(value) >= 0 for value in weights.values())
    weight_sum = sum(float(value) for value in weights.values()) if numeric_weights else None
    check("reliability_components_complete", component_names == EXPECTED_COMPONENTS, observed=sorted(component_names))
    check(
        "reliability_weights_sum_to_one",
        numeric_weights and math.isclose(float(weight_sum), 1.0, abs_tol=1e-12),
        weights=weights,
        total=weight_sum,
    )
    leakage = _get(whale_score, "leakage_controls", default={}) or {}
    check(
        "reliability_is_point_in_time",
        leakage.get("point_in_time_only") is True
        and leakage.get("exclude_current_market_outcome") is True
        and leakage.get("exclude_future_transactions") is True
        and leakage.get("cutoff_field") == splits.get("time_key")
        and split_constraints.get("reliability_features_use_prior_data_only") is True,
        leakage_controls=leakage,
    )
    check(
        "reliability_reports_uncertainty",
        _get(whale_score, "reporting", "include_uncertainty") is True
        and _get(whale_score, "reporting", "label_as_predictive_association") is True,
        reporting=_get(whale_score, "reporting", default={}),
    )

    missing_sections = sorted(REQUIRED_MANIFEST_SECTIONS - set(manifest))
    check("manifest_sections_present", not missing_sections, missing=missing_sections)
    dataset = _get(manifest, "dataset", default={}) or {}
    check(
        "manifest_dataset_identity_present",
        all(key in dataset for key in ("id", "version", "status", "description"))
        and bool(dataset.get("id"))
        and bool(dataset.get("status")),
        dataset=dataset,
    )
    source = _get(manifest, "source_snapshot", default={}) or {}
    licence = source.get("licence") if isinstance(source.get("licence"), dict) else {}
    check(
        "manifest_provenance_and_licence_present",
        all(key in source for key in ("source", "source_kind", "collection_method", "external_location", "committed_to_git", "provenance", "licence"))
        and source.get("committed_to_git") is False
        and all(key in licence for key in ("declared", "status", "required_action")),
        source_kind=source.get("source_kind"),
        committed_to_git=source.get("committed_to_git"),
        licence=licence,
    )
    coverage = _get(manifest, "coverage", default={}) or {}
    counts = coverage.get("counts") if isinstance(coverage.get("counts"), dict) else {}
    check(
        "manifest_coverage_present",
        all(key in coverage for key in ("profiled_at_utc", "transaction_time_utc", "counts", "resolved_time_utc"))
        and bool(counts),
        coverage_keys=sorted(coverage),
        count_keys=sorted(counts),
    )
    category_quality = _get(manifest, "category_quality", default={}) or {}
    manifest_categories = set(category_quality.get("in_scope_categories") or [])
    check(
        "manifest_category_quality_present",
        manifest_categories == EXPECTED_CATEGORIES
        and all(key in category_quality for key in ("status", "raw_event_counts", "unknown_policy", "required_action")),
        in_scope_categories=sorted(manifest_categories),
        status=category_quality.get("status"),
    )
    resolution_quality = _get(manifest, "resolution_label_quality", default={}) or {}
    resolver_methods = resolution_quality.get("resolver_methods")
    resolver_methods = resolver_methods if isinstance(resolver_methods, dict) else {}
    resolver_row_total = sum(
        int(method.get("rows") or 0)
        for method in resolver_methods.values()
        if isinstance(method, dict)
    )
    resolution_policy = resolution_quality.get("policy")
    resolution_policy = resolution_policy if isinstance(resolution_policy, dict) else {}
    winning_labels = int(counts.get("winning_outcome_labels_present") or 0)
    authoritative_labels = int(counts.get("authoritative_resolution_labels_verified") or 0)
    check(
        "resolution_label_quality_policy_present",
        resolution_quality.get("status") == "blocking_review_required"
        and resolver_row_total == winning_labels
        and 0 <= authoritative_labels <= winning_labels
        and resolution_policy.get("primary_final_outcome_labels") == "authoritative_resolution_source_only"
        and resolution_policy.get("heuristic_labels") == "sensitivity_analysis_only"
        and bool(resolution_policy.get("required_action")),
        status=resolution_quality.get("status"),
        resolver_row_total=resolver_row_total,
        winning_labels=winning_labels,
        authoritative_labels=authoritative_labels,
        policy=resolution_policy,
    )
    privacy = _get(manifest, "privacy", default={}) or {}
    no_identity_linking = privacy.get("real_world_identity_linking") in (False, "prohibited", "not_permitted")
    check(
        "privacy_and_raw_data_exclusions",
        privacy.get("wallet_data_is_public") is True
        and no_identity_linking
        and privacy.get("raw_wallet_rows_committed") is False
        and bool(privacy.get("aggregation_policy")),
        privacy=privacy,
    )
    artifacts = _get(manifest, "artifacts", default={}) or {}
    raw_artifact = artifacts.get("raw_snapshot") if isinstance(artifacts.get("raw_snapshot"), dict) else {}
    analytical_artifact = artifacts.get("analytical_dataset") if isinstance(artifacts.get("analytical_dataset"), dict) else {}
    artifact_fields = ("status", "path", "sha256", "tracked_in_git")
    check(
        "artifact_tracking_policy_present",
        all(key in raw_artifact for key in artifact_fields)
        and all(key in analytical_artifact for key in artifact_fields)
        and raw_artifact.get("tracked_in_git") is False
        and analytical_artifact.get("tracked_in_git") is False,
        raw_snapshot=raw_artifact,
        analytical_dataset=analytical_artifact,
    )
    reproduction = _get(manifest, "reproduction", default={}) or {}
    check(
        "reproduction_commands_present",
        bool(reproduction.get("profile_command")) and bool(reproduction.get("build_command")),
        reproduction=reproduction,
    )

    targets = _get(manifest, "targets", default={}) or {}
    movement_12h = targets.get("movement_12h")
    movement_24h = targets.get("movement_24h")
    final_outcome = targets.get("final_outcome")
    check(
        "probability_and_movement_bounds",
        _bounds_equal(targets.get("probability_bounds"), (0.0, 1.0))
        and _bounds_equal(targets.get("movement_bounds"), (-1.0, 1.0)),
        probability_bounds=targets.get("probability_bounds"),
        movement_bounds=targets.get("movement_bounds"),
    )
    check(
        "movement_horizons_are_12_and_24_hours",
        _target_horizon(movement_12h) == 12 and _target_horizon(movement_24h) == 24,
        movement_12h=movement_12h,
        movement_24h=movement_24h,
    )
    final_bounds = final_outcome.get("bounds") if isinstance(final_outcome, dict) else None
    check(
        "final_outcome_is_bounded",
        isinstance(final_outcome, dict)
        and final_outcome.get("type") == "binary_classification"
        and _bounds_equal(final_bounds, (0.0, 1.0)),
        final_outcome=final_outcome,
    )

    target_alignment = _get(manifest, "target_alignment", default={}) or {}
    source_hierarchy = target_alignment.get("probability_source_hierarchy") or []
    prohibited_sources = set(target_alignment.get("prohibited_sources") or [])
    feature_alignment = target_alignment.get("feature_price")
    feature_alignment = feature_alignment if isinstance(feature_alignment, dict) else {}
    future_alignment = target_alignment.get("future_targets")
    future_alignment = future_alignment if isinstance(future_alignment, dict) else {}
    tolerances = future_alignment.get("maximum_tolerance_minutes")
    tolerances = tolerances if isinstance(tolerances, dict) else {}
    missing_policy = target_alignment.get("missing_target_policy")
    missing_policy = missing_policy if isinstance(missing_policy, dict) else {}
    required_missing_accounting = {"horizon", "category", "attempted_source", "exclusion_reason"}
    check(
        "target_alignment_policy_frozen",
        target_alignment.get("status") == "frozen_v1"
        and source_hierarchy
        == ["exact_contract_transaction_price", "exact_contract_orderbook_midpoint"]
        and {
            "mutable_current_market_last_trade_price",
            "final_resolution_price",
            "opposite_contract_price_without_explicit_conversion",
        }
        <= prohibited_sources
        and feature_alignment.get("direction") == "backward_as_of"
        and "at_or_before" in str(feature_alignment.get("rule") or "")
        and future_alignment.get("direction") == "forward_only"
        and "at_or_after" in str(future_alignment.get("rule") or "")
        and tolerances.get("movement_12h") == 60
        and tolerances.get("movement_24h") == 60
        and bool(target_alignment.get("duplicate_policy")),
        target_alignment=target_alignment,
    )
    check(
        "missing_target_alignment_is_explicit",
        missing_policy.get("action") == "exclude_from_that_horizon_only"
        and required_missing_accounting <= set(missing_policy.get("required_accounting") or []),
        missing_target_policy=missing_policy,
    )

    feature_contract = _get(manifest, "feature_contract", default={}) or {}
    split_contract = _get(manifest, "split_contract", default={}) or {}
    required_exclusions = {
        "future_transactions",
        "future_orderbook_observations",
        "current_market_resolution",
        "post_cutoff_profitability",
        "raw_wallet_identifier",
        "target_horizon_prices",
    }
    observed_exclusions = set(feature_contract.get("excluded_from_features") or [])
    check(
        "manifest_point_in_time_contract",
        feature_contract.get("point_in_time_only") is True
        and feature_contract.get("cutoff_column") == splits.get("time_key")
        and required_exclusions <= observed_exclusions,
        feature_contract=feature_contract,
    )
    check(
        "manifest_split_contract_matches_config",
        split_contract.get("strategy") == splits.get("strategy")
        and split_contract.get("group_key") == splits.get("group_key")
        and split_contract.get("time_key") == splits.get("time_key")
        and split_contract.get("same_market_across_partitions") is False
        and split_contract.get("strict_partition_time_order") is True
        and split_contract.get("final_test_locked") is True,
        split_contract=split_contract,
    )

    required_gates = {
        "provenance_complete",
        "licence_review_recorded",
        "categories_normalized_and_reviewed",
        "analytical_dataset_hashed",
        "missingness_and_coverage_profiled",
        "point_in_time_leakage_checks_pass",
        "grouped_chronological_split_checks_pass",
        "resolution_label_quality_reviewed",
        "target_alignment_rule_frozen",
    }
    release_gates = set(manifest.get("release_gates") or [])
    check(
        "data_release_gates_declared",
        required_gates <= release_gates,
        missing=sorted(required_gates - release_gates),
    )
    known_limitations = manifest.get("known_limitations")
    check(
        "known_data_limitations_recorded",
        isinstance(known_limitations, list) and len(known_limitations) >= 3,
        limitation_count=len(known_limitations) if isinstance(known_limitations, list) else 0,
    )

    ok = all(item["ok"] for item in checks)
    print(json.dumps({"ok": ok, "checks": checks}, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
