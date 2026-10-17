#!/usr/bin/env python3
"""Rebuild every DROID website preview with a portable reprojection release.

--inputs is a JSON mapping from each DROID dataset ID to {root, kind}. It must
name the actual inputs, including existing reviewed calibration derivatives.
Episode selection comes from the website; no episode or calibration is guessed.
Outputs are prepared and validated under --out before --install changes the site.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import copy
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from zoneinfo import ZoneInfo

SITE = Path(__file__).resolve().parents[1]
PROJECTS = {"robotiq/droid", "robotiq/droid_lowres"}


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(path.suffix + ".pending")
    if path.name == "datasets.json":
        pending.write_text(json.dumps(data, separators=(",", ":"), ensure_ascii=False))
    else:
        pending.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    pending.replace(path)


def ff(*args):
    subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                    *map(str, args)], check=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--release", type=Path, required=True)
    ap.add_argument("--inputs", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--install", action="store_true")
    args = ap.parse_args()
    release, out = args.release.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    catalog_path = SITE / "data/datasets.json"
    original_bytes = catalog_path.read_bytes()
    catalog = json.loads(original_bytes)
    clips = [c for p in catalog["projects"] if p["key"] in PROJECTS for c in p["overlays"]]
    inputs = json.loads(args.inputs.read_text())
    if not clips or set(inputs) != {c["dataset"] for c in clips}:
        raise ValueError("Input map must cover exactly the website's DROID datasets")
    sys.path.insert(0, str(release))
    import reproject as renderer
    import raw_clips as raw
    recipes = renderer.check_release()
    version = renderer.lib_version()
    stage = out / "site"
    for sub in ("videos", "posters", "raw"):
        (stage / "overlays" / sub).mkdir(parents=True, exist_ok=True)
    raw.VIDEOS = str(stage / "overlays/videos")
    raw.RAW = str(stage / "overlays/raw")
    raw.dataset_root = lambda _root, dataset: inputs[dataset]["root"]
    built = datetime.datetime.now(ZoneInfo("America/Los_Angeles")).isoformat(timespec="seconds")

    def build(clip):
        dataset, ep = clip["dataset"], int(clip["episode"])
        project, name = dataset.rsplit("/", 1)
        root = Path(inputs[dataset]["root"]).resolve()
        info = renderer.load_info(root)
        row = renderer.episode_row(root, ep)
        source_paths = [root / "meta/info.json"]
        source_paths += sorted((root / "meta/episodes").rglob("*.parquet"))
        source_paths += sorted((root / "meta").glob("*.parquet"))
        source_paths.append(root / info["data_path"].format(
            chunk_index=row["data/chunk_index"], file_index=row["data/file_index"]))
        for view in clip["views"]:
            key = "observation.image." + view
            source_paths.append(root / info["video_path"].format(video_key=key,
                chunk_index=row[f"videos/{key}/chunk_index"], file_index=row[f"videos/{key}/file_index"]))
        source_hashes = {str(p.relative_to(root)): sha(p) for p in source_paths}
        print(f"Rendering {dataset} episode {ep}", flush=True)
        opts = argparse.Namespace(out=out / "renders", episode=ep, frames=None, seconds=45,
            fps=10, frame=0, png=False, look="white", dry_run=False, python=sys.executable)
        meta = renderer.run_one(dict(root=str(root), project=project, dataset=name,
            project_inferred_from="website catalog", lib_version=version), recipes, opts)
        if meta["status"] != "ok":
            raise RuntimeError(f"{dataset}: {meta.get('error', meta['status'])}")
        if meta["views"] != clip["views"]:
            raise ValueError(f"{dataset}: renderer changed the website's camera order")
        render_dir = out / "renders" / dataset / f"ep{ep}"
        stem = f"{clip['key']}__{clip['slug']}"
        video = stage / "overlays/videos" / (stem + ".mp4")
        poster = stage / "overlays/posters" / (stem + ".jpg")
        ff("-i", render_dir / "stitched.mp4", "-vf", "scale=-2:360", "-c:v", "libx264",
           "-preset", "slow", "-crf", "28", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", video)
        width, height, rate, frames = raw.probe(str(video))
        _, _, source_rate, source_frames = raw.probe(str(render_dir / "stitched.mp4"))
        if rate != source_rate or frames != source_frames:
            raise ValueError(f"{dataset}: site encode changed frame sampling")
        seconds = frames / float(rate)
        ff("-ss", f"{seconds / 2:.6f}", "-i", video, "-frames:v", "1",
           "-vf", "scale=-2:180", "-q:v", "6", poster)
        message = raw.raw_one(clip, force=True)
        print(message, flush=True)
        if "failed" in message or "rejected" in message or "skipped" in message:
            raise RuntimeError(message)
        companion = stage / "overlays/raw" / (stem + ".mp4")
        if raw.probe(str(companion)) != (width, height, rate, frames):
            raise ValueError(f"{dataset}: raw and overlay encodes differ in shape or sampling")
        for path in (video, companion):
            ff("-i", path, "-f", "null", "-")
        if source_hashes != {str(p.relative_to(root)): sha(p) for p in source_paths}:
            raise RuntimeError(f"{dataset}: source changed during rendering")
        fitted = any("Applied sample override [droid-wrist" in n for n in meta.get("notes", []))
        note = "Rebuilt with corrected Robotiq jaw geometry. "
        if fitted:
            note += ("Wrist placement is fitted to both stereo views of this recording. "
                     "Camera calibration and remaining CAD alignment errors are unvalidated.")
        else:
            note += "Existing camera calibration retained; residual wrist alignment is unvalidated."
        if clip.get("alignment_audit"):
            note += " The previously reviewed calibration repair is retained."
        files = {str(p.relative_to(stage)): sha(p) for p in (video, poster, companion,
            stage / "overlays/raw" / (stem + ".jpg"))}
        record = {"dataset": dataset, "episode": ep, "views": clip["views"],
            "frames": frames, "fps": float(rate), "width": width, "height": height,
            "source_kind": inputs[dataset]["kind"], "source_sha256": source_hashes,
            "lib_version": version, "config": meta["recipe"].get("config"),
            "wrist_translation_candidate": fitted, "review_note": note, "files": files}
        fingerprint = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
        updated = dict(clip, seconds=round(seconds, 3), bytes=video.stat().st_size,
            render_built=built, render_fingerprint=fingerprint, review_note=note,
            overlay_label="Gripper CAD · alignment unvalidated")
        record["render_fingerprint"] = fingerprint
        # These receipts are local build caches, ignored by the website checkout.
        write_json(video.with_suffix(".json"), record)
        return updated, record

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        results = list(pool.map(build, clips))
    updated = {(c["dataset"], c["episode"]): c for c, _ in results}
    refreshed = copy.deepcopy(catalog)
    for project in refreshed["projects"]:
        for i, clip in enumerate(project["overlays"]):
            project["overlays"][i] = updated.get((clip["dataset"], clip["episode"]), clip)
    refreshed["previews_updated"] = built
    report = {"reviewed_at": built, "scope": "All existing DROID website previews; original episode selections retained",
        "clip_count": len(results), "data_modified": False, "release_manifest_sha256": sha(release / "ASSETS.md"),
        "validation": "All overlay/raw pairs fully decoded; matching dimensions, frame counts, rates and camera order",
        "clips": [record for _, record in results]}
    write_json(stage / "data/datasets.json", refreshed)
    write_json(stage / "data/droid-preview-review.json", report)
    if args.install:
        if catalog_path.read_bytes() != original_bytes:
            raise RuntimeError("Website catalog changed during rebuild; staged outputs retained for review")
        backup = out / "before"
        if backup.exists():
            raise FileExistsError("Backup already exists; use a fresh --out for another install")
        backup.mkdir()
        paths = [p for p in stage.rglob("*") if p.is_file()]
        for src in paths:
            relative = src.relative_to(stage)
            dest, saved = SITE / relative, backup / relative
            if dest.exists():
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dest, saved)
        for src in paths:
            dest = SITE / src.relative_to(stage)
            dest.parent.mkdir(parents=True, exist_ok=True)
            pending = dest.with_suffix(dest.suffix + ".pending")
            shutil.copy2(src, pending)
            os.replace(pending, dest)
        print(f"Installed {len(results)} DROID previews into {SITE}", flush=True)
    else:
        print(f"Prepared {len(results)} DROID previews under {stage}", flush=True)


if __name__ == "__main__":
    main()
