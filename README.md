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
  served from `overlays/videos/` (tracked, so Pages sends them as `video/mp4`; iOS Safari will not play the
  `application/octet-stream` that GitHub release assets come back as); posters live in `overlays/posters/`. The site is fully static
  (GitHub Pages); there is no rendering backend.
- `data/datasets.json` — one row per converted dataset (3,585) plus per-project aggregates. The browse tree follows
  the source tables of the paper's appendix: the build relabels rows into the paper's embodiment groups (iPhUMI,
  TacUMI, Other research projects; Galaxea, UR5, ARX5 and OpenArm each inside one morphology band) and copies
  `data/pending.json` in as `pending`.
- `data/pending.json` — hand-maintained: every source of the appendix tables that has no converted LeRobot-v3 data
  on the site yet (no sample archive, no validation clip), with the paper's counts (datasets, episodes, frames, hours,
  views, fps) and the table's note letter ([A]–[D]). The tree lists them under their embodiment group without a tick
  box; their cards (a block under the results, opening a record with license and citation) are switched off for now
  by `SHOW_PEND` in `index.html`. Remove an entry once its data is converted and the build picks the rows up.
- `data/sources.json` — the license and the paper(s) of every source dataset, keyed by the source label of the
  rows (`projects` maps a family/project to a more specific entry where one source ships under two licenses,
  e.g. FastUMI vs FastUMI-100K, RH20T configurations 1-5 vs 6-7; `datasets` does the same per row for the
  five lerobot ALOHA repos whose card says Apache-2.0). Hand-maintained; author given names are
  abbreviated to initials. The build checks it (every source has an entry, no forbidden term) and writes
  `data/citations.bib` (CAMX plus every source paper) from it.
- Download gate — every download action (the slice command's Copy / Save .sh, a record's "Copy sample command")
  first opens a compact dialog listing the sources of exactly those samples (name, license chip, short paper
  cite), offers the BibTeX of that set (Copy / Save .bib), and asks the user to agree to cite them and follow
  the licenses. It is asked every time, nothing is remembered; the command block itself is always visible.
  The shortcuts (Full release, one morphology) are handled the same way, since the set is derived from the rows
  of the slice. Each record also shows its License and Cite rows. The generated script carries a three-line
  header that links `data/citations.bib`.

## Rebuilding the data

```
python3 tools/build_site_data.py            # scans camx_480p, joins the inventory + stats, writes data/datasets.json
```

Clips that the shared render tree does not carry (every other project of the training tree, rigs without a
URDF, re-renders) come from `tools/overlay_picks.py`: `render` runs the renderers of the camera-cross-embodiment
checkout (`render_multiview_overlay_video.py` for every camera stream of a dataset, the fisheye bimanual tool for
the DataClaw / GenRobot picks) for a pick table of three episodes per project, `pack` writes
`<project_key>/<slug>/{stitched.mp4,poster.jpg,meta.json}` in the tree's layout, `encode` makes the 360p release
mp4 and the site poster. Point `CAMX_OVERLAYS_EXTRA` at that directory when building.

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
