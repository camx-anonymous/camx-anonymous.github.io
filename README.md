# CAMX Dataset

Project page and data manager: https://camx-anonymous.github.io/

This repository is anonymized for review.

## Pages

- `index.html` — the data manager: stats, faceted filters (morphology, form factor, embodiment, source,
  # camera views, camera composition/model, resolution, FPS, state channels, validation status, skills,
  hours / episodes per dataset), a project-grouped sortable table, and the batch downloader
  (JSON import/export, `hf` CLI / Python / bash generators).
- `overlays/` — camera-projection validation clips, a few example episodes per project: the gripper URDF
  (or the camera path + up axis where no URDF is released) projected through each dataset's own poses and
  intrinsics. Clips are served from the `overlays-v1` GitHub release; posters live in `overlays/posters/`.
  The site is fully static (GitHub Pages); there is no rendering backend.
- `data/datasets.json` — one row per converted dataset (3,585) plus per-project aggregates.

## Rebuilding the data

```
python3 tools/build_site_data.py            # scans camx_480p, joins the inventory + stats, writes data/datasets.json
```
