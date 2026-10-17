# Public-sample reprojection release and gallery — 2026-10-13

The exported code can render the available public sample episodes and generate a
portable video gallery. It cannot recreate every earlier website clip exactly:
the sample archives contain episode 0 only, some reviewed poses were never
published in those archives, and the released OpenCV renderer differs visually
from the earlier Rerun renderer. A successful render does not establish camera
calibration accuracy.

**Completed: 301/301 samples, zero failures**, with 282 projected clips and 19
raw-only clips. The 12-worker batch finished in 2,204.88 seconds (36 minutes,
45 seconds), reusing seven clips completed before the parallel run. The site
contains 301 stitched videos and 711 individual camera videos, approximately
2.30 hours of distinct stitched footage. All **1,012 MP4s** passed full decoding,
expected-frame-count, frame-rate and dimension checks; no output was missing.

## Scope and coverage

The frozen public catalog has 4,336 datasets, of which 4,295 have sample download
links. The default gallery selection comprises the **301 distinct public sample
datasets represented by the website's 307 example clips**, covering all 75 catalog
projects and 76 recipe keys, including the GenRobot gripper-v4 alias. This run uses
episode 0, at most 45 seconds per sample, the recipe frame strides, and opaque
grey overlays. These 301 archives total 1,898,492,583 bytes.

| Projection available in the release | Samples |
| --- | ---: |
| URDF mesh | 169 |
| CAD mesh | 71 |
| Geometric stand-in | 38 |
| Coordinate axes | 4 |
| Raw footage only | 19 |

Thus **240 samples have CAD/URDF projections**. The gallery labels every other
mode explicitly. Raw-only projects are DexUMI, DexWild, ManipForce and Bridge V2.
Known input/calibration differences are shown in the player, including the
approximately 10 cm / 135 degree RH20T cfg5 mismatch and unpublished reviewed
inputs for UMI-on-legs tossing and three DROID-lowres samples. The dated
[previous review](release_reprojection_review_1012.md) and shipped README describe
the original-site reproduction limits.

`--scope all` selects all 4,295 downloadable samples; that full catalog was not
rendered in this run. `--scope representatives` selects one sample per catalog
project. Separate output directories are recommended for different scopes.

## Changes and release workflow

The on-disk export at the beginning of this review was stale. A fresh export
initially exposed an anonymity-scan failure in an OpenArm configuration comment;
the personal attribution was removed without changing calibration values. A test
that inspected the wrong dry-run output line was corrected.

The maintainer exporter now bundles `render_gallery.py`, the `gallery/` tools,
their regression tests, and Pillow for gallery thumbnails. Recipients need the
extracted release, its Python dependencies and FFmpeg; they do not need this
repository, the maintainer exporter, a GPU or a frontend build system.

The runner downloads and fingerprints inputs, limits numeric-library threads to
one per worker, renders independent datasets concurrently, and updates the site
after each result. Resume requires matching input, renderer, asset, package and
setting fingerprints, plus complete outputs with the expected frame counts. A
kernel lock prevents two runs from writing the same site. Failed/interrupted
clips are retried. Restoring an input after a failed integrity check preserves
the ability to resume. Thumbnails refresh when a clip is rendered again.

The export skill's current default target is the separate
`cosmos-cam-uva/camx_visualization` checkout. This review explicitly used
`--out release/reprojection`; it did not publish or commit the generated export.
The skill requires `CAMX_SMOKE_DATASETS` for both smoke routes. Its bare
`selftest.sh` invocation still assumes a prepared sample tree; the public README
documents the explicit sample/output arguments and the complete gallery command.
The user requested parallel rendering, so the batch used 12 workers after CPU
and memory checks, superseding the skill's conservative two-worker guidance for
this run. The portable command retains a safe default of two workers.

On this 32-logical-CPU machine, the measured workload was CPU mesh projection,
with ample memory available. Dense multi-camera jobs take several minutes;
lighter samples finish in seconds. More workers are useful while CPU and memory
headroom remain; GPU encoding alone does not remove the projection bottleneck.
The running batch uses an isolated exported snapshot, so concurrent checkout
edits cannot change its renderers mid-run.
Its renderer/assets/dependency fingerprint matches the final exported release:
`cfa46297776146b062d8bd71af40a7a2edd37ce3db0411cfe38cc51831a189f8`.

