#!/usr/bin/env python3
"""On-demand gripper-URDF / axis overlay renderer for any camx_480p LeRobot dataset.

CPU only (numpy + cv2 + PyAV), no Rerun viewer, so it can run inside a web service. The scene is
assembled by the same code the validation clips use (camera-cross-embodiment/camx/visualization:
viz config per collection, per-episode intrinsics from meta/episodes, gripper profile + mount /
eef anchoring from gripper_registry, width -> joint mapping, the fisheye tool's calibrations) and
rasterised here.

Per view, per frame:
  * the gripper URDF of every side is placed through the dataset's own camera trajectory and
    eef / mount transform, posed at the recorded gripper width, projected with the episode's K
    (pinhole) or the rig's Kannala-Brandt / EUCM calibration (fisheye);
  * a side whose rig has no URDF profile gets a jaw bar spanning the recorded width at the TCP
    plus the TCP axes; every view also gets the other cameras' frames and paths when no URDF is
    drawn, so the pose chain can still be judged;
  * fisheye views with neither a calibration nor a config FOV are left undrawn.

CLI:  python overlay_render.py aloha/abc/zip_up_the_jacket_realsense --episode 11 --frame 300 --out /tmp/f.jpg
      python overlay_render.py robotiq/droid/WEIRD_success --episode 0 --clip /tmp/c.mp4 --seconds 10
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import math
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import av
import cv2
import numpy as np
import trimesh
from scipy.spatial.transform import Rotation as R

VIZ_DIR = Path(os.environ.get("CAMX_VIZ_DIR", "~/projects/camera-cross-embodiment/camx/visualization")).expanduser()
sys.path.insert(0, str(VIZ_DIR))
sys.path.insert(0, str(VIZ_DIR / "mv_site"))
import lerobot_rerun_viz as viz  # noqa: E402
import gripper_registry  # noqa: E402
import urdf_logger  # noqa: E402
import build_mv_site as mv  # noqa: E402  (config_for / profile_for / RRD_EXTRA_ARGS)
import render_bimanual_urdf_overlay_video as fisheye_tool  # noqa: E402  (Calib, load_calib, calib_to_video, project)

CAMX_ROOT = Path(os.environ.get("CAMX_ROOT", str(mv.CAMX_ROOT)))
CALIB_DIR = VIZ_DIR / "calib"

SIDE_COLOR = {"right": (235, 205, 170), "left": (170, 225, 190), "head": (200, 200, 215)}  # BGR, light tints
AXIS_COLOR = ((0, 0, 255), (0, 255, 0), (255, 0, 0))  # x red, y green, z blue (BGR)
PATH_COLOR = (0, 200, 255)
JAW_COLOR = (0, 255, 255)

# Collections the clip builder's config_for() does not map, with the viz config that fits them
# (loaded tolerantly: config videos the dataset lacks are dropped instead of aborting).
SECONDARY_CONFIG = {
    "hifi_umi/hifi_umi": "hifi_umi.json", "stretch/dobbe": "dobbe.json", "franka_hand/fmb": "fmb.json",
    "ur/openneo_ur": "openneo.json", "flexiv/openneo_flexiv": "openneo_flexiv.json", "aloha/openneo_aloha": "openneo_aloha.json",
    "aloha/openneo_arx5": "openneo.json", "aloha/openneo_arx5_single": "openneo_single.json",
    "umi/openneo_umi": "openneo_umi.json", "umi/openneo_umi_single": "openneo_umi_single.json",
    "robotiq/robomind_ur5": "robomind_ur5.json", "daimon/dataclaw": "dataclaw.json",
    "genrobot/10kh": "genrobot_bimanual.json", "genrobot/gripper_v4": "genrobot.json",
}
# Visuals of a gripper NOT drawn in the view of the camera that rides on it (the housing sits on the lens
# and would blanket the image); same lists the fisheye clip tool uses.
OWN_VIEW_EXCLUDE = {
    "genrobot_das_v4": {"base_link", "link_imu", "link_ca1", "link_ca2", "link_ca3"},
    "umi": {"world_body_0_geom_3", "world_body_0_geom_9"}, "iphumi": {"world_body_0_geom_3", "world_body_0_geom_9"},
    "umift": {"base_white", "base_dark", "base_grey"}, "rby1_finray": {"ee_body_visual"},
}


# ── small transform helpers ──────────────────────────────────────────────

def pose7_T(p) -> np.ndarray:
    p = np.asarray(p, dtype=np.float64).reshape(7)
    T = np.eye(4)
    T[:3, :3] = R.from_quat([p[4], p[5], p[6], p[3]]).as_matrix()
    T[:3, 3] = p[:3]
    return T


def posrot_T(pos, rotvec) -> np.ndarray:
    T = np.eye(4)
    T[:3, :3] = R.from_rotvec(np.asarray(rotvec, dtype=np.float64)).as_matrix()
    T[:3, 3] = pos
    return T


def inv_T(T: np.ndarray) -> np.ndarray:
    Ti = np.eye(4)
    Ti[:3, :3] = T[:3, :3].T
    Ti[:3, 3] = -T[:3, :3].T @ T[:3, 3]
    return Ti


def apply_T(T: np.ndarray, pts: np.ndarray) -> np.ndarray:
    return pts @ T[:3, :3].T + T[:3, 3]


# ── URDF geometry (visual meshes in link frames + FK per gripper width) ───

class UrdfMesh:
    def __init__(self, inst):
        self.inst = inst
        prof, urdf = inst.profile, inst.urdf
        urdf_dir = prof.urdf_path(inst.side).parent
        self.visuals: list[tuple[str, str, np.ndarray, np.ndarray]] = []  # (link, name, verts_link, faces)
        for link_name, link in urdf.link_map.items():
            if link_name in prof.hidden_links:
                continue
            for i, v in enumerate(link.visuals):
                vname = v.name or f"{link_name}_visual_{i}"
                if vname in prof.exclude_visual_names:
                    continue
                mesh_geo = getattr(v.geometry, "mesh", None)
                box_geo = getattr(v.geometry, "box", None)
                cyl_geo = getattr(v.geometry, "cylinder", None)
                if mesh_geo is not None and mesh_geo.filename:
                    path = urdf_logger._resolve_mesh_path(urdf_dir, mesh_geo.filename)
                    if not path.is_file():
                        continue
                    tm = trimesh.load(str(path), force="mesh")
                elif box_geo is not None:
                    tm = trimesh.creation.box(extents=np.asarray(box_geo.size, dtype=np.float64))
                elif cyl_geo is not None:
                    tm = trimesh.creation.cylinder(radius=float(cyl_geo.radius), height=float(cyl_geo.length), sections=24)
                else:
                    continue
                origin = np.asarray(v.origin, dtype=np.float64) if v.origin is not None else np.eye(4)
                verts = np.asarray(tm.vertices, dtype=np.float64)
                if mesh_geo is not None and mesh_geo.scale is not None:
                    verts = verts * np.broadcast_to(np.asarray(mesh_geo.scale, dtype=np.float64), (3,))[None, :]
                verts = apply_T(origin, verts)
                self.visuals.append((link_name, vname, verts, np.asarray(tm.faces, dtype=np.int64)))
        self.n_faces = sum(len(f) for _, _, _, f in self.visuals)
        self.own_exclude = OWN_VIEW_EXCLUDE.get(prof.name, set())
        self._cache: dict[int, list[np.ndarray]] = {}
        self._lock = threading.Lock()

    def verts_root(self, width_m: float) -> list[np.ndarray]:
        prof, urdf = self.inst.profile, self.inst.urdf
        w = min(max(float(width_m), prof.width_min), prof.width_max) if np.isfinite(width_m) else prof.width_max
        key = int(round(w * 2000))
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None:
                return hit
            joints = prof.width_to_joints(key / 2000.0)
            cfg = np.asarray(urdf.cfg, dtype=np.float64).copy()
            for jn, val in joints.items():
                if jn in urdf.actuated_joint_names:
                    cfg[urdf.actuated_joint_names.index(jn)] = val
            urdf.update_cfg(cfg)
            out = []
            for link_name, _, verts, _ in self.visuals:
                T = np.asarray(urdf.get_transform(frame_to=link_name, frame_from=urdf.base_link), dtype=np.float64)
                out.append(apply_T(T, verts))
            if len(self._cache) > 400:
                self._cache.clear()
            self._cache[key] = out
            return out


# ── projection + rasterisation ───────────────────────────────────────────

_LIGHT = np.array([0.3, -0.5, -0.8]); _LIGHT /= np.linalg.norm(_LIGHT)


class Projector:
    """(N,3) camera-optical points -> (uv (N,2), ok (N,)); pinhole from (fx,fy,cx,cy) or the fisheye tool's Calib."""

    def __init__(self, K=None, calib=None, near=0.004):
        self.K, self.calib, self.near = K, calib, near
        self.model = calib.model if calib is not None else "pinhole"

    def __call__(self, pts_cam: np.ndarray):
        pts_cam = np.asarray(pts_cam, dtype=np.float64).reshape(-1, 3)
        if self.calib is not None:
            uv = fisheye_tool.project(pts_cam, self.calib)
            ok = np.isfinite(uv).all(axis=1) & (pts_cam[:, 2] > self.near)
            return uv, ok
        fx, fy, cx, cy = self.K
        z = pts_cam[:, 2]
        ok = z > self.near
        uv = np.full((len(z), 2), np.nan)
        uv[ok, 0] = fx * pts_cam[ok, 0] / z[ok] + cx
        uv[ok, 1] = fy * pts_cam[ok, 1] / z[ok] + cy
        return uv, ok


