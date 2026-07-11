import json
import sys


def compute_iou(a_start, a_end, b_start, b_end):
    overlap = max(0, min(a_end, b_end) - max(a_start, b_start))
    union = max(a_end, b_end) - min(a_start, b_start)
    return overlap / union if union > 0 else 0.0


def match_clips(gt_clips, pipeline_clips, threshold=0.5):
    """For each GT clip, find best matching pipeline clip by IoU."""
    matches = []
    for gt in gt_clips:
        best_iou = 0.0
        best_pipeline = None
        best_pipeline_rank = None
        for i, pc in enumerate(pipeline_clips):
            iou = compute_iou(float(gt["start"]), float(gt["end"]), float(pc["start"]), float(pc["end"]))
            if iou > best_iou:
                best_iou = iou
                best_pipeline = pc
                best_pipeline_rank = i + 1
        matches.append({
            "gt_rank": gt["confidence_rank"],
            "gt_start": gt["start"],
            "gt_end": gt["end"],
            "pipeline_rank": best_pipeline_rank if best_iou >= threshold else None,
            "pipeline_start": best_pipeline["start"] if best_pipeline and best_iou >= threshold else None,
            "pipeline_end": best_pipeline["end"] if best_pipeline and best_iou >= threshold else None,
            "iou": round(best_iou, 3),
            "matched": best_iou >= threshold,
        })
    return matches


def compute_metrics(gt_clips, pipeline_clips):
    # Sort GT by confidence_rank ascending (1 = best)
    gt_sorted = sorted(gt_clips, key=lambda x: x["confidence_rank"])
    matches = match_clips(gt_sorted, pipeline_clips)

    # 1. Coverage: how many of GT top-3 are covered by any pipeline clip
    top3_gt = [m for m in matches if m["gt_rank"] <= 3]
    coverage_hits = sum(1 for m in top3_gt if m["matched"])
    coverage_score = coverage_hits / len(top3_gt) if top3_gt else 0.0

    # 2. Ranking: is GT #1 in pipeline top-3?
    gt1_match = next((m for m in matches if m["gt_rank"] == 1), None)
    ranking_hit = (
        gt1_match is not None
        and gt1_match["matched"]
        and gt1_match["pipeline_rank"] is not None
        and gt1_match["pipeline_rank"] <= 3
    )

    # 3. Boundary precision: avg IoU across all matched clips
    matched = [m for m in matches if m["matched"]]
    avg_iou = sum(m["iou"] for m in matched) / len(matched) if matched else 0.0

    return matches, {
        "coverage": f"{coverage_hits}/{len(top3_gt)} GT top-3 clips found  ({coverage_score:.0%})",
        "ranking": f"GT #1 in pipeline top-3: {'YES' if ranking_hit else 'NO'}"
                   + (f" (pipeline rank {gt1_match['pipeline_rank']})" if gt1_match and gt1_match["pipeline_rank"] else ""),
        "boundary_precision": f"Avg IoU across matched clips: {avg_iou:.3f}  ({len(matched)}/{len(matches)} clips matched)",
    }


def print_table(matches):
    header = f"{'GT Rank':<9} {'GT Range':<22} {'Pipeline Rank':<14} {'Pipeline Range':<22} {'IoU':<7} {'Status'}"
    print(header)
    print("-" * len(header))
    for m in sorted(matches, key=lambda x: x["gt_rank"]):
        gt_range = f"{m['gt_start']} - {m['gt_end']}"
        if m["matched"]:
            p_range = f"{m['pipeline_start']} - {m['pipeline_end']}"
            p_rank = str(m["pipeline_rank"])
            status = "MATCH"
        else:
            p_range = "—"
            p_rank = "—"
            status = "MISS"
        print(f"{m['gt_rank']:<9} {gt_range:<22} {p_rank:<14} {p_range:<22} {m['iou']:<7} {status}")


def main():
    if len(sys.argv) != 3:
        print("Usage: python eval.py ground_truth.json pipeline_clips.json")
        sys.exit(1)

    with open(sys.argv[1], encoding="utf-8") as f:
        gt_data = json.load(f)
    with open(sys.argv[2], encoding="utf-8") as f:
        pipeline_data = json.load(f)

    gt_clips = gt_data["clips"]
    pipeline_clips = pipeline_data["clips"]

    matches, metrics = compute_metrics(gt_clips, pipeline_clips)

    print(f"\n=== ClipForge Eval — {gt_data.get('video_id', 'unknown')} ===\n")
    print_table(matches)
    print("\n--- Metrics ---")
    for k, v in metrics.items():
        print(f"  {k}: {v}")
    print()


if __name__ == "__main__":
    main()