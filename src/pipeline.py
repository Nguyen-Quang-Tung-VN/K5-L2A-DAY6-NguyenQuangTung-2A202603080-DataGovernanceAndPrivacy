"""T02 PoC Pipeline — Raw QC Triage (Image Quality & Defect Detection).

Automated 5 steps run by `python -m src.main ...`:
    01 load      input + provenance check (manifest.csv) + images.csv
    02 process   multi-feature vision algorithm: blur (adaptive to cam_B),
                 local glare (patch saturation), dark (night-normalized),
                 and JPEG compression artifacts
    03 rank      prioritise top-B suspicious items for review (review_queue.csv + contact_sheet.html)
    04 review    human-in-the-loop: load review_queue_reviewed.csv, apply overrides, audit log
    05 decide    GO / HOLD / REWORK policy based on review findings and defect density
"""
from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd

from .common.contact_sheet import render_contact_sheet
from .common.context import RunContext
from .common.decision import Decision, write_decision
from .common.image_ops import brightness_stats, laplacian_variance, load_rgb, to_gray
from .common.manifest import verify_manifest
from .common.review import apply_overrides, load_review_decisions, make_review_queue, write_review_queue
from .metrics.tracks import get_track


# ---------------------------------------------------------------- 01 load
def load(ctx: RunContext) -> dict:
    if ctx.track != "t02":
        spec = get_track(ctx.track)
        raise NotImplementedError(f"Track {ctx.track} ({spec.title}) is not implemented in this PoC (only t02)")

    manifest = ctx.input_dir / "manifest.csv"
    problems = verify_manifest(manifest) if manifest.exists() else [{"problem": "no_manifest"}]
    if problems:
        ctx.audit.log(actor="pipeline", action="provenance_problems", item_id=str(manifest), after=problems[:20])
        if ctx.config.get("strict_provenance", True):
            raise ValueError(f"provenance check failed ({len(problems)} problems), first: {problems[:3]}")

    images_path = ctx.input_dir / "images.csv"
    if not images_path.exists():
        raise FileNotFoundError(f"Missing images.csv in {ctx.input_dir}")

    images = pd.read_csv(images_path)
    return {
        "manifest": pd.read_csv(manifest) if manifest.exists() else None,
        "images": images,
    }


# ---------------------------------------------------------------- 02 process
def _score_single_image(img_rgb: np.ndarray, camera_id: str, light: str) -> tuple[float, str, str, str]:
    """Analyze image across 4 defect modalities with domain-specific normalizations."""
    gray = to_gray(img_rgb)
    H, W = gray.shape
    sharp = laplacian_variance(img_rgb)
    b_stats = brightness_stats(img_rgb)

    # 1. Blur Detection (normalized by camera optical baseline)
    # cam_B has softer lens naturally (~350 variance) vs cam_A (~650)
    cam_base = 650.0 if camera_id == "cam_A" else 350.0
    norm_sharp = sharp / cam_base
    blur_score = float(np.clip(1.0 - (norm_sharp / 0.08), 0.0, 1.0))

    # 2. Dark / Underexposure Detection (adaptive to ambient light condition)
    # Night scenes naturally have lower brightness; avoid false alarm on clean night images
    if light == "night":
        dark_score = float(np.clip((0.85 - b_stats["mean"] / 35.0), 0.0, 1.0)) if b_stats["mean"] < 20.0 else 0.0
    else:
        dark_score = float(np.clip((b_stats["frac_dark"] - 0.50) / 0.35, 0.0, 1.0))

    # 3. Local Glare Detection (sliding patch saturation)
    # Global saturation misses localized hotspot glares (e.g., license plate or headlamp)
    patches = [gray[y:y+32, x:x+32] for y in range(0, max(1, H - 32), 16) for x in range(0, max(1, W - 32), 16)]
    patch_sat = max([(p > 240).mean() for p in patches]) if patches else b_stats["frac_saturated"]
    glare_score = float(np.clip((patch_sat - 0.15) / 0.20, 0.0, 1.0))

    # 4. Compression / JPEG Artifact Detection (8x8 boundary blockiness)
    diff_h = np.abs(gray[:, 1:] - gray[:, :-1])
    boundary_diff_h = float(diff_h[:, 7::8].mean()) if W > 8 else 0.0
    internal_diff_h = float((diff_h.sum() - diff_h[:, 7::8].sum()) / max(1, (diff_h.size - diff_h[:, 7::8].size)))
    blockiness = boundary_diff_h / (internal_diff_h + 1e-4)
    comp_score = float(np.clip((blockiness - 2.2) / 1.0, 0.0, 1.0))

    sub_scores = {
        "blur": blur_score,
        "dark": dark_score,
        "glare": glare_score,
        "compression": comp_score,
    }
    top_defect = max(sub_scores, key=sub_scores.get)
    max_score = sub_scores[top_defect]
    
    pred_defect_type = top_defect if max_score >= 0.20 else "none"
    suggested_action = "RECAPTURE" if max_score >= 0.50 else "KEEP"
    reason = f"{pred_defect_type}({max_score:.2f})" if pred_defect_type != "none" else "clean"

    return round(max_score, 6), pred_defect_type, suggested_action, reason