def draw_mesh(img: np.ndarray, verts_cam: np.ndarray, faces: np.ndarray, proj: Projector, color, alpha=0.55,
              max_edge_frac=0.35, wire=False) -> int:
    """Flat-shaded, alpha-blended triangles (painter's order). Returns the number of triangles drawn."""
    h, w = img.shape[:2]
    uv, ok = proj(verts_cam)
    f = faces[ok[faces].all(axis=1)]
    if f.size == 0:
        return 0
    uvf = uv[f]
    edge = np.max(np.linalg.norm(uvf - np.roll(uvf, 1, axis=1), axis=2), axis=1)
    inside = ((uvf[:, :, 0] >= -w) & (uvf[:, :, 0] < 2 * w) & (uvf[:, :, 1] >= -h) & (uvf[:, :, 1] < 2 * h)).any(axis=1)
    keep = (edge < max_edge_frac * max(w, h)) & inside
    f, uvf = f[keep], uvf[keep]
    if f.size == 0:
        return 0
    p0, p1, p2 = verts_cam[f[:, 0]], verts_cam[f[:, 1]], verts_cam[f[:, 2]]
    n = np.cross(p1 - p0, p2 - p0)
    nn = np.linalg.norm(n, axis=1)
    good = nn > 1e-12
    f, uvf, n, nn = f[good], uvf[good], n[good], nn[good]
    n = n / nn[:, None]
    shade = 0.45 + 0.55 * np.abs(n @ _LIGHT)
    depth = np.linalg.norm(verts_cam[f].mean(axis=1), axis=1)
    order = np.argsort(-depth)
    layer = img.copy()
    mask = np.zeros((h, w), dtype=np.uint8)
    col = np.asarray(color, dtype=np.float64)
    pts = np.round(uvf).astype(np.int32)
    for i in order:
        c = tuple(int(v) for v in np.clip(col * shade[i], 0, 255))
        if wire:
            cv2.polylines(layer, [pts[i]], True, c, 1, cv2.LINE_AA)
            cv2.polylines(mask, [pts[i]], True, 255, 1, cv2.LINE_AA)
        else:
            cv2.fillConvexPoly(layer, pts[i], c, cv2.LINE_8)
            cv2.fillConvexPoly(mask, pts[i], 255, cv2.LINE_8)
    blended = cv2.addWeighted(img, 1.0 - alpha, layer, alpha, 0.0)
    m = mask > 0
    img[m] = blended[m]
    return int(len(f))


