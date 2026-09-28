# CAMX Dataset

Project page and data manager: https://camx-anonymous.github.io/

This repository is anonymized for review.

## Pages

- `index.html` — the landing page and dataset browser: hero stats, a morphology → platform tree with search
  over every dataset (cards open a record drawer with the dataset's sample archive and its one-line fetch
  command), and the download section: one bash command per slice (full release, one morphology, or the
  datasets added from the drawer) that fetches and unpacks the one-episode samples from the GitHub releases,
  with JSON export/import of the selection.
- One-episode samples — episode 0 of every dataset as a valid LeRobot-v3 dataset (`meta/`, `data/`, `videos/`
  holding just that episode), one `.tar.gz` per dataset on the `samples-v1-<family>` GitHub releases of this
  repository. Built with `tools/build_samples.py` (cuts the episode out of the packed files, drops every meta
  file that is not `info.json`, `episodes/`, `tasks.parquet`, `stats.json` or `_SUCCESS`, and runs the
  anonymisation pass), uploaded with `tools/publish_samples.py`, and merged into `data/datasets.json` as each
  row's `sample` (`{url, bytes, frames, seconds}`) by `tools/build_site_data.py --attach-samples-only`.
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

One-episode samples (the tree root, the output dir and the scrub list are the `--root`, `--out` and
`$CAMX_SCRUB` defaults; re-running either script only does what is still missing):

```
uv run --with pyarrow python tools/build_samples.py --workers 8   # cuts episode 0 of every dataset, one .tar.gz each
python3 tools/publish_samples.py                                  # uploads them to the samples-v1-<family> releases
python3 tools/build_site_data.py --attach-samples-only             # writes each row's `sample` into data/datasets.json
```

The build ends with an anonymisation pass driven by a local, uncommitted term list (`.claude/scrub.json`, or
`$CAMX_SCRUB`); the build fails if any listed term survives. `--scrub-only` re-runs just that pass over the
existing `data/datasets.json`.
