# ManipForce two-view CAD-projection clips: render runbook (prepared 2026-10-17)

Three site clips (`battery_insertion__ep0`, `box_flipping__ep0`, `gear_assembly__ep8`), each main D455 | attached D405 with the
author CAD (`grippers/manipforce`) drawn through the image-fitted cameras. Pipeline: `tools/rerun_clips.py` multiview route ->
`tools/white_multiview.py` -> `$CAMX_VIZ/render_multiview_overlay_video.py --viz-config config/manipforce_2view.json
--profile registry:manipforce` (spec `overlay_picks.MANIPFORCE`). The clip records in `data/datasets.json` are already the targets.

## 0. Environment (every command below, from the website repo root)

```sh
export CAMX_ROOT=/storage/hdd4/yihuai/camx_480p CAMX_CURATION=/storage/hdd4/yihuai/camx_480p_browser/mv_urdf/videos \
       CAMX_CLIPS_OUT=/storage/ssd1/yihuai/data/mv_urdf_work/camx_site_1003 \
       MV_SITE_MESA=/storage/ssd1/yihuai/data/mv_urdf_work/camx_site_1003/mesa_shim \
       CAMX_PY=~/miniforge3/envs/iphumi/bin/python \
       CAMX_VIZ=~/video-gen/repositories/camera-cross-embodiment/camx/visualization
export CAMX_VIZ_MV=$CAMX_VIZ
cd ~/robotics/websites/camx-anonymous.github.io && git status --short
```

## 1. Preflight (once the backfill has landed under `$CAMX_ROOT/manipforce/manipforce/<task>`)

```sh
$CAMX_PY -c "
import json, os
for t in ('battery_insertion', 'box_flipping', 'gear_assembly'):
    i = json.load(open(os.environ['CAMX_ROOT'] + '/manipforce/manipforce/' + t + '/meta/info.json'))
    print(t, 'width col:', 'observation.state.right_gripper_width_m' in i['features'],
          'eef:', i.get('right_eef_pose_in_main_xyz_wxyz'), 'd405 pose:', i.get('right_attached_camera_0_pose_in_main_xyz_wxyz'),
          'd405 K:', i.get('right_attached_camera_0_intrinsics_fx_fy_cx_cy'))
"
```
All three must print `width col: True`, a non-zero-translation eef (expected ~ `[0.00003, 0.0461, 0.1337, 0.0026, -0.0061, -0.1743, 0.9847]`
= inv(camera_in_tcp) of `cad_projection_all_tasks_20261017.json`) and a D405 pose.

D405 lens: if `camx/data_processing/manipforce/config/cad_projection_d405_20261017.json` exists (or the printed `d405 K` is not
`[450, 450, 320, 240]`), set the attached view of `$CAMX_VIZ/config/manipforce_2view.json` from the fitted fx, fy, cx, cy at 640x480:
`hfov_deg = 2*atan(320/fx)`, `vfov_deg = 2*atan(240/fy)`, `cx_rel = cx/640`, `cy_rel = cy/480` (degrees), and drop the PLACEHOLDER
remarks (`_intrinsics_source`, `_README`, `_note`). The renderer does not read info.json intrinsics; the config is the only lens source.

```sh
$CAMX_PY tools/rerun_clips.py plan --only manipforce
```
Expected (stderr `{'multiview': 3}`):
```
multiview manipforce_manipforce/battery_insertion__ep0  config/manipforce_2view.json
multiview manipforce_manipforce/box_flipping__ep0  config/manipforce_2view.json
multiview manipforce_manipforce/gear_assembly__ep8  config/manipforce_2view.json
```

## 2. Render

```sh
$CAMX_PY tools/rerun_clips.py render --only manipforce --routes multiview --force
```
Expected one line per clip: `multiview manipforce_manipforce/<slug>: 2 view(s), N frames, Ts`, then `3/3 current clips in $CAMX_CLIPS_OUT`.
(`--force` is required: the old `box_flipping__ep0` / `gear_assembly__ep8` dirs hold raw-only renders.)

## 3. Verify, per `$CAMX_CLIPS_OUT/manipforce_manipforce/<slug>/`

- `stitched.png`: left pane = main view with the CAD fingers on the real jaws; right pane = the attached D405 video (stored upside down,
  no rotation) with the CAD on the jaws seen from the other side. Grey, opaque meshes; no text labels.
- `_render.log`: `[view] right_main_camera_rgb ... f=(384.00,384.00)`, `[view] right_attached_camera_0_rgb ... f=(fx,fy) <- viz config`,
  `[gripper] right: ... -> manipforce (manipforce, eef); eef_pose_in_main present`, `[width] right: min .. max ..` with a non-zero,
  task-plausible range (battery ~5 mm, box_flipping 0 to ~49 mm, gear ~31 mm physical gap), no `[candidate]` / retarget lines.
- `meta.json`: `views` = 2 entries, `grippers.right` = `{profile: manipforce, urdf_present: true}`, `overlay_mode: urdf`,
  `overlay_label` and `review_note` present (from the spec), `render_provenance.fingerprint` set.

## 4. Encode and attach

```sh
$CAMX_PY tools/rerun_clips.py encode --only manipforce     # overlays/videos/manipforce_manipforce__<slug>.mp4 + overlays/posters/<..>.jpg
$CAMX_PY tools/rerun_clips.py attach                       # no --only: rewrites every clip record whose cache is current
git diff --stat data/datasets.json                         # expect only the 3 manipforce records to change (views, grippers, label, note, fingerprint, seconds, bytes)
```

## 5. Raw companions (same episode / views / sampling as the overlay clips)

```sh
uv run --with pyarrow python tools/raw_clips.py --only manipforce_manipforce --force
```
Writes `overlays/raw/manipforce_manipforce__<slug>.{mp4,jpg,json}`; check that each raw mp4 has the overlay clip's size and frame count.

## 6. Leftovers

- `battery_insertion__ep14` was dropped from `data/datasets.json` (2026-10-17). Its files `overlays/videos|posters|raw/
  manipforce_manipforce__battery_insertion__ep14.*` are still referenced by `gallery/evidence/VALIDATION.json`, `gallery/evidence/catalog.json`
  and the 20261016 snapshot, so they were left in place; delete them only together with a gallery evidence rebuild.
- `tools/overlay_picks.py list --only manipforce` shows the three NEW_PICKS plus three auto picks of the same project (the standalone
  tool's auto_picks runs for every SPECS entry; rerun_clips never uses all_picks). Harmless.
- Do not commit from a render session; review `git status --short` first.
