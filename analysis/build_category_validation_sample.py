"""Build a deterministic, local-only blinded category-validation sample."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Iterable, Mapping, Sequence

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_platform.services.research_categories import (  # noqa: E402
    DEFAULT_CONFIG_PATH as CATEGORY_CONFIG_PATH,
    classify_research_category,
)


DEFAULT_CONFIG_PATH = REPO_ROOT / "configs" / "category-validation.yaml"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "data_platform" / "runtime" / "category-validation"
CLASSIFIER_PATH = REPO_ROOT / "data_platform" / "services" / "research_categories.py"
REQUIRED_TABLES = {"market_event", "market_tag", "market_tag_map"}
RESEARCH_CATEGORIES = ("politics", "crypto", "finance", "technology", "geopolitics")
VALID_STATUSES = {"classified", "review", "unmapped", "excluded"}
REVIEW_FIELDS = (
    "review_key",
    "title",
    "description",
    "description_truncated",
    "tags",
    "reviewed_label",
    "reviewer_confidence",
    "uncertainty_reason",
    "rationale",
)
REFERENCE_FIELDS = (
    "review_key",
    "decision_status",
    "predicted_category",
    "top_candidate_category",
    "excluded_candidate",
    "review_path",
    "score_margin_ratio",
    "sampling_stratum",
    "selected_in_stratum",
    "population_in_stratum",
    "inclusion_probability_exact",
    "inclusion_probability",
)


@dataclass(frozen=True)
class Candidate:
    """One event held in memory; its raw identifier is never exported."""

    event_id: str
    title: str
    description: str
    tags: tuple[str, ...]
    decision_status: str
    predicted_category: str
    top_candidate_category: str
    excluded_candidate: str
    review_path: str
    score_margin_ratio: float
    sampling_stratum: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create two blinded local review files and a separate classifier reference. "
            "Review text is never printed to stdout."
        )
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL", ""),
        help="PostgreSQL SQLAlchemy URL. Defaults to DATABASE_URL.",
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_ROOT / "latest"),
        help="Must resolve beneath data_platform/runtime/category-validation.",
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _string_list(value: Any, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ValueError(f"{field} must be a non-empty string list")
    result = tuple(item.strip() for item in value)
    if len(set(result)) != len(result):
        raise ValueError(f"{field} must not contain duplicates")
    return result


def load_validation_config(path_value: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """Load and validate the review protocol."""
    path = Path(path_value).resolve()
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("Category validation config must use schema_version 1")
    sample, privacy, review, gate = (
        payload.get("sample"),
        payload.get("privacy"),
        payload.get("review_export"),
        payload.get("gate"),
    )
    if not all(isinstance(section, dict) for section in (sample, privacy, review, gate)):
        raise ValueError("Config requires sample, privacy, review_export, and gate mappings")

    for field in (
        "seed",
        "classified_per_category",
        "review_total",
        "unmapped",
        "excluded_total",
        "physical_sports_excluded",
    ):
        if not isinstance(sample.get(field), int) or int(sample[field]) < 1:
            raise ValueError(f"sample.{field} must be a positive integer")
    if int(sample["physical_sports_excluded"]) > int(sample["excluded_total"]):
        raise ValueError("Physical-sports quota cannot exceed the total excluded quota")
    if sample.get("use_census_when_below_quota") is not True:
        raise ValueError("Sampling must use a census when a stratum is below quota")

    for field in ("minimum_salt_bytes", "pseudonym_hex_length"):
        if not isinstance(privacy.get(field), int) or int(privacy[field]) < 16:
            raise ValueError(f"privacy.{field} must be an integer of at least 16")
    if int(privacy["pseudonym_hex_length"]) > 64:
        raise ValueError("Pseudonym length cannot exceed a SHA-256 hex digest")
    if privacy.get("allowed_output_root") != "data_platform/runtime/category-validation":
        raise ValueError("Review output root must remain the ignored runtime path")
    for field in (
        "include_event_identifiers",
        "include_contract_identifiers",
        "include_slugs",
        "include_wallet_identifiers",
    ):
        if privacy.get(field) is not False:
            raise ValueError(f"privacy.{field} must remain false")
    if not isinstance(privacy.get("salt_environment_variable"), str):
        raise ValueError("A salt environment-variable name is required")

    for field in (
        "max_title_characters",
        "max_description_characters",
        "max_tags",
        "max_tag_characters",
    ):
        if not isinstance(review.get(field), int) or int(review[field]) < 1:
            raise ValueError(f"review_export.{field} must be a positive integer")
    reviewers = _string_list(review.get("reviewers"), field="review_export.reviewers")
    if len(reviewers) != 2:
        raise ValueError("Exactly two independent reviewers are required")
    labels = set(_string_list(review.get("allowed_labels"), field="review_export.allowed_labels"))
    if labels != {*RESEARCH_CATEGORIES, "out_of_scope", "insufficient_evidence"}:
        raise ValueError("Review labels must contain the five categories plus the two review states")
    confidences = set(
        _string_list(
            review.get("allowed_reviewer_confidence"),
            field="review_export.allowed_reviewer_confidence",
        )
    )
    if confidences != {"high", "medium", "low"}:
        raise ValueError("Reviewer confidence must be high, medium, or low")
    uncertainty_reasons = set(
        _string_list(
            review.get("allowed_uncertainty_reasons"),
            field="review_export.allowed_uncertainty_reasons",
        )
    )
    if uncertainty_reasons != {"none", "multiple_categories", "incomplete_evidence", "other"}:
        raise ValueError("Review uncertainty reasons do not match the frozen protocol")
    if gate.get("modelling_approved") is not False:
        raise ValueError("Sample generation cannot approve category-level modelling")
    frozen_gate = {
        "minimum_completed_reviews_per_reviewer": "all_sampled_events",
        "minimum_inter_reviewer_agreement": 0.90,
        "minimum_cohens_kappa": 0.80,
        "minimum_reference_positive_support": 50,
        "minimum_classifier_positive_support": 50,
        "minimum_per_category_precision": 0.85,
        "minimum_per_category_precision_95ci_lower": 0.70,
        "minimum_per_category_recall": 0.75,
        "minimum_per_category_recall_95ci_lower": 0.60,
        "minimum_out_of_scope_precision": 0.90,
        "minimum_out_of_scope_recall": 0.90,
        "minimum_macro_f1": 0.80,
        "maximum_false_in_scope_rate": 0.05,
        "bootstrap_replicates": 2000,
        "adjudication_agreement_audit_fraction": 0.10,
        "maximum_audited_agreement_change_rate": 0.05,
    }
    if any(gate.get(field) != value for field, value in frozen_gate.items()):
        raise ValueError("Category-quality gates must match the frozen validation guide")
    return payload


def validate_output_dir(path_value: str | Path) -> Path:
    """Enforce the ignored runtime boundary, including resolved symlinks."""
    output_dir = Path(path_value).expanduser().resolve()
    allowed_root = DEFAULT_OUTPUT_ROOT.resolve()
    try:
        output_dir.relative_to(allowed_root)
    except ValueError as exc:
        raise ValueError(f"Output directory must be beneath {allowed_root}") from exc
    if output_dir == allowed_root:
        raise ValueError("Choose a run directory beneath the category-validation root")
    return output_dir


def salt_from_environment(config: Mapping[str, Any]) -> bytes:
    """Read the run salt from the environment, never from CLI arguments."""
    privacy = config["privacy"]
    env_name = str(privacy["salt_environment_variable"])
    salt = os.getenv(env_name, "").encode("utf-8")
    minimum = int(privacy["minimum_salt_bytes"])
    if len(salt) < minimum:
        raise ValueError(f"{env_name} must contain at least {minimum} UTF-8 bytes")
    return salt


def source_snapshot_hash(rows: Iterable[Mapping[str, Any]]) -> str:
    """Fingerprint all source evidence without returning identifiers or text."""
    digest = hashlib.sha256()
    for row in sorted(rows, key=lambda item: str(item.get("event_id") or "")):
        payload = {
            "event_id": str(row.get("event_id") or ""),
            "category": str(row.get("category") or ""),
            "title": str(row.get("title") or ""),
            "description": str(row.get("description") or ""),
            "classification_tags": sorted(
                str(tag)
                for tag in (row.get("classification_tags") or row.get("tags") or ())
            ),
            "review_tags": sorted(
                str(tag) for tag in (row.get("review_tags") or row.get("tags") or ())
            ),
        }
        digest.update(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def _top_scored(values: Mapping[str, int], order: Sequence[str]) -> str:
    ranked = sorted(order, key=lambda name: (-int(values.get(name, 0)), order.index(name)))
    return ranked[0] if ranked and int(values.get(ranked[0], 0)) > 0 else "unassigned"


def _review_path(reasons: Sequence[str]) -> str:
    reason = " ".join(reasons).casefold()
    if "out-of-scope" in reason:
        return "exclusion_conflict"
    if "only weak" in reason:
        return "weak_only"
    if "separated by less" in reason:
        return "close_tie"
    if "below the classification minimum" in reason:
        return "below_threshold"
    return "other"


def _stratum(
    status: str,
    predicted: str,
    top_candidate: str,
    excluded_candidate: str,
    review_path: str,
) -> str:
    if status == "classified":
        return f"classified:{predicted}"
    if status == "review":
        return f"review:{review_path}:{top_candidate}"
    if status == "excluded":
        return f"excluded:{excluded_candidate}"
    return "unmapped"


def build_candidates(rows: Iterable[Mapping[str, Any]]) -> list[Candidate]:
    """Classify in-memory rows and retain raw IDs only in private candidate objects."""
    candidates: list[Candidate] = []
    for row in rows:
        event_id = str(row.get("event_id") or "").strip()
        if not event_id:
            raise RuntimeError("Every source event must have an identifier")
        result = classify_research_category(
            raw_category=row.get("category"),
            tags=tuple(row.get("classification_tags") or row.get("tags") or ()),
            title=row.get("title"),
            description=row.get("description"),
        )
        if result.status not in VALID_STATUSES:
            raise RuntimeError("Classifier returned an unsupported decision status")
        predicted = result.category or ""
        top_candidate = _top_scored(result.scores, RESEARCH_CATEGORIES)
        exclusion_order = tuple(sorted(result.exclusion_scores))
        excluded_candidate = _top_scored(result.exclusion_scores, exclusion_order)
        review_path = _review_path(result.reasons) if result.status == "review" else ""
        candidates.append(
            Candidate(
                event_id=event_id,
                title=str(row.get("title") or ""),
                description=str(row.get("description") or ""),
                tags=tuple(
                    sorted(
                        {
                            str(tag)
                            for tag in (row.get("review_tags") or row.get("tags") or ())
                            if str(tag)
                        }
                    )
                ),
                decision_status=result.status,
                predicted_category=predicted,
                top_candidate_category=top_candidate,
                excluded_candidate=excluded_candidate,
                review_path=review_path,
                score_margin_ratio=float(result.score_margin_ratio),
                sampling_stratum=_stratum(
                    result.status,
                    predicted,
                    top_candidate,
                    excluded_candidate,
                    review_path,
                ),
            )
        )
    return candidates


def _stable_key(candidate: Candidate, *, seed: int, context: str) -> str:
    return _sha256_bytes(f"{seed}|{context}|{candidate.event_id}".encode())


def _allocate_equal_total(
    grouped: Mapping[str, Sequence[Candidate]], total: int
) -> dict[str, int]:
    """Allocate a total equally, then redistribute unused quota deterministically."""
    keys = sorted(grouped)
    if not keys:
        return {}
    quotas = {key: total // len(keys) for key in keys}
    for key in keys[: total % len(keys)]:
        quotas[key] += 1
    remaining = total - sum(min(quotas[key], len(grouped[key])) for key in keys)
    while remaining > 0:
        progressed = False
        for key in keys:
            available = len(grouped[key])
            if quotas[key] < available:
                quotas[key] += 1
                remaining -= 1
                progressed = True
                if remaining == 0:
                    break
        if not progressed:
            break
    return quotas


def _stratum_quotas(
    grouped: Mapping[str, Sequence[Candidate]], config: Mapping[str, Any]
) -> dict[str, int]:
    sample = config["sample"]
    quotas: dict[str, int] = {}
    review = {key: rows for key, rows in grouped.items() if key.startswith("review:")}
    quotas.update(_allocate_equal_total(review, int(sample["review_total"])))
    excluded = {key: rows for key, rows in grouped.items() if key.startswith("excluded:")}
    sports_key = "excluded:physical_sports"
    sports_quota = min(
        int(sample["physical_sports_excluded"]), len(excluded.get(sports_key, ()))
    )
    if sports_key in excluded:
        quotas[sports_key] = sports_quota
    other_excluded = {key: rows for key, rows in excluded.items() if key != sports_key}
    other_total = max(0, int(sample["excluded_total"]) - sports_quota)
    quotas.update(_allocate_equal_total(other_excluded, other_total))
    remaining_excluded = int(sample["excluded_total"]) - sum(
        min(quotas.get(key, 0), len(rows)) for key, rows in excluded.items()
    )
    while remaining_excluded > 0:
        progressed = False
        for key in sorted(excluded):
            if quotas.get(key, 0) < len(excluded[key]):
                quotas[key] = quotas.get(key, 0) + 1
                remaining_excluded -= 1
                progressed = True
                if remaining_excluded == 0:
                    break
        if not progressed:
            break
    for key in grouped:
        if key.startswith("classified:"):
            quotas[key] = int(sample["classified_per_category"])
        elif key == "unmapped":
            quotas[key] = int(sample["unmapped"])
    return quotas


def select_candidates(
    candidates: Iterable[Candidate], config: Mapping[str, Any]
) -> tuple[list[Candidate], dict[str, dict[str, int | float | str]]]:
    """Select deterministic strata and report exact inclusion probabilities."""
    grouped: dict[str, list[Candidate]] = {}
    for candidate in candidates:
        grouped.setdefault(candidate.sampling_stratum, []).append(candidate)
    quotas = _stratum_quotas(grouped, config)
    seed = int(config["sample"]["seed"])
    selected: list[Candidate] = []
    counts: dict[str, dict[str, int | float | str]] = {}
    for stratum in sorted(grouped):
        ordered = sorted(
            grouped[stratum],
            key=lambda item: _stable_key(item, seed=seed, context=stratum),
        )
        quota = quotas.get(stratum, 0)
        chosen = ordered[:quota]
        selected.extend(chosen)
        counts[stratum] = {
            "population": len(ordered),
            "quota": quota,
            "selected": len(chosen),
            "inclusion_probability_exact": f"{len(chosen)}/{len(ordered)}",
            "inclusion_probability": round(len(chosen) / len(ordered), 8),
        }
    return selected, counts


def pseudonymize_event_id(
    event_id: str, *, salt: bytes, run_id: str, hex_length: int
) -> str:
    """Return a run-scoped keyed pseudonym for one private source identifier."""
    if len(salt) < 16:
        raise ValueError("Pseudonym salt must contain at least 16 bytes")
    if not 16 <= hex_length <= 64:
        raise ValueError("Pseudonym length must be between 16 and 64 hex characters")
    return hmac.new(
        salt, f"{run_id}|{event_id}".encode(), hashlib.sha256
    ).hexdigest()[:hex_length]


def _truncate(value: str, limit: int) -> tuple[str, bool]:
    return (value, False) if len(value) <= limit else (value[:limit], True)


def _spreadsheet_safe(value: str) -> str:
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value


def _csv_text(rows: Iterable[Mapping[str, Any]], fields: tuple[str, ...]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="raise", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def render_review_artifacts(
    selected: Iterable[Candidate],
    config: Mapping[str, Any],
    *,
    salt: bytes,
    run_id: str,
    strata: Mapping[str, Mapping[str, int | float | str]],
) -> tuple[dict[str, str], str]:
    """Render blinded reviewer files plus a non-blinded local reference."""
    chosen = list(selected)
    length = int(config["privacy"]["pseudonym_hex_length"])
    keyed = [
        (
            candidate,
            pseudonymize_event_id(
                candidate.event_id, salt=salt, run_id=run_id, hex_length=length
            ),
        )
        for candidate in chosen
    ]
    if len({key for _, key in keyed}) != len(keyed):
        raise RuntimeError("Pseudonym collision detected; increase pseudonym length")

    review = config["review_export"]
    seed = int(config["sample"]["seed"])
    files: dict[str, str] = {}
    prior_order: list[str] | None = None
    for reviewer in review["reviewers"]:
        ordered = sorted(
            keyed,
            key=lambda item: _stable_key(
                item[0], seed=seed, context=f"review-order:{reviewer}"
            ),
        )
        if prior_order == [key for _, key in ordered] and len(ordered) > 1:
            ordered.reverse()
        prior_order = [key for _, key in ordered]
        rows: list[dict[str, Any]] = []
        for candidate, key in ordered:
            title, _ = _truncate(candidate.title, int(review["max_title_characters"]))
            description, description_truncated = _truncate(
                candidate.description, int(review["max_description_characters"])
            )
            tags = [
                _spreadsheet_safe(tag[: int(review["max_tag_characters"])])
                for tag in candidate.tags[: int(review["max_tags"])]
            ]
            rows.append(
                {
                    "review_key": key,
                    "title": _spreadsheet_safe(title),
                    "description": _spreadsheet_safe(description),
                    "description_truncated": str(description_truncated).lower(),
                    "tags": json.dumps(tags, ensure_ascii=False, separators=(",", ":")),
                    "reviewed_label": "",
                    "reviewer_confidence": "",
                    "uncertainty_reason": "",
                    "rationale": "",
                }
            )
        files[f"{reviewer}.csv"] = _csv_text(rows, REVIEW_FIELDS)

    reference_rows = []
    for candidate, key in sorted(keyed, key=lambda item: item[1]):
        stratum = strata[candidate.sampling_stratum]
        probability = stratum["inclusion_probability"]
        reference_rows.append(
            {
                "review_key": key,
                "decision_status": candidate.decision_status,
                "predicted_category": candidate.predicted_category,
                "top_candidate_category": candidate.top_candidate_category,
                "excluded_candidate": candidate.excluded_candidate,
                "review_path": candidate.review_path,
                "score_margin_ratio": f"{candidate.score_margin_ratio:.4f}",
                "sampling_stratum": candidate.sampling_stratum,
                "selected_in_stratum": stratum["selected"],
                "population_in_stratum": stratum["population"],
                "inclusion_probability_exact": stratum["inclusion_probability_exact"],
                "inclusion_probability": f"{float(probability):.8f}",
            }
        )
    files["prediction_reference.csv"] = _csv_text(reference_rows, REFERENCE_FIELDS)
    membership_payload = "\n".join(
        f"{candidate.sampling_stratum}|{candidate.event_id}"
        for candidate in sorted(
            chosen, key=lambda item: (item.sampling_stratum, item.event_id)
        )
    ).encode()
    membership_hash = hmac.new(salt, membership_payload, hashlib.sha256).hexdigest()
    return files, membership_hash


def build_sample_from_rows(
    rows: Iterable[Mapping[str, Any]],
    config: Mapping[str, Any],
    *,
    salt: bytes,
    snapshot_hash: str | None = None,
    config_hash: str | None = None,
) -> tuple[dict[str, str], dict[str, Any]]:
    """Pure in-memory sampling entry point for CI and database-backed runs."""
    source_rows = list(rows)
    snapshot = snapshot_hash or source_snapshot_hash(source_rows)
    candidates = build_candidates(source_rows)
    selected, strata = select_candidates(candidates, config)
    config_fingerprint = config_hash or _sha256_bytes(
        yaml.safe_dump(dict(config), sort_keys=True).encode()
    )
    run_id = (
        f"category-validation-v1-{snapshot[:12]}-{config_fingerprint[:12]}-"
        f"{config['sample']['seed']}"
    )
    files, membership_hash = render_review_artifacts(
        selected, config, salt=salt, run_id=run_id, strata=strata
    )
    metadata = {
        "run_id": run_id,
        "source_snapshot_sha256": snapshot,
        "sampling_config_sha256": config_fingerprint,
        "sampling_membership_sha256": membership_hash,
        "sample_seed": int(config["sample"]["seed"]),
        "source_event_count": len(candidates),
        "selected_event_count": len(selected),
        "strata": strata,
    }
    return files, metadata


def _source_rows(database_url: str) -> list[Mapping[str, Any]]:
    if not database_url:
        raise ValueError("A database URL is required via --database-url or DATABASE_URL")
    engine = create_engine(database_url, future=True, pool_pre_ping=True)
    try:
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
            with connection.begin():
                connection.execute(text("SET TRANSACTION READ ONLY"))
                found = set(
                    connection.execute(
                        text(
                            "SELECT table_name FROM information_schema.tables "
                            "WHERE table_schema = 'analytics'"
                        )
                    ).scalars()
                )
                missing = sorted(REQUIRED_TABLES - found)
                if missing:
                    raise RuntimeError("Missing analytics tables: " + ", ".join(missing))
                return list(
                    connection.execute(
                        text(
                            """
                            SELECT event.event_id, event.category, event.title, event.description,
                              COALESCE(
                                ARRAY_AGG(DISTINCT tag.tag_label ORDER BY tag.tag_label)
                                  FILTER (WHERE tag.tag_label IS NOT NULL),
                                ARRAY[]::varchar[]
                              ) AS review_tags,
                              COALESCE(
                                ARRAY_AGG(DISTINCT tag_evidence.value ORDER BY tag_evidence.value)
                                  FILTER (WHERE tag_evidence.value IS NOT NULL),
                                ARRAY[]::varchar[]
                              ) AS classification_tags
                            FROM analytics.market_event AS event
                            LEFT JOIN analytics.market_tag_map AS tag_map
                              ON tag_map.event_id = event.event_id
                            LEFT JOIN analytics.market_tag AS tag
                              ON tag.tag_id = tag_map.tag_id
                            LEFT JOIN LATERAL (
                              VALUES (tag.tag_label), (tag.tag_slug)
                            ) AS tag_evidence(value) ON TRUE
                            GROUP BY event.event_id, event.category, event.title, event.description
                            ORDER BY event.event_id
                            """
                        )
                    ).mappings()
                )
    finally:
        engine.dispose()


def write_artifacts(
    output_dir: str | Path,
    files: Mapping[str, str],
    *,
    overwrite: bool = False,
) -> dict[str, str]:
    """Atomically write only this tool's named local artifacts."""
    directory = validate_output_dir(output_dir)
    if any(Path(name).name != name for name in files):
        raise ValueError("Artifact names must not contain path components")
    targets = {name: directory / name for name in files}
    if any(path.exists() for path in targets.values()) and not overwrite:
        raise FileExistsError("Review artifacts exist; pass --overwrite to replace this run")
    DEFAULT_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    DEFAULT_OUTPUT_ROOT.chmod(0o700)
    current = DEFAULT_OUTPUT_ROOT
    for part in directory.relative_to(DEFAULT_OUTPUT_ROOT).parts:
        current = current / part
        current.mkdir(exist_ok=True, mode=0o700)
        current.chmod(0o700)
    for name, content in files.items():
        target = targets[name]
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=directory
        )
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
                descriptor = -1
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            if overwrite:
                os.replace(temporary, target)
            else:
                os.link(temporary, target)
                temporary.unlink()
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if temporary.exists():
                temporary.unlink()
        target.chmod(0o600)
    return {name: _sha256_file(path) for name, path in targets.items()}


