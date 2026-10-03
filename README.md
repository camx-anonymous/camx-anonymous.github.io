# CAMX Dataset

Project page and data manager: https://camx-anonymous.github.io/

This repository is anonymized for review.

## Pages

- `index.html` — the landing page and dataset browser: hero stats, a morphology → platform tree
  over every dataset (each row shows its project count and hours, "13 projects · 434 h"; a project row shows its
  task count, "34 tasks · 209 h", where each of its datasets holds one task, and its dataset count, "26 datasets · 209 h",
  where any holds several; cards open a record drawer with the dataset's sample archive and its one-line fetch
  command), and the download section: two panes per slice (full release, one morphology, or the
  datasets added from the drawer). Left, one bash command that fetches and unpacks the one-episode samples
  from the GitHub releases; right, the BibTeX of that slice (CAMX plus one entry per source paper, with
  Copy / Save .bib). JSON export of the selection.
- One-episode samples — episode 0 of every dataset as a valid LeRobot-v3 dataset (`meta/`, `data/`, `videos/`
  holding just that episode), one `.tar.gz` per dataset on the `samples-v1-<family>` GitHub releases of this
  repository. Built with `tools/build_samples.py` (cuts the episode out of the packed files, drops every meta
  file that is not `info.json`, `episodes/`, `tasks.parquet`, `stats.json` or `_SUCCESS`, and runs the
  anonymisation pass), uploaded with `tools/publish_samples.py`, and merged into `data/datasets.json` as each
  row's `sample` (`{url, bytes, frames, seconds}`) by `tools/build_site_data.py --attach-samples-only`.
- `overlays/` — camera-projection example clips, a few episodes per project: the gripper URDF as the opaque
  light-grey CAD mesh of the headless Rerun viewer (the look of the curation pages; fisheye rigs, which that viewer
  cannot draw through, go through the OpenCV fisheye renderer with the same grey, `tools/white_overlay.py`), or,
  where no URDF is released, a primitive stand-in: hinged fingers that follow the recorded jaw width plus
  the tool-centre frame as RGB = xyz axes; the OpenNeoData rigs draw the stock PiPER / ARX X5 / UMI gripper CAD as
  a stand-in (`standin` on the clip record). Everything is projected through each dataset's own poses and intrinsics. Clips are
  served from `overlays/videos/` (tracked, so Pages sends them as `video/mp4`; iOS Safari will not play the
  `application/octet-stream` that GitHub release assets come back as); posters live in `overlays/posters/`. The site is fully static
  (GitHub Pages); there is no rendering backend.
- `overlays/raw/` — the raw companion of every example clip (`<key>__<slug>.mp4` + `.jpg` poster): the same episode,
  camera views, tile order, frame sampling and frame size, with nothing drawn on it (`tools/raw_clips.py`). The
  dataset cards of the landing page show only the raw poster. Clicking a card opens the dataset record and, beside
  it (above it on a phone), a comparison viewer that plays the raw clip next to the overlay clip in step; picking one
  camera view crops both clips to that tile and shows them side by side. Under the clips the viewer shows the caption
  of the frame on screen: each clip's `task` in `data/datasets.json`, or, for an episode annotated per sub-task whose
  caption changes while the clip plays, its `captions` track (`[[start second, caption], ...]`). The build reads both
  from the dataset's current data (the episode's per-frame `task_index` through `meta/tasks.parquet`), the same
  source as the record's Caption row, so the viewer, the overlays page and the record always agree; the render
  tree's `meta.json` task string is a snapshot from render time (it goes stale when an annotation bank is
  re-expanded) and only stands in when the dataset cannot be read. A caption with alternate wordings (the datasets'
  `||`-joined language annotations, 2-25 per task) gets an "augmented ‹ 1 / n ›" stepper through all its wordings.