def _line(img, a, b, color, thickness):
    if np.all(np.abs(a) < 1e5) and np.all(np.abs(b) < 1e5):
        cv2.line(img, tuple(np.round(a).astype(int)), tuple(np.round(b).astype(int)), color, thickness, cv2.LINE_AA)


def draw_axes(img, cam_T_frame, proj: Projector, length=0.05, thickness=2, label=None):
    o = cam_T_frame[:3, 3]
    pts = np.vstack([o[None], np.stack([o + cam_T_frame[:3, k] * length for k in range(3)])])
    uv, ok = proj(pts)
    if not ok[0]:
        return False
    for k in range(3):
        if ok[k + 1]:
            _line(img, uv[0], uv[k + 1], AXIS_COLOR[k], thickness)
    p0 = tuple(np.round(uv[0]).astype(int))
    cv2.circle(img, p0, 3, (255, 255, 255), -1, cv2.LINE_AA)
    if label:
        cv2.putText(img, label, (p0[0] + 5, p0[1] - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(img, label, (p0[0] + 5, p0[1] - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
    return True


def draw_jaw(img, cam_T_tcp, width_m, proj: Projector, color=JAW_COLOR):
    """Jaw bar spanning the recorded tip gap along TCP y, with fingertip pads: the no-CAD stand-in."""
    if not np.isfinite(width_m):
        return
    h = max(0.0, float(width_m)) / 2.0
    pts_t = np.array([[0, -h, 0], [0, h, 0], [-0.02, -h, 0], [-0.02, h, 0]])
    uv, ok = proj(apply_T(cam_T_tcp, pts_t))
    if ok[0] and ok[1]:
        _line(img, uv[0], uv[1], color, 3)
    for a, b in ((0, 2), (1, 3)):
        if ok[a] and ok[b]:
            _line(img, uv[a], uv[b], color, 5)


def draw_path(img, pts_cam, proj: Projector, color=PATH_COLOR, min_dist=0.03):
    uv, ok = proj(pts_cam)
    ok &= np.linalg.norm(pts_cam, axis=1) > min_dist
    seg = []
    for p, good in zip(uv, ok):
        if good and np.all(np.abs(p) < 1e5):
            seg.append(np.round(p).astype(np.int32))
        else:
            if len(seg) > 1:
                cv2.polylines(img, [np.stack(seg)], False, color, 2, cv2.LINE_AA)
            seg = []
    if len(seg) > 1:
        cv2.polylines(img, [np.stack(seg)], False, color, 2, cv2.LINE_AA)


def label(img, text, y=18):
    cv2.putText(img, text, (6, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(img, text, (6, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)


# ── video decoding ───────────────────────────────────────────────────────

class Decoder:
    """Frame-accurate reader of one LeRobot video file (episodes are concatenated; `from_ts` offsets)."""

    def __init__(self, path: Path, from_ts: float, fps: float):
        self.path, self.from_ts, self.fps = Path(path), float(from_ts), float(fps)
        self.c = av.open(str(self.path))
        self.s = self.c.streams.video[0]
        self.s.thread_type = "AUTO"
        self.it = None
        self.last_i = None
        self.last = None

    def close(self):
        try:
            self.c.close()
        except Exception:  # noqa: BLE001
            pass

    def frame(self, i: int):
        if self.last_i == i and self.last is not None:
            return self.last
        target = self.from_ts + i / self.fps
        tb = float(self.s.time_base)
        if self.it is None or self.last_i is None or i < self.last_i or i > self.last_i + 60:
            self.c.seek(max(0, int((target - 0.05) / tb)), stream=self.s, backward=True, any_frame=False)
            self.it = self.c.decode(self.s)
        tol = 0.5 / self.fps
        out = None
        for fr in self.it:
            t = float(fr.pts * tb) if fr.pts is not None else None
            if t is None:
                continue
            if t >= target - tol:
                out = fr
                break
        if out is None:
            self.it = None
            return None
        img = out.to_ndarray(format="bgr24")
        self.last_i, self.last = i, img
        return img


# ── the scene ────────────────────────────────────────────────────────────

@dataclasses.dataclass
class View:
    name: str
    video_key: str
    spec: object
    w: int
    h: int
    K: tuple | None          # (fx, fy, cx, cy) or None
    K_source: str
    fisheye: bool
    projection: str          # pinhole | kb4 | eucm | none
    proj: Projector | None
    path: Path
    from_ts: float
    T_eye: np.ndarray        # camera-root -> this eye (identity unless a stereo eye)
    side: str | None
    own_side: str | None     # the gripper this camera rides on (its housing is not drawn here)


class Scene:
    def __init__(self, rel: str, episode: int, assume_hfov_deg: float = 70.0):
        t0 = time.time()
        self.rel, self.episode = rel, int(episode)
        self.root = CAMX_ROOT / rel
        self.warnings: list[str] = []
        self.lock = threading.Lock()
        info = viz._load_info(self.root)
        self.info = info
        feats = info["features"]
        self.fps = float(info["fps"])
        keys = [k for k in feats if k.startswith("observation.image.")]
        self.coll = "/".join(rel.split("/")[:2])
        self.name = "/".join(rel.split("/")[2:])
        videos, scalars = self._load_config(feats, keys, assume_hfov_deg)
        side_to_main = viz._side_to_main_camera_entity(videos)
        pims = viz._discover_pose_in_main_transforms(info, side_to_main)
        episodes = viz._build_episode_specs(self.root, info, videos, sides=side_to_main)
        self.n_episodes = len(episodes)
        ep = next((e for e in episodes if e.episode_index == self.episode), None)
        if ep is None:
            raise ValueError(f"episode {episode} not in {rel} ({len(episodes)} episodes)")
        self.ep = ep
        if ep.eef_pose_in_main:
            pims = [t for t in pims if t.child_name != "eef"]
        # stereo eyes: a video whose stream is `<side>_<child>` of a pose_in_main child of its main camera
        eye_child, eye_parent = {}, {}
        for v in videos:
            if not v.camera_trajectory_key:
                continue
            stream = v.video_key.split("observation.image.", 1)[-1].removesuffix("_rgb")
            side = v.camera_trajectory_key.rsplit(".", 1)[-1].removesuffix("_main_camera_trajectory_xyz_wxyz")
            main_entity = side_to_main.get(side, viz._camera_entity_root(v))
            for t in pims:
                if t.parent_entity == main_entity and stream == f"{side}_{t.child_name}":
                    eye_child[v.video_key] = t.child_name
                    eye_parent[v.video_key] = main_entity
                    break
        videos = [dataclasses.replace(v, seed_intrinsics=ep.camera_intrinsics.get(v.video_key),
                                      eye_child=eye_child.get(v.video_key), eye_parent=eye_parent.get(v.video_key))
                  for v in videos]
        self.videos, self.pims, self.side_to_main = videos, pims, side_to_main

        # grippers: one instance per side (per-episode variant, collection override, else info.json model)
        variants = {s: [m] for s, m in ep.gripper_variants}
        self.gripper_models = {}
        for side in side_to_main:
            model = (variants.get(side) or [info.get(f"{side}_gripper_model")])[0]
            prof = mv.profile_for(self.coll, side, model)
            base = gripper_registry.lookup(model)
            if prof is not None and (base is None or prof.name != base.name):
                variants[side] = [prof.name]
            self.gripper_models[side] = model
        self.instances = viz._resolve_gripper_instances(info, side_to_main, True, variants or None, ep.eef_pose_in_main or None)
        (self.frame_indices, cam_arrays, self.scalars, self.gripper_frames) = viz._load_episode_arrays(
            ep.data_path, videos, scalars, self.instances, self.episode,
            eef_pose_by_side=ep.eef_pose_in_main or None, variant_by_side=dict(ep.gripper_variants) or None)
        self.n_frames = int(len(self.frame_indices))
        self.world_T_cam = {name: np.stack([posrot_T(p, r) for p, r in zip(pos, rot)]) for name, (pos, rot) in cam_arrays.items()}
        self.meshes = {inst.key: UrdfMesh(inst) for inst in self.instances if inst.key in self.gripper_frames}
        # recorded width per side (for the jaw-bar stand-in of sides without a URDF)
        self.width_by_side = {}
        for s in scalars:
            if s.name in self.scalars and s.data_key.endswith("_gripper_width_m"):
                self.width_by_side[s.data_key.rsplit(".", 1)[-1].removesuffix("_gripper_width_m")] = self.scalars[s.name]
        self.urdf_sides = {inst.side for inst in self.instances if inst.key in self.gripper_frames}
        for inst in self.instances:
            if inst.key not in self.gripper_frames:
                self.warnings.append(f"{inst.side}: gripper profile {inst.profile.name} resolved but no width / trajectory column for this episode")
        for side in side_to_main:
            if side not in self.urdf_sides:
                m = self.gripper_models.get(side)
                how = "jaw bar at the recorded width + TCP axes" if self._tcp_pose(side) is not None and side in self.width_by_side else "axes / camera path only"
                self.warnings.append(f"{side}: no URDF profile for gripper model {m!r} -> {how}" if m
                                     else f"{side}: dataset names no gripper model -> {how}")

        # views
        self.views: list[View] = []
        for v in videos:
            shape = feats[v.video_key]["shape"]
            w, h = int(shape[1]), int(shape[0])
            stream = v.video_key.split("observation.image.", 1)[-1].removesuffix("_rgb")
            side = v.camera_trajectory_key.rsplit(".", 1)[-1].removesuffix("_main_camera_trajectory_xyz_wxyz") if v.camera_trajectory_key else None
            model = info.get(f"{stream}_model") or info.get(f"{stream}_camera_model")
            fisheye = bool(info.get(f"{stream}_is_fisheye") or info.get(f"{stream}_camera_is_fisheye"))
            K, src, projection, proj = None, "none", "none", None
            if v.camera_trajectory_key and v.name in self.world_T_cam:
                calib = self._fisheye_calib(stream, side, model, w, h)
                if calib is not None:
                    projection, proj = calib.model, Projector(calib=calib)
                    src = f"{calib.model.upper()} calibration {Path(calib.source).name}"
                    fisheye = True
                    K = (calib.K[0, 0], calib.K[1, 1], calib.K[0, 2], calib.K[1, 2])
                elif v.video_key in ep.camera_intrinsics:
                    K, src = tuple(ep.camera_intrinsics[v.video_key]), "meta/episodes (per-episode calibration)"
                elif v.fx is not None or v.hfov_deg is not None:
                    K, src = v.intrinsics_px(), ("viz config" if self.config else f"assumed {assume_hfov_deg:g} deg HFOV")
                    if fisheye and self.config is None:
                        K, src = None, "fisheye without calibration (not drawn)"
                        self.warnings.append(f"{v.name}: fisheye stream and no calibration or viz config -> overlay skipped")
                    elif fisheye:
                        src += " (pinhole approximation on a fisheye lens)"
                if K is not None and proj is None:
                    projection, proj = "pinhole", Projector(K=K)
            elif v.camera_trajectory_key:
                src = "no trajectory column in this episode"
            else:
                src = "no camera trajectory (2-D stream)"
            T_eye = np.eye(4)
            if v.eye_child:
                t = next((t for t in pims if t.parent_entity == v.eye_parent and t.child_name == v.eye_child), None)
                if t is not None:
                    T_eye = pose7_T(t.pose7)
            own = side if (side in self.urdf_sides and self._camera_rides_on_gripper(side)) else None
            self.views.append(View(v.name, v.video_key, v, w, h, K, src, fisheye, projection, proj, ep.video_paths[v.video_key],
                                   ep.video_from_timestamps[v.video_key], T_eye, side, own))
        self.decoders: dict[str, Decoder] = {}
        self.task = ep.task_name
        self.build_seconds = round(time.time() - t0, 2)

    # ── scene assembly helpers ──

    def _load_config(self, feats, keys, hfov):
        """Viz config for the collection (config_for, then SECONDARY_CONFIG), loaded tolerantly; else the name-pairing fallback."""
        self.config = None
        cfg = None
        try:
            cfg = mv.config_for(self.coll, str(self.info.get("robot_type") or ""), len(keys), keys, self.rel)
        except (Exception, SystemExit) as e:  # noqa: BLE001  (the viz helpers raise SystemExit on bad input)
            self.warnings.append(f"config_for failed: {e}")
        if cfg is None:
            sec = SECONDARY_CONFIG.get(self.coll) or ("rh20t.json" if self.coll.split("/")[1].startswith("rh20t") else None)
            cfg = VIZ_DIR / "config" / sec if sec else None
        if cfg is not None and Path(cfg).is_file():
            try:
                payload = json.loads(Path(cfg).read_text())
                vids = payload.get("videos", [])
                keep = [v for v in vids if v.get("video_key") in feats]
                if len(keep) != len(vids):
                    self.warnings.append(f"{Path(cfg).name}: dropped {len(vids) - len(keep)} config video(s) this dataset lacks")
                payload = dict(payload, videos=keep, scalars=[s for s in payload.get("scalars", []) if s.get("data_key") in feats])
                videos = viz._load_video_specs(feats, payload)
                scalars = viz._load_scalar_specs(feats, payload)
                if videos:
                    self.config = str(Path(cfg).relative_to(VIZ_DIR)) if str(cfg).startswith(str(VIZ_DIR)) else str(cfg)
                    # config-less streams of the dataset still get a name-paired spec so every view is shown
                    have = {v.video_key for v in videos}
                    extra, extra_sc = self._fallback_specs({k: f for k, f in feats.items() if k not in have or f.get("dtype") != "video"}, hfov)
                    return videos + [e for e in extra if e.video_key not in have], scalars + [s for s in extra_sc if s.data_key not in {x.data_key for x in scalars}]
            except (Exception, SystemExit) as e:  # noqa: BLE001
                self.warnings.append(f"viz config {Path(cfg).name} does not fit this dataset ({e}); using the fallback")
        videos, scalars = self._fallback_specs(feats, hfov)
        self.warnings.append(
            f"no usable viz config for {self.coll}: cameras paired to trajectories by name; intrinsics from "
            f"meta/episodes where present, else an ASSUMED {hfov:g} deg HFOV")
        return videos, scalars

    @staticmethod
    def _fallback_specs(feats, hfov):
        videos, scalars = [], []
        for k, f in feats.items():
            if f.get("dtype") != "video":
                continue
            stream = k.split("observation.image.", 1)[-1].removesuffix("_rgb")
            traj = None
            for cand in (f"observation.state.{stream}_trajectory_xyz_wxyz", f"observation.state.{stream}_camera_trajectory_xyz_wxyz"):
                if cand in feats:
                    traj = cand
                    break
            if traj is None:  # attached / stereo streams ride on their side's main camera
                side = stream.split("_", 1)[0]
                cand = f"observation.state.{side}_main_camera_trajectory_xyz_wxyz"
                if cand in feats and stream != f"{side}_main_camera":
                    traj = cand
            videos.append(viz.VideoSpec(name=stream + ("_rgb" if k.endswith("_rgb") else ""), video_key=k,
                                        camera_trajectory_key=traj, hfov_deg=hfov,
                                        resolution=(int(f["shape"][1]), int(f["shape"][0]))))
        for k in feats:
            if k.startswith("observation.state.") and k.endswith("_gripper_width_m"):
                scalars.append(viz.ScalarSpec(name=k.rsplit(".", 1)[-1], data_key=k))
        return videos, scalars

    def _fisheye_calib(self, stream, side, model, w, h):
        """The fisheye tool's calibration for this stream, mapped onto the stored video, or None (pinhole rig)."""
        m = (model or "").lower()
        fam = self.coll.split("/")[0]
        path, fit = None, "crop"
        if fam == "hifi_umi":
            path = CALIB_DIR / "hifi_umi_hand_fisheye.json"
        elif "fastumi pro" in m:
            path = CALIB_DIR / "umi_benchmark_fastumi_pro_seucm.json"
        elif "gopro" in m and "webcam" not in m:
            path = CALIB_DIR / "gopro_hero9_maxlens_2_7k_umi.json"  # UMI GoPro + Max Lens Mod
        elif fam == "genrobot":
            per_ep = CALIB_DIR / "genrobot_episodes" / f"{self.name}_ep{self.episode}_{side}.json"
            path = per_ep if per_ep.is_file() else CALIB_DIR / ("genrobot_das_camera0_sewing_mean.json" if "sewing" in self.name else "genrobot_das_camera0_session_mean.json")
            fit = "stretch"
        elif fam == "daimon":
            dev = CALIB_DIR / f"daimon_dataclaw_{self.name.split('_')[0]}.json"
            path = dev if dev.is_file() else CALIB_DIR / "daimon_dataclaw_fleet_fallback.json"
        elif "freetacman" in self.coll:
            path = CALIB_DIR / "freetacman_camera3_equidistant.json"
            fit = "stretch"
        if path is None or not path.is_file():
            return None
        try:
            c = fisheye_tool.load_calib(path)
            return fisheye_tool.calib_to_video(c, w, h, fit, None)
        except (Exception, SystemExit) as e:  # noqa: BLE001
            self.warnings.append(f"{stream}: calibration {path.name} unusable ({e})")
            return None

    def _camera_rides_on_gripper(self, side) -> bool:
        """True when the side's main camera is mounted on the gripper (handheld rigs / wrist cams anchored by mount link)."""
        inst = next((i for i in self.instances if i.side == side), None)
        return inst is not None and (inst.profile.mount_link_name is not None or inst.profile.name in OWN_VIEW_EXCLUDE)

    def _tcp_pose(self, side):
        eef = self.ep.eef_pose_in_main.get(side)
        if eef is None:
            ent = self.side_to_main.get(side)
            t = next((t for t in self.pims if t.parent_entity == ent and t.child_name == "eef"), None)
            eef = t.pose7 if t is not None else None
        return eef

    def close(self):
        for d in self.decoders.values():
            d.close()
        self.decoders.clear()

    def describe(self) -> dict:
        grips = {}
        for inst in self.instances:
            key = inst.key
            src = ("mount link " + inst.profile.mount_link_name) if inst.profile.mount_link_name else (
                "per-episode eef_pose_in_main" if inst.side in self.ep.eef_pose_in_main else "info.json eef_pose_in_main")
            grips[inst.side] = {"model": self.gripper_models.get(inst.side), "profile": inst.profile.name, "variant": inst.variant,
                                "urdf": str(inst.profile.urdf_path(inst.side).relative_to(gripper_registry.GRIPPERS_ROOT)),
                                "anchor": src, "active": key in self.gripper_frames,
                                "faces": self.meshes[key].n_faces if key in self.meshes else 0}
        for side in self.side_to_main:
            if side not in grips:
                jaw = self._tcp_pose(side) is not None and side in self.width_by_side
                grips[side] = {"model": self.gripper_models.get(side), "profile": None, "active": False,
                               "anchor": "jaw bar at recorded width + TCP axes" if jaw else "axes only"}
        return {"dataset": self.rel, "episode": self.episode, "n_episodes": self.n_episodes, "n_frames": self.n_frames,
                "fps": self.fps, "task": self.task, "robot_type": self.info.get("robot_type"), "config": self.config,
                "views": [{"name": v.name, "w": v.w, "h": v.h, "K": [round(float(x), 2) for x in v.K] if v.K else None,
                           "K_source": v.K_source, "fisheye": v.fisheye, "projection": v.projection, "drawable": v.proj is not None,
                           "own_side": v.own_side} for v in self.views],
                "grippers": grips, "warnings": self.warnings, "build_seconds": self.build_seconds}

    # ── rendering ──

    def _decoder(self, v: View) -> Decoder:
        d = self.decoders.get(v.name)
        if d is None:
            d = self.decoders[v.name] = Decoder(v.path, v.from_ts, self.fps)
        return d

    def render_view(self, v: View, i: int, draw_urdf=True, draw_axes_mode="auto", draw_path_mode="auto", alpha=0.55, wire=False):
        img = self._decoder(v).frame(i)
        if img is None:
            img = np.zeros((v.h, v.w, 3), dtype=np.uint8)
            label(img, "frame not decodable", 40)
        if img.shape[0] != v.h or img.shape[1] != v.w:
            img = cv2.resize(img, (v.w, v.h))
        tris = 0
        drew_urdf = False
        if v.proj is not None and v.name in self.world_T_cam:
            world_T_view = self.world_T_cam[v.name][i] @ v.T_eye
            cam_T_world = inv_T(world_T_view)
            if draw_urdf:
                for inst in self.instances:
                    fd = self.gripper_frames.get(inst.key)
                    if fd is None:
                        continue
                    root_pose7s, widths = fd
                    cam_T_root = cam_T_world @ pose7_T(root_pose7s[i])
                    color = SIDE_COLOR.get(inst.side, (200, 200, 215))
                    mesh = self.meshes[inst.key]
                    skip = mesh.own_exclude if v.own_side == inst.side else set()
                    for verts_root, (link, name, _, faces) in zip(mesh.verts_root(float(widths[i])), mesh.visuals):
                        if skip and (name in skip or link in skip):
                            continue
                        tris += draw_mesh(img, apply_T(cam_T_root, verts_root), faces, v.proj, color, alpha, wire=wire)
                    drew_urdf = True
                # sides without a URDF: jaw bar at the TCP spanning the recorded width
                for side, ent in self.side_to_main.items():
                    if side in self.urdf_sides:
                        continue
                    eef = self._tcp_pose(side)
                    main_name = ent.rsplit("/", 1)[-1]
                    if eef is None or main_name not in self.world_T_cam or side not in self.width_by_side:
                        continue
                    cam_T_tcp = cam_T_world @ self.world_T_cam[main_name][i] @ pose7_T(eef)
                    draw_jaw(img, cam_T_tcp, float(self.width_by_side[side][i]), v.proj)
                    draw_axes(img, cam_T_tcp, v.proj, 0.04, 2, f"{side} tcp")
            want_axes = draw_axes_mode == "on" or (draw_axes_mode == "auto" and not drew_urdf)
            want_path = draw_path_mode == "on" or (draw_path_mode == "auto" and not drew_urdf)
            if want_axes:
                for side, ent in self.side_to_main.items():
                    main_name = ent.rsplit("/", 1)[-1]
                    eef = self._tcp_pose(side)
                    if eef is not None and main_name in self.world_T_cam:
                        draw_axes(img, cam_T_world @ self.world_T_cam[main_name][i] @ pose7_T(eef), v.proj, 0.05, 2, f"{side} eef")
                for name, Ts in self.world_T_cam.items():
                    if name == v.name:
                        continue
                    draw_axes(img, cam_T_world @ Ts[i], v.proj, 0.03, 1, name.replace("_camera_rgb", "").replace("_rgb", ""))
            if want_path:
                n_ahead = int(3 * self.fps)
                for name, Ts in self.world_T_cam.items():
                    seg = Ts[i:i + n_ahead:max(1, int(self.fps // 10)), :3, 3]
                    if len(seg) > 1:
                        draw_path(img, apply_T(cam_T_world, seg), v.proj)
        else:
            label(img, "not drawn: " + v.K_source, 40)
        wtxt = ""
        if v.side in self.width_by_side:
            wtxt = f"  w={float(self.width_by_side[v.side][i]) * 1000:.0f}mm"
        label(img, f"{v.name.replace('_rgb', '')}  ep{self.episode} f{i}{wtxt}  {v.projection}" + (f"  {tris} tris" if tris else ""))
        return img

    def render_frame(self, i: int, views=None, **kw) -> np.ndarray:
        i = max(0, min(int(i), self.n_frames - 1))
        vs = [v for v in self.views if views is None or v.name in views] or self.views
        with self.lock:
            tiles = [self.render_view(v, i, **kw) for v in vs]
        H = max(t.shape[0] for t in tiles)
        tiles = [t if t.shape[0] == H else cv2.copyMakeBorder(t, 0, H - t.shape[0], 0, 0, cv2.BORDER_CONSTANT) for t in tiles]
        return np.hstack(tiles)

    def render_clip(self, out_path: Path, start=0, seconds=10.0, out_fps=10.0, views=None, progress=None, **kw) -> dict:
        step = max(1, int(round(self.fps / out_fps)))
        end = min(self.n_frames, int(start + seconds * self.fps))
        frames = list(range(int(start), end, step))
        if not frames:
            raise ValueError("empty frame range")
        first = self.render_frame(frames[0], views, **kw)
        h, w = first.shape[:2]
        w -= w % 2; h -= h % 2
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        enc = subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
                                "-s", f"{w}x{h}", "-r", f"{self.fps / step:g}", "-i", "-", "-c:v", "libx264", "-preset", "veryfast",
                                "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out_path)],
                               stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        t0 = time.time()
        try:
            for n, fi in enumerate(frames):
                img = first if n == 0 else self.render_frame(fi, views, **kw)
                enc.stdin.write(np.ascontiguousarray(img[:h, :w]).tobytes())
                if progress:
                    progress(n + 1, len(frames))
        finally:
            enc.stdin.close()
            err = enc.stderr.read().decode(errors="replace")
            enc.wait()
        if enc.returncode != 0:
            raise RuntimeError("ffmpeg failed: " + err[-500:])
        cv2.imwrite(str(out_path.with_suffix(".jpg")), first[:h, :w], [cv2.IMWRITE_JPEG_QUALITY, 80])
        return {"frames": len(frames), "out_fps": self.fps / step, "seconds": round(time.time() - t0, 1), "width": w, "height": h}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dataset", help="path under camx_480p, e.g. aloha/abc/zip_up_the_jacket_realsense")
    ap.add_argument("--episode", type=int, default=0)
    ap.add_argument("--frame", type=int, default=0)
    ap.add_argument("--out", type=Path, help="write this frame as an image")
    ap.add_argument("--clip", type=Path, help="write a clip (mp4)")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--out-fps", type=float, default=10.0)
    ap.add_argument("--views", default=None, help="comma-separated view names (default all)")
    ap.add_argument("--axes", default="auto", choices=["auto", "on", "off"])
    ap.add_argument("--path", default="auto", choices=["auto", "on", "off"])
    ap.add_argument("--no-urdf", action="store_true")
    ap.add_argument("--wire", action="store_true")
    a = ap.parse_args()
    sc = Scene(a.dataset, a.episode)
    print(json.dumps(sc.describe(), indent=1))
    views = a.views.split(",") if a.views else None
    kw = dict(draw_urdf=not a.no_urdf, draw_axes_mode=a.axes, draw_path_mode=a.path, wire=a.wire)
    if a.out:
        t = time.time()
        img = sc.render_frame(a.frame, views, **kw)
        cv2.imwrite(str(a.out), img)
        print(f"frame {a.frame} -> {a.out} {img.shape[1]}x{img.shape[0]} in {time.time() - t:.2f}s")
    if a.clip:
        print(sc.render_clip(a.clip, a.start, a.seconds, a.out_fps, views, progress=lambda n, N: print(f"\r{n}/{N}", end=""), **kw))
    sc.close()


if __name__ == "__main__":
    main()
