#!/usr/bin/env python3
"""CAMX overlay backend: renders gripper-URDF / axis projections for any camx_480p dataset on demand.

  /api/datasets                       every dataset the site knows (from data/datasets.json)
  /api/scene?dataset=&episode=        how the scene resolved: views, intrinsics source, gripper profiles, warnings
  /api/frame.jpg?dataset=&episode=&frame=[&views=a,b&urdf=1&axes=auto&path=auto&wire=0&scale=1]
  POST /api/clip {dataset, episode, start, seconds, out_fps, views, ...} -> job; /api/job/{key}; /clips/{key}.mp4
  /                                   the static site (data manager, viewer, overlays)

Run:  /data/venvs/camx-overlay/bin/python backend/server.py --port 19529
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from overlay_render import CAMX_ROOT, Scene  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
CACHE = Path(os.environ.get("CAMX_OVERLAY_CACHE", str(REPO / "_build" / "overlay_cache")))
CACHE.mkdir(parents=True, exist_ok=True)
DATA = json.load(open(REPO / "data" / "datasets.json"))
ROWS = {r["id"]: r for r in DATA["datasets"]}

app = FastAPI(title="CAMX overlay backend")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_scenes: OrderedDict[tuple[str, int], Scene] = OrderedDict()
_scenes_lock = threading.Lock()
_building: dict[tuple[str, int], threading.Event] = {}
MAX_SCENES = int(os.environ.get("CAMX_OVERLAY_MAX_SCENES", "8"))
_jobs: dict[str, dict] = {}
_pool = ThreadPoolExecutor(max_workers=int(os.environ.get("CAMX_OVERLAY_WORKERS", "2")))
# public exposure limits: bounded concurrent frame renders, bounded clip queue / length
_render_sem = threading.BoundedSemaphore(int(os.environ.get("CAMX_OVERLAY_RENDERS", "6")))
MAX_CLIP_SECONDS = float(os.environ.get("CAMX_OVERLAY_MAX_CLIP_SECONDS", "60"))
MAX_QUEUED_JOBS = int(os.environ.get("CAMX_OVERLAY_MAX_QUEUED", "12"))


def _valid_rel(rel: str) -> str:
    rel = rel.strip("/")
    if ".." in rel or not rel or not (CAMX_ROOT / rel / "meta" / "info.json").is_file():
        raise HTTPException(404, f"unknown dataset {rel!r}")
    return rel


def get_scene(rel: str, episode: int) -> Scene:
    key = (rel, int(episode))
    with _scenes_lock:
        sc = _scenes.get(key)
        if sc is not None:
            _scenes.move_to_end(key)
            return sc
        ev = _building.get(key)
        if ev is None:
            ev = _building[key] = threading.Event()
            owner = True
        else:
            owner = False
    if not owner:
        ev.wait()
        with _scenes_lock:
            sc = _scenes.get(key)
        if sc is None:
            raise HTTPException(500, "scene build failed")
        return sc
    try:
        sc = Scene(rel, episode)
    except (Exception, SystemExit) as e:  # noqa: BLE001  (the viz helpers raise SystemExit on bad input)
        with _scenes_lock:
            _building.pop(key, None)
        ev.set()
        raise HTTPException(422, f"{type(e).__name__}: {e}")
    with _scenes_lock:
        _scenes[key] = sc
        while len(_scenes) > MAX_SCENES:
            _, old = _scenes.popitem(last=False)
            old.close()
        _building.pop(key, None)
    ev.set()
    return sc


@app.get("/api/health")
def health():
    return {"ok": True, "root": str(CAMX_ROOT), "scenes": len(_scenes), "jobs": len(_jobs), "built": DATA["built"]}


@app.get("/api/datasets")
def datasets():
    return {"datasets": [{"id": r["id"], "project": r["project"], "embodiment": r["embodiment"], "robot_type": r["robot_type"],
                          "episodes": r["episodes"], "hours": r["hours"], "fps": r["fps"], "views": [c["name"] for c in r["cams"]],
                          "fisheye": r["fisheye"]} for r in DATA["datasets"]]}


@app.get("/api/scene")
async def scene(dataset: str, episode: int = 0):
    rel = _valid_rel(dataset)
    sc = await asyncio.to_thread(get_scene, rel, episode)
    return sc.describe()


def _parse_views(views: str | None):
    return [v for v in views.split(",") if v] if views else None


@app.get("/api/frame.jpg")
async def frame(dataset: str, episode: int = 0, frame: int = 0, views: str | None = None, urdf: int = 1,
                axes: str = "auto", path: str = "auto", wire: int = 0, scale: float = 1.0, q: int = 82):
    rel = _valid_rel(dataset)
    sc = await asyncio.to_thread(get_scene, rel, episode)

    def work():
        with _render_sem:
            img = sc.render_frame(frame, _parse_views(views), draw_urdf=bool(urdf), draw_axes_mode=axes, draw_path_mode=path, wire=bool(wire))
        if 0.1 <= scale < 0.999:
            img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, int(q)])
        return buf.tobytes()
    t = time.time()
    data = await asyncio.to_thread(work)
    return Response(data, media_type="image/jpeg", headers={"X-Render-Ms": str(int((time.time() - t) * 1000)),
                                                           "Cache-Control": "public, max-age=3600"})


class ClipReq(BaseModel):
    dataset: str
    episode: int = 0
    start: int = 0
    seconds: float = 10.0
    out_fps: float = 10.0
    views: list[str] | None = None
    urdf: bool = True
    axes: str = "auto"
    path: str = "auto"
    wire: bool = False


def _job_key(req: ClipReq) -> str:
    return hashlib.sha1(json.dumps(req.model_dump(), sort_keys=True).encode()).hexdigest()[:16]


def _run_job(key: str, req: ClipReq):
    job = _jobs[key]
    try:
        job["status"] = "building scene"
        sc = get_scene(_valid_rel(req.dataset), req.episode)
        job["status"] = "rendering"

        def prog(n, N):
            job["progress"] = n / N
            job["frames"] = [n, N]
        info = sc.render_clip(CACHE / f"{key}.mp4", req.start, req.seconds, req.out_fps, req.views, progress=prog,
                              draw_urdf=req.urdf, draw_axes_mode=req.axes, draw_path_mode=req.path, wire=req.wire)
        job.update({"status": "done", "progress": 1.0, "info": info, "url": f"/clips/{key}.mp4", "poster": f"/clips/{key}.jpg",
                    "finished": time.time()})
        json.dump(job, open(CACHE / f"{key}.json", "w"))
    except Exception as e:  # noqa: BLE001
        job.update({"status": "error", "error": f"{type(e).__name__}: {e}"})


@app.post("/api/clip")
def clip(req: ClipReq):
    _valid_rel(req.dataset)
    req.seconds = max(0.5, min(float(req.seconds), MAX_CLIP_SECONDS))
    req.out_fps = max(1.0, min(float(req.out_fps), 30.0))
    key = _job_key(req)
    cached = CACHE / f"{key}.json"
    if key not in _jobs and cached.is_file() and (CACHE / f"{key}.mp4").is_file():
        _jobs[key] = json.load(open(cached))
    if key not in _jobs:
        if sum(1 for j in _jobs.values() if j.get("status") in ("queued", "building scene", "rendering")) >= MAX_QUEUED_JOBS:
            raise HTTPException(429, "clip queue is full; try again in a minute")
        _jobs[key] = {"key": key, "request": req.model_dump(), "status": "queued", "progress": 0.0, "submitted": time.time()}
        _pool.submit(_run_job, key, req)
    return _jobs[key]


@app.get("/api/job/{key}")
def job(key: str):
    j = _jobs.get(key)
    if j is None:
        cached = CACHE / f"{key}.json"
        if cached.is_file():
            j = _jobs[key] = json.load(open(cached))
        else:
            raise HTTPException(404, "no such job")
    return j


@app.get("/api/jobs")
def jobs(dataset: str | None = None, episode: int | None = None):
    out = []
    for j in _jobs.values():
        r = j.get("request", {})
        if dataset and r.get("dataset") != dataset:
            continue
        if episode is not None and r.get("episode") != episode:
            continue
        out.append(j)
    if dataset:  # also the cached clips of earlier server runs
        for p in CACHE.glob("*.json"):
            if p.stem not in _jobs:
                try:
                    j = json.load(open(p))
                except Exception:  # noqa: BLE001
                    continue
                r = j.get("request", {})
                if r.get("dataset") == dataset and (episode is None or r.get("episode") == episode):
                    _jobs[p.stem] = j
                    out.append(j)
    out.sort(key=lambda j: -(j.get("submitted") or 0))
    return {"jobs": out[:50]}


app.mount("/clips", StaticFiles(directory=str(CACHE)), name="clips")
app.mount("/", StaticFiles(directory=str(REPO), html=True), name="site")


if __name__ == "__main__":
    import uvicorn
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=19529)
    a = ap.parse_args()
    uvicorn.run(app, host=a.host, port=a.port, log_level="info")