- `data/captions.json` — the language annotations of every dataset for the Caption row of its record, keyed by row
  id: `{n: instructions in meta/tasks.parquet, tasks: [the first 3 by task_index, wordings '||'-joined], name?: the
  task group of info.json task_name (AgiBot), shown as the headline over its sub-task labels}`. The row shows the
  first instruction (or the group) with the same augmented stepper, then the count of the others with the
  next ones as examples. Its own file, fetched when the first record opens: the task strings of all datasets run to
  13 MB (DROID lists every episode's instruction), so only the first three per dataset are kept. The build merges
  into the existing file: a row whose dataset is not under `--root` keeps its entry (so an incremental build against
  a partial tree drops nothing), ids no longer in `datasets.json` go.
- Task mix — most datasets are one task each, but the DROID lab splits, BiPlay, RoboCOIN and FMB hold several tasks
  (one caption per episode, differing between episodes), and AgiBot World, Galaxea and MolmoAct hold one task annotated
  per sub-task (several captions per episode). The build's `--tasks-only` pass reads every episode's `tasks` list from
  `meta/episodes` and writes `tm` on such rows: `{kind: mixed | steps, eps, per_ep, n_task, n_step?, skills: [[class, n]],
  top: [[caption, n]]}` (skill classes by the first verb of the caption, the taxonomy of the project histograms; the four
  most frequent captions). The card shows the kind as a tag on its poster ("3.8k tasks · mixed", "1 task · sub-task
  captions"), the record a Task mix row (the account, a stacked skill bar with legend, the top captions). Rows whose
  `info.json` carries a `task_name` (AgiBot World, opaque numeric ids) get `title`, shown over the id on the card and
  the record.
- `data/datasets.json` — one row per converted dataset (3,585) plus per-project aggregates. The browse tree follows
  the source tables of the paper's appendix: the build relabels rows into the paper's embodiment groups (iPhUMI,
  TacUMI, Other research projects; Galaxea, UR5, ARX5 and OpenArm each inside one morphology band) and copies
  `data/pending.json` in as `pending`.
- `data/pending.json` — hand-maintained: every source of the appendix tables that has no converted LeRobot-v3 data
  on the site yet (no sample archive, no example clip), with the paper's counts (datasets, episodes, frames, hours,
  views, fps) and the table's note letter ([A]–[D]). The hero stats and the footer quote the paper: the
  totals of its two appendix tables (episodes, hours, datasets, sources, platforms), kept by hand in the `paper` block
  of this file and copied to `totals.paper`. The build warns when the site's own sums (converted + these entries)
  differ from them; the download slices keep counting converted datasets only. The tree leaves them out:
  it shows only sources with converted data and a stated license (`inTree` in `index.html`), and its project, task
  and hour counts follow the rows shown. Their cards (a block under the results, opening a record with license and
  citation) are switched off for now by `SHOW_PEND` in `index.html`. Remove an entry once its data is converted and
  the build picks the rows up.
- `data/sources.json` — the license and the paper(s) of every source dataset, keyed by the source label of the
  rows (`projects` maps a family/project to a more specific entry where one source ships under two licenses,
  e.g. FastUMI vs FastUMI-100K, RH20T configurations 1-5 vs 6-7; `datasets` does the same per row for the
  five lerobot ALOHA repos whose card says Apache-2.0). Hand-maintained; author given names are
  abbreviated to initials. The build checks it (every source has an entry, no forbidden term) and writes
  `data/citations.bib` (every source paper) from it.
- Download gate — every download action (the slice command's Copy / Save .sh, a record's "Copy sample command")
  first opens a compact dialog listing the sources of exactly those samples (name, license chip, short paper
  cite), offers the BibTeX of that set (Copy / Save .bib), and asks the user to agree to cite them and follow
  the licenses. It is asked every time, nothing is remembered; the command block and the BibTeX pane beside it
  are always visible (citing is never gated).
  The shortcuts (All morphologies, one morphology) are handled the same way, since the set is derived from the rows
  of the slice. Each record also shows its License and Cite rows, and every source row of the browse tree carries
  a line with its paper ("(Chi et al. 2024)", linking to arXiv where there is one) and its license chip. Every license
  chip links to the page that states the license (`license.repo` in `sources.json`: the dataset's Hugging Face /
  ModelScope repository, else the project's GitHub repository, else the UMI Data Initiative listing); the License row
  of a record adds the license text and the source page. The
  generated script carries a three-line header that links `data/citations.bib`.

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

`tools/rerun_clips.py` re-renders the clips of `data/datasets.json` in the curation look, on a machine with the
camx_480p tree, the curation tree and the camera-cross-embodiment checkout (`plan` prints each clip's route: `reuse`
a current headless-Rerun export of the curation tree, `rerun` headless Rerun through `lerobot_rerun_viz.py` +
`mv_site/record_views.py`, `fisheye` the OpenCV renderer through `tools/white_overlay.py`, also Vista-UMI with the UMI-Benchmark stand-in, lens and tool-point calibration (same FastUMI Pro device), `multiview` the multi-view
renderer through `tools/white_multiview.py` with the arguments of `tools/overlay_picks.py`, for rigs the headless viewer cannot do:
pinhole rigs without a gripper CAD (primitive stand-in: the OpenNeoData Flexiv / UR / ARX X5 / UMI rigs; RH20T cfg1-3 take the `rerun` route since 2026-10-03, with the vendors' AG-95 / WSG-50 URDFs of `grippers/dh_ag95` and `grippers/wsg50`), fisheye rigs
with their own lens file (UMI-3D, AetheRock, HiFi-UMI, GenRobot V4), RoboMIND UR5 and the 180p DROID twin; `MULTIVIEW` in the script
lists them, and `CAMX_VIZ_MV` names a camera-cross-embodiment checkout that carries that renderer and the lens files; Bimanual rigs whose two hands are not in one world frame (`OWN_ONLY`: Vista-UMI, FastUMI-100K dual-arm, OpenNeoData UMI; `WORLD_FRAME_NOTES` in `tools/build_site_data.py` puts the reason on the dataset record and the detail panel) draw each view's own gripper only (`--cross off` / `--own-only`), and their clip records carry `own_only`. `keep` untouched:
datasets not in the local tree). `render` writes the clip tree
(`<key>/<slug>/{stitched.mp4,meta.json,DONE.json,poster.jpg}`, 2 Rerun + 3 OpenCV clips in parallel, pausing while
the user slice's memory pressure is high), `encode` the 360p site mp4 + poster, `attach` the clip records
(views, grippers, mode, seconds, bytes, caption track):

```
PY=~/miniforge3/envs/iphumi/bin/python   # rerun, pyarrow, cv2
$PY tools/rerun_clips.py plan && $PY tools/rerun_clips.py render && $PY tools/rerun_clips.py encode && $PY tools/rerun_clips.py attach
```

After any change to `overlays/videos/`, refresh the raw companions (it reads each overlay clip's size, frame count
and frame rate back and cuts the same frames from the dataset's own videos; only stale or missing clips are redone):

```
uv run --with pyarrow python tools/raw_clips.py      # overlays/raw/<key>__<slug>.{mp4,jpg}
```

The captions (each clip's `captions` track, and `data/captions.json` for the records) are read in the same build
(pyarrow needed; without it they are left out) and can be refreshed alone, against any `camx_480p` tree:

```
uv run --with pyarrow python tools/build_site_data.py --captions-only --root /data/camx_480p
```

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
