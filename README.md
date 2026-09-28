# CAMX Dataset

Project page and data manager: https://camx-anonymous.github.io/

This repository is anonymized for review.

## Pages

- `index.html` — the landing page and dataset browser: hero stats, a morphology → platform tree with search
  over every dataset (cards open a record drawer with the per-dataset `hf` command), and the download section:
  one command per slice (full release, one morphology, or the datasets added from the drawer) as `hf` CLI /
  Python / bash / paths, with JSON export/import of the selection. The default scope fetches one sample episode
  per dataset: `meta/` plus the first packed data and video file of each view, which hold episode 0; a toggle
  switches to whole dataset directories.
- `overlays/` — camera-projection validation clips, a few example episodes per project: the gripper URDF
  (or, where no URDF is released, a primitive stand-in: hinged fingers that follow the recorded jaw width plus
  the tool-centre frame as RGB = xyz axes) projected through each dataset's own poses and intrinsics. Clips are
  served from the `overlays-v1` GitHub release; posters live in `overlays/posters/`. The site is fully static
  (GitHub Pages); there is no rendering backend.
- `data/datasets.json` — one row per converted dataset (3,585) plus per-project aggregates.

## Rebuilding the data

```
python3 tools/build_site_data.py            # scans camx_480p, joins the inventory + stats, writes data/datasets.json
```

Clips that the shared render tree does not carry (rigs without a URDF, re-renders) come from
`tools/overlay_picks.py`: `render` runs the renderer of the camera-cross-embodiment checkout for a fixed pick
table, `pack` writes `<project_key>/<slug>/{stitched.mp4,poster.jpg,meta.json}` in the tree's layout, `encode`
makes the 360p release mp4 and the site poster. Point `CAMX_OVERLAYS_EXTRA` at that directory when building.

The build ends with an anonymisation pass driven by a local, uncommitted term list (`.claude/scrub.json`, or
`$CAMX_SCRUB`); the build fails if any listed term survives. `--scrub-only` re-runs just that pass over the
existing `data/datasets.json`.