def process(ctx: RunContext, data: dict) -> pd.DataFrame:
    df_images = data["images"]
    rows = []

    for r in df_images.itertuples(index=False):
        img_path = ctx.input_dir / r.path
        if not img_path.exists():
            raise FileNotFoundError(f"Image not found: {img_path}")
        
        img = load_rgb(img_path)
        score, pred_defect, action, reason = _score_single_image(img, r.camera_id, r.light)

        rows.append({
            "image_id": r.image_id,
            "score": score,
            "pred_defect_type": pred_defect,
            "suggested_action": action,
            "reason": reason,
            "slice": f"light={r.light},cam={r.camera_id}",
            "evidence_path": r.path,
        })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 03 rank
def rank(ctx: RunContext, scored: pd.DataFrame) -> pd.DataFrame:
    budget = int(ctx.param("budget", 20))
    if "score" not in scored.columns:
        raise ValueError("rank(): process() output needs a numeric `score` column")

    q = make_review_queue(
        scored,
        id_col="image_id",
        score_col="score",
        budget=budget,
        reason_col="reason",
        action_col="suggested_action",
        slice_col="slice",
        evidence_col="evidence_path",
    )
    write_review_queue(q, ctx.out("review_queue.csv"))

    # Render offline contact sheet HTML for human verification
    render_contact_sheet(
        q,
        ctx.out("contact_sheet.html"),
        image_root=ctx.input_dir,
        title=f"T02 PoC Review Queue (Top {budget} Suspicious Items)",
    )
    return q


# ---------------------------------------------------------------- 04 review
def review(ctx: RunContext, scored: pd.DataFrame, queue: pd.DataFrame) -> pd.DataFrame:
    reviewed_path = ctx.output_dir / "review_queue_reviewed.csv"
    if reviewed_path.exists():
        reviewed = load_review_decisions(reviewed_path)
        ctx.stats["n_reviewed"] = len(reviewed)
        
        # Apply human reviewer overrides to suggested_action
        scored = apply_overrides(scored, reviewed, id_col="image_id", value_col="suggested_action", audit=ctx.audit)
        
        for r in reviewed.itertuples(index=False):
            ctx.audit.log(
                actor=r.reviewer,
                action=f"reviewer_action:{r.reviewer_decision}",
                item_id=r.item_id,
                reason=r.review_note or "",
                override_value=r.override_value,
            )
    return scored


# ---------------------------------------------------------------- 05 decide
def decide(ctx: RunContext, final: pd.DataFrame) -> Decision:
    budget = int(ctx.param("budget", 20))
    top_b = final.sort_values("score", ascending=False).head(budget)
    
    # Check severity in top-B: count how many items require RECAPTURE or are severe defects
    severe_count = (top_b["suggested_action"] == "RECAPTURE").sum()
    owner = ctx.config.get("owner", "QC Lead")

    if severe_count >= 8:
        return Decision(
            status="HOLD",
            reason_code="DEFECT_DENSITY_HIGH",
            reason=f"QC Gate: {severe_count}/{budget} sampled images exhibit severe defects; hold for batch review",
            owner=owner,
            scope=ctx.track,
            evidence=[str(ctx.out("ranked_review.csv")), str(ctx.out("review_queue.csv"))],
            metrics={"severe_in_top_b": int(severe_count), "budget": budget},
        )

    return Decision(
        status="GO",
        reason_code="BATCH_ACCEPTED",
        reason=f"QC Gate: defect count ({severe_count}/{budget}) within acceptable tolerance; batch approved",
        owner=owner,
        scope=ctx.track,
        evidence=[str(ctx.out("ranked_review.csv"))],
        metrics={"severe_in_top_b": int(severe_count), "budget": budget},
    )


def run(ctx: RunContext) -> None:
    spec = get_track(ctx.track)
    data = load(ctx)
    scored = process(ctx, data)
    ctx.stats["n_items"] = len(scored)
    queue = rank(ctx, scored)
    final = review(ctx, scored, queue)
    
    # Save required pred file with pred_columns first
    cols_to_save = spec.pred_columns + [c for c in final.columns if c not in spec.pred_columns]
    final[cols_to_save].to_csv(ctx.out(spec.pred_file), index=False)
    
    # Write decision
    write_decision(decide(ctx, final), ctx.out("decision.json"), ctx.out("decision_log.csv"))
