# CAMX Dataset

Project page and data manager: https://camx-anonymous.github.io/

This repository is anonymized for review.

## Pages

- `index.html` — the data manager: stats, faceted filters (morphology, form factor, embodiment, source,
  # camera views, camera composition/model, resolution, FPS, state channels, validation status, skills,
  hours / episodes per dataset), a project-grouped sortable table, and the batch downloader
  (JSON import/export, `hf` CLI / Python / bash generators).
- `overlays/` — camera-projection validation clips: the gripper URDF (or the camera path + up axis
  where no URDF is released) projected through each dataset's own poses and intrinsics.
  Clips are served from the `overlays-v1` GitHub release; posters live in `overlays/posters/`.
- `data/datasets.json` — one row per converted dataset (3,585) plus per-project aggregates.

## Rebuilding the data

```
python3 tools/build_site_data.py            # scans camx_480p, joins the inventory + stats, writes data/datasets.json
```

## Live overlay backend (`backend/`)

`viewer/` renders the gripper-URDF / axis projection of **any** dataset episode on demand instead of
showing fixed clips. It talks to a small FastAPI service that runs on the data machine next to
`camx_480p` and the `camera-cross-embodiment` checkout (it reuses that repo's viz configs, gripper
registry and fisheye calibrations; the rasteriser is CPU-only, no Rerun viewer needed):

```
backend/run.sh                 # nohup on :19529, log in _build/logs/server.log (venv /data/venvs/camx-overlay)
open http://<desktop>:19529/viewer/     # or tunnel: ssh -L 19529:127.0.0.1:19529 <desktop>, then the GitHub Pages viewer
                                        # page connects to http://127.0.0.1:19529 automatically
python backend/overlay_render.py <family>/<project>/<dataset> --episode N --frame F --out f.jpg   # CLI, same renderer
```

API: `/api/datasets`, `/api/scene?dataset=&episode=`, `/api/frame.jpg?dataset=&episode=&frame=`,
`POST /api/clip`, `/api/job/{key}`, `/clips/{key}.mp4` (rendered clips are cached under `_build/overlay_cache`).