def refuse_completed_review_overwrite(
    output_dir: str | Path, reviewers: Iterable[str]
) -> None:
    """Fail closed rather than erase any reviewer work already in progress."""
    directory = validate_output_dir(output_dir)
    review_fields = (
        "reviewed_label",
        "reviewer_confidence",
        "uncertainty_reason",
        "rationale",
    )
    for reviewer in reviewers:
        path = directory / f"{reviewer}.csv"
        if not path.exists():
            continue
        try:
            with path.open(encoding="utf-8", newline="") as handle:
                rows = csv.DictReader(handle)
                if not rows.fieldnames or not set(review_fields).issubset(rows.fieldnames):
                    raise RuntimeError(
                        "Refusing to overwrite an unrecognized existing reviewer file"
                    )
                if any(
                    any(str(row.get(field) or "").strip() for field in review_fields)
                    for row in rows
                ):
                    raise RuntimeError(
                        "Refusing to overwrite reviewer files containing completed work"
                    )
        except (csv.Error, UnicodeError) as exc:
            raise RuntimeError(
                "Refusing to overwrite an unreadable existing reviewer file"
            ) from exc


def build_validation_sample(
    *,
    database_url: str,
    config_path: str | Path,
    output_dir: str | Path,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Run the database-backed workflow and return aggregate-only metadata."""
    config_path_resolved = Path(config_path).resolve()
    config = load_validation_config(config_path_resolved)
    if overwrite:
        refuse_completed_review_overwrite(
            output_dir, config["review_export"]["reviewers"]
        )
    salt = salt_from_environment(config)
    rows = _source_rows(database_url)
    config_hash = _sha256_file(config_path_resolved)
    files, metadata = build_sample_from_rows(
        rows, config, salt=salt, config_hash=config_hash
    )
    file_hashes = {name: _sha256_bytes(content.encode()) for name, content in files.items()}
    manifest = {
        "schema_version": 1,
        **metadata,
        "category_validation_config_sha256": config_hash,
        "category_rules_sha256": _sha256_file(CATEGORY_CONFIG_PATH),
        "classifier_sha256": _sha256_file(CLASSIFIER_PATH),
        "sampler_sha256": _sha256_file(Path(__file__).resolve()),
        "reviewers": list(config["review_export"]["reviewers"]),
        "allowed_labels": list(config["review_export"]["allowed_labels"]),
        "artifacts": {
            name: {"sha256": digest, "local_only": True}
            for name, digest in sorted(file_hashes.items())
        },
        "privacy": {
            "salt_persisted": False,
            "raw_event_identifiers_emitted": False,
            "contract_identifiers_emitted": False,
            "slugs_emitted": False,
            "wallet_identifiers_emitted": False,
            "review_text_local_only": True,
        },
        "interpretation": {
            "category_modelling_approved": False,
            "predictive_claim": False,
            "warning": "This is a blinded review sample, not category accuracy or model evidence.",
        },
    }
    manifest_text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    all_files = {**files, "manifest.json": manifest_text}
    written_hashes = write_artifacts(output_dir, all_files, overwrite=overwrite)
    manifest_hash = written_hashes["manifest.json"]
    return {
        **manifest,
        "manifest_sha256": manifest_hash,
        "output_directory": str(validate_output_dir(output_dir)),
    }


def main() -> int:
    args = parse_args()
    try:
        summary = build_validation_sample(
            database_url=args.database_url,
            config_path=args.config,
            output_dir=args.output_dir,
            overwrite=args.overwrite,
        )
    except SQLAlchemyError:
        print("category validation sample failed: database operation failed", file=sys.stderr)
        return 2
    except (FileNotFoundError, OSError, RuntimeError, ValueError, yaml.YAMLError) as exc:
        print(f"category validation sample failed: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "status": "PASS",
                "run_id": summary["run_id"],
                "source_event_count": summary["source_event_count"],
                "selected_event_count": summary["selected_event_count"],
                "strata": summary["strata"],
                "artifact_sha256": {
                    **{
                        name: value["sha256"]
                        for name, value in summary["artifacts"].items()
                    },
                    "manifest.json": summary["manifest_sha256"],
                },
                "output_directory": summary["output_directory"],
                "category_modelling_approved": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
