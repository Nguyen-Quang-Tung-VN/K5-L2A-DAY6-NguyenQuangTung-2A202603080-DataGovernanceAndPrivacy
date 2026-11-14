"""Unit tests for T02 Raw QC Triage PoC Pipeline.

Covers:
  - Contract check (image_id, score in [0, 1], descending rank order)
  - Edge cases (pure black, pure white, uniform image robustness)
  - Camera B softness normalization (failure mode 3 verification)
  - Local glare detection vs global saturation (failure mode 2 verification)
  - Human review overrides and audit logging
"""
from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from src.common.context import RunContext
from src.common.review import AuditLog, apply_overrides, load_review_decisions
from src.pipeline import _score_single_image, load, process, rank, review


@pytest.fixture
def run_ctx(tmp_path: Path) -> RunContext:
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    audit = AuditLog(out / "audit_log.jsonl")
    return RunContext(
        track="t02",
        input_dir=Path("fixtures/t02_raw_qc"),
        output_dir=out,
        config={
            "track": "t02",
            "owner": "Tester",
            "params": {"budget": 20},
            "strict_provenance": True,
        },
        seed=42,
        rng=np.random.default_rng(42),
        offline=True,
        audit=audit,
    )


def test_t02_contract_and_score_bounds(run_ctx: RunContext):
    """Verify that process() returns valid rows with scores in [0.0, 1.0]."""
    data = load(run_ctx)
    assert "images" in data
    assert len(data["images"]) == 96

    df_scored = process(run_ctx, data)
    assert "image_id" in df_scored.columns
    assert "score" in df_scored.columns
    assert "pred_defect_type" in df_scored.columns
    assert "suggested_action" in df_scored.columns
    assert len(df_scored) == 96

    scores = df_scored["score"].to_numpy()
    assert np.all(scores >= 0.0)
    assert np.all(scores <= 1.0)
    assert not np.any(np.isnan(scores))


def test_t02_rank_budget_and_monotonicity(run_ctx: RunContext):
    """Verify rank() extracts exactly budget items sorted descending."""
    data = load(run_ctx)
    df_scored = process(run_ctx, data)
    q = rank(run_ctx, df_scored)

    assert len(q) == 20
    assert list(q["rank"]) == list(range(1, 21))
    # Scores must be non-increasing
    scores = q["score"].tolist()
    assert all(scores[i] >= scores[i + 1] for i in range(len(scores) - 1))
    assert (run_ctx.output_dir / "review_queue.csv").exists()
    assert (run_ctx.output_dir / "contact_sheet.html").exists()


def test_t02_edge_cases_pure_black_and_white():
    """Verify pipeline resilience on extreme edge-case images without NaN or crashes."""
    # 1. Pure black image (180x320x3)
    black_img = np.zeros((180, 320, 3), dtype=np.uint8)
    score_b, defect_b, action_b, _ = _score_single_image(black_img, "cam_A", "day")
    assert not np.isnan(score_b)
    assert defect_b in {"dark", "blur"}  # Should be flagged as extreme defect
    assert action_b == "RECAPTURE"

    # 2. Pure white image
    white_img = np.full((180, 320, 3), 255, dtype=np.uint8)
    score_w, defect_w, action_w, _ = _score_single_image(white_img, "cam_A", "day")
    assert not np.isnan(score_w)
    assert defect_w in {"glare", "blur"}
    assert action_w == "RECAPTURE"

    # 3. Uniform flat gray image
    gray_img = np.full((180, 320, 3), 128, dtype=np.uint8)
    score_g, defect_g, action_g, _ = _score_single_image(gray_img, "cam_A", "day")
    assert not np.isnan(score_g)
    assert defect_g == "blur"  # Zero variance means pure blur


def test_t02_camera_b_softness_compensation():
    """Test that cam_B baseline softness does not trigger false blur alarms."""
    # Synthetic texture with moderate sharpness ~200 variance
    rng = np.random.default_rng(42)
    base = rng.integers(100, 150, (180, 320, 3), dtype=np.uint8)

    # For cam_B, natural baseline is lower so moderate sharpness should NOT trigger severe blur
    score_b, defect_b, _, _ = _score_single_image(base, "cam_B", "day")
    assert score_b < 0.80


def test_t02_local_glare_detection():
    """Verify local patch glare is detected even if the overall image is normal."""
    # Normal image with mean brightness ~120
    img = np.full((180, 320, 3), 120, dtype=np.uint8)
    # Inject a 32x32 hotspot (glare on headlights/license plate)
    img[40:72, 50:82, :] = 255

    score, defect, action, _ = _score_single_image(img, "cam_A", "day")
    assert defect == "glare"
    assert score >= 0.90


def test_t02_human_review_and_audit_log(run_ctx: RunContext):
    """Verify human review override and audit logging."""
    audit_file = run_ctx.output_dir / "audit_log.jsonl"
    audit = AuditLog(audit_file)

    pred = pd.DataFrame({
        "image_id": ["img_01", "img_02"],
        "score": [0.95, 0.88],
        "suggested_action": ["RECAPTURE", "RECAPTURE"],
    })

    reviewed = pd.DataFrame({
        "rank": [1, 2],
        "item_id": ["img_01", "img_02"],
        "score": [0.95, 0.88],
        "reason": ["glare", "dark"],
        "suggested_action": ["RECAPTURE", "RECAPTURE"],
        "slice": ["", ""],
        "evidence_path": ["", ""],
        "reviewer": ["Nguyen Quang Tung", "Nguyen Quang Tung"],
        "reviewer_decision": ["approve", "edit"],
        "override_value": ["", "KEEP"],
        "review_note": ["Confirmed defect", "Acceptable in night conditions"],
        "reviewed_at": ["2026-11-14T00:00:00Z", "2026-11-14T00:00:00Z"],
    })

    updated = apply_overrides(pred, reviewed, id_col="image_id", value_col="suggested_action", audit=audit)
    assert updated.loc[updated["image_id"] == "img_01", "suggested_action"].iloc[0] == "RECAPTURE"
    assert updated.loc[updated["image_id"] == "img_02", "suggested_action"].iloc[0] == "KEEP"

    logs = audit.read()
    assert len(logs) == 1
    assert logs[0]["item_id"] == "img_02"
    assert logs[0]["actor"] == "Nguyen Quang Tung"
    assert logs[0]["before"] == "RECAPTURE"
    assert logs[0]["after"] == "KEEP"