## Validation

- A fresh Python 3.12 environment installed the release requirements.
- Export checks passed: 11 library files copied verbatim; 280 asset references
  resolved, zero missing/outside assets; zero anonymity-scan hits. The one known
  missing RB-Y1 material-file warning uses the renderer's flat colours.
- Both export smoke routes passed: XArm/MINT `pick_bread` (multiview) and
  FastUMI dual-arm `add_rice_to_rice_cooker` (bimanual fisheye).
- The complete exported regression suite passed: **68 passed, 3 skipped**. The
  skips are duplicate project-inference checks covered in the driver tests.
- The portable CLI downloaded and rendered both routes from a reduced catalog;
  its second invocation reused both clips with zero renders. The selection,
  signature invalidation, incomplete-output, output-lock and input-restoration
  cases have regression coverage.
- Browser checks passed for search, filters, pagination, mobile width, deep
  links, MP4 playback, seeking, individual camera views and HTTP byte ranges;
  no JavaScript console errors were recorded.
- Final browser verification confirmed all 301 clips ready, 75 projects, 240
  CAD/URDF samples, playback, mobile layout, the renderer archive download and
  the frozen catalog. Final desktop/mobile/player screenshots are in `work/`.
- Full MP4 validation passed for every stitched and per-camera file. Frame
  counts match exactly; the FPS tolerance is 0.0001 to allow the renderer's
  decimal rounding of fractional DROID rates.
- The original dated `VALIDATION.json` remains historical evidence. New run
  results are recorded in the gallery, its per-clip metadata and the evidence
  paths below.

## Artifacts and commands

- Gallery: <http://127.0.0.1:8767/>. Forward port 8767 for access from a remote
  desktop. The server is local; no public deployment was performed.
- Site directory: `[local path]
  Copy the entire directory to a static host to publish it.
- Release archive: `release/reprojection.tar.gz`, 32,033,386 bytes;
  SHA-256 `352faa6db7743b2da9e48ab3033e4223bb18dc794532b02c82479512d4039199`.
  A copy is stored in `[local path]
  Download through the gallery server at
  <http://127.0.0.1:8767/reprojection.tar.gz>.
- Manifest: 453 files, approximately 105.1 MB unpacked, from commit
  `72b8b2df6971dc6fc618ab87f976c56594ab50b3` plus the working-tree gallery changes
  recorded in `ASSETS.md`. Compared with the pre-review export: **12 added,
  0 removed, 35 changed**. Full old/new file hashes are in
  `[local path]
- Recipe consistency check passed; no recipe regeneration was needed during
  this review.
- Smoke outputs:
  `release/reprojection.smoke/pick_bread/xarm/mint_xarm/pick_bread/ep0/` and
  `release/reprojection.smoke/add_rice_to_rice_cooker/fastumi/fastumi_100k_dual_arm/add_rice_to_rice_cooker/ep0/`.
- Logs, frozen catalog, dependency versions, input receipts, browser evidence
  and video validation are under
  `[local path]

After extracting the archive, run inside `reprojection/`:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
ffmpeg -version
ffprobe -version
python render_gallery.py --out ../sample-gallery --jobs 12
python gallery/serve.py --directory ../sample-gallery --port 8767
```

Install system FFmpeg if absent; it needs `libx264` and an AV1 decoder. Use fewer
workers on smaller machines. Start the server in a second terminal to watch
progress. Rerun the render command to resume. Add `--scope all` for the full
public catalog, `--seconds 0` for whole episodes, or `--catalog` pointing to the
site's `evidence/catalog.json` to reproduce this frozen selection.

No commit was made by this review. Source changes belong in
`camx/visualization/release_src/`, `camx/visualization/release_gallery/`, the
OpenArm configuration comment, and this report; generated exports stay outside
this checkout's tracked files. Suggested commit message:
`Add resumable parallel public-sample projection gallery to release`.
