# CAMX gripper reprojection: reproduce the overlay clips

This folder renders gripper projections from the public CAMX sample episodes. It includes recipes for all
75 projects on the [CAMX dataset website](https://camx-anonymous.github.io/camx-dataset/), plus GenRobot gripper-v4.
The gripper of each dataset (a URDF / CAD model where one exists, a drawn stand-in where none does) is
projected through the sample's camera poses, gripper widths and lens model. Nothing is fitted or learned
at run time. Inputs are `meta/info.json`, `meta/episodes`, `data/*.parquet`, `videos/` and the per-project
recipe in `recipes.json`.

**What this folder cannot reproduce** (details in [Reproduction coverage](#reproduction-coverage)):

* Site clips of episodes other than 0. The public sample archives hold episode 0 (`ep0`) only.
* Seven ep0 clips rendered from reviewed or repaired data that was never exported into the samples.
* The exact pixels of the 109 site clips drawn with the headless Rerun viewer. Same geometry and
  inputs; this folder draws them with the OpenCV renderers, so the shading differs.
* The LEGATO 3x decode upscale and a few cosmetic per-clip flags listed below.

Contents: `reproject.py` (driver), `recipes.json` + `RECIPES.md` (one recipe per `family/project`), `lib/` (the
OpenCV renderers, copied from the CAMX code base), `grippers/` (URDFs and meshes, see `grippers/SOURCES.md`),
`calib/` (lens files), `config/` (viz configs: view order, field of view, trajectory keys), `ASSETS.md` (what each
asset is and where it came from), `download_sample.py` (public sample downloader), `selftest.sh` (sample-tree
smoke test), `tests/` (regression tests), `VALIDATION.json` (the dated coverage audit).

## Quickstart: download and project a public sample

Linux is the tested platform. Python 3.10 or newer is required; no GPU is needed. The virtual environment
takes about 0.9 GB of disk and each sample archive is 1 to 50 MB. Rendering takes seconds to
minutes depending on the clip length, number of camera views and mesh complexity.

```bash
tar xzf reprojection.tar.gz && cd reprojection      # or: cd release/reprojection inside the source checkout
python3 -m venv .venv                               # Debian/Ubuntu: apt-get install python3-venv first
. .venv/bin/activate
python -m pip install -r requirements.txt
ffmpeg -version
ffprobe -version
```

Install FFmpeg if either command is missing: on Ubuntu/Debian, `sudo apt-get install ffmpeg`; on macOS,
`brew install ffmpeg`. FFmpeg must provide the `libx264` encoder and an AV1 decoder (`libdav1d` or `libaom`):
the sample videos are AV1, and pip's OpenCV cannot decode them, so the renderers spawn `ffmpeg` for every
decode and encode. `reproject.py` checks both codecs before rendering and names the missing one.

Download the 1.23 MB UMI cup sample and render it:

```bash
python download_sample.py --dataset umi/umi/cup_in_the_wild --out samples
python reproject.py --dataset samples/umi/umi/cup_in_the_wild --out out --seconds 10
```

Open `out/umi/umi/cup_in_the_wild/ep0/stitched.mp4` to see the gripper projected onto the camera video,
or `poster.png` for a still image (`ep0` = episode 0, the only episode in a public sample). This sample is
about 6.7 seconds long, so the 10-second budget renders all of it; so would the default budget of 45 seconds,
the site's clip length. `render.log` lists the lens and gripper profile used; `meta.json` records the resolved
recipe. No account or dataset repository clone is needed for the public sample downloads.

For a robot with multiple camera views:

```bash
python download_sample.py --dataset aloha/aloha_lerobot/battery --out samples
python reproject.py --dataset samples/aloha/aloha_lerobot/battery --out out --seconds 3
python reproject.py --dataset samples/aloha/aloha_lerobot/battery --out stills --frame 120 --png
```

The single frame is saved as `stills/aloha/aloha_lerobot/battery/ep0/frame000120.png`. A `--png` run into a
directory that already holds a clip keeps that `stitched.mp4`; a separate output directory still keeps the
two runs' `meta.json` apart.

`.venv/`, `samples/` and `out/` (and any other `--out`) are your own folders: delete them when done.

## Render a complete sample gallery in parallel

The release includes the batch renderer and website builder. After installing the
requirements and FFmpeg above, one command downloads the samples, renders them,
and builds a static site:

```bash
python render_gallery.py --out ../sample-gallery --jobs 8
python gallery/serve.py --directory ../sample-gallery --port 8767
```

Open <http://127.0.0.1:8767/>. On a remote machine, forward port 8767 through SSH
or your IDE. To publish the gallery elsewhere, upload the entire `sample-gallery/`
folder to a static host; it has no frontend build step or external asset dependency.
Start the server in a second terminal to watch the gallery fill while rendering.

The default scope is the 301 distinct public samples represented by the website's
307 example clips, covering 75 catalog projects. To render **every public sample**
(4,295 in the audited catalog), add `--scope all`. For a smaller end-to-end check,
use `--scope representatives --seconds 3`. Keep separate output directories for
different scopes. Every sample contains episode 0; this does not supply missing
episodes or reviewed inputs from the earlier website.

`--jobs` controls concurrent datasets. The safe default is 2; start there on an
8–16 GB computer. A machine with 32 CPU cores and sufficient free RAM can run
8–12 workers. Rendering is mostly CPU mesh projection, so GPU encoding alone
will not remove that bottleneck. More workers can slow a shared or memory-limited
machine; measure CPU utilization and memory before increasing it. The batch caps
numeric-library threads at one per worker to avoid nested thread pools.

Rerun the same command to resume. Completed clips are reused only when input
fingerprints, renderer/assets, package versions and settings match and every
output exists with the expected video frame count. Failed or interrupted clips
are retried. Inputs, source URLs and SHA-256 receipts are stored in
`sample-gallery.work/` alongside the site. The gallery updates after each completed
clip and labels CAD/URDF, stand-ins, axes, raw footage and known calibration gaps.
The process returns nonzero if any render fails; per-clip `meta.json`,
`videos/summary.json` and `sample-gallery.work/run.json` record the results.

`export_release.py` is the maintainer's packaging tool and is intentionally not
needed by recipients. `reproject.py`, `render_gallery.py`, all renderers, assets,
recipes and the `gallery/` tools are included in the exported folder/tarball.

## More samples and commands

```bash
# List public samples, optionally filtering by project/name.
python download_sample.py --list --only fastumi

# Render every downloaded sample (default 45-second cap) into its own output tree; keep concurrent renders modest.
python reproject.py --tree samples --out out_tree --jobs 2

# Validate the bundled gripper assets, smoke-test your downloaded samples, run the regression tests.
python lib/check_assets.py
./selftest.sh samples smoke-output
python -m pytest tests -q          # pytest is installed by requirements.txt
```

Each archive preserves `<family>/<project>/<dataset>/{meta,data,videos}`. The downloader obtains URLs
from the website catalog, checks the advertised archive size, and refuses to replace an existing dataset.
You can also use the **sample** download links on the website and unpack their `.tar.gz` archives under
`samples/`. Public samples contain only episode 0; `--episode N` needs a dataset that actually contains N,
and a missing episode lists the ones available.

Clip length and rate: `--seconds S` caps the rendered part of the episode. It defaults to the recipes'
`defaults.max_seconds` (45, the site's cap); `--seconds 0` renders the whole episode. `--fps F` is the output
rate, default `defaults.out_fps` (10); frames are subsampled by `round(fps/F)`, and a recipe may fix its own
`stride` instead. `--frames N` caps the input frames before subsampling. Other options: `--episode N` (default 0),
`--project family/project` (the recipe key; it wins over the key inferred from the path, which must match whole
path segments `family/project/dataset`, then from `repo_id` / `source_dataset` in `info.json`), `--look white|color`
(`white` = the site's opaque light-grey CAD, also for the AgiBot Beta route; `color` = the renderers' tinted parts
with frame labels and the tool-centre axes), `--dry-run` (print the renderer command lines only, shell-quoted so
they can be pasted), `--only substr` (comma-separated alternatives), `--max-per-project N`, `--jobs N`,
`--python <interpreter>`, `--recipes <file>` (an edited copy of `recipes.json`).

## Output layout

    <out>/<family>/<project>/<dataset>/ep<N>/
        stitched.mp4              every rendered view side by side (the renderer's own output)
        stitched.json             the renderer's summary (clip mode only): views in tile order, gripper kind per
                                  side, frames written, output fps, tile widths and height, lens model / source /
                                  fx / fy per view (the AgiBot Beta renderer adds calibration and export ids)
        <view>.mp4                one file per view, cut from stitched.mp4 (e.g. right_main_camera_rgb.mp4)
        poster.png                frame 0 of the clip;  poster_mid.png = the middle frame of the rendered budget
        frame000120.png           (--png mode) the requested frame instead of the clips; route raw writes <view>.png
        render.log                the command line, any `# driver note:` lines, then the renderer's stdout:
                                  per-view lens source, anchor pose, width range; in clip mode its last line
                                  names stitched.png, which the driver renames to poster_mid.png
        meta.json                 see below; `error` when the render failed; `no_overlay` with the reason for route raw
    <out>/summary.json            every meta.json (merged across runs into the same --out, keyed by dataset and
                                  episode) plus the per-project ok / raw / failed counts

`meta.json` keys: `dataset`, `dataset_root`, `episode`, `project`, `project_inferred_from` (`path`, `info`, `--project`
for an explicit override, or `fallback` when no recipe key matched), `route`, `recipe` (the resolved recipe), `note`, `site_renderer` (how the site drew this
project's clip: `opencv`, `rerun` or `raw`; informational), `episode_length`, `fps`, `clip` (seconds, output fps, stride,
source frames), `views`, `command` and `command_shell` (the renderer command, as a list and shell-quoted), `notes`
(driver remarks, e.g. a recipe key the route ignores), `outputs`, `status`, `stdout_tail`, `renderer_summary` (the
`stitched.json` content), `lib_version`, `timestamp`. The AgiBot Beta `render.log` carries only the command and the
`[done]` line; its lens and profile source is `renderer_summary.calib` in `meta.json`.

Site posters are the middle frame of each full clip, whereas `poster.png` is frame 0; use `--frame N --png` to
render a specific frame. For route `raw` the views are cut from the dataset videos with ffmpeg (no overlay) and
`meta.json` says why. A command exits nonzero if any dataset fails; tree runs still attempt the remaining datasets.
Missing or truncated videos and out-of-range frames are reported as failures rather than successful renders.

## Reproduction coverage

The website catalog (audited 2026-10-12, detailed clip/sample mapping and test evidence in
[`VALIDATION.json`](VALIDATION.json)) lists 307 example clips: 288 with a projection and 19 raw companions. All 75
site projects have a recipe, and every catalogued clip dataset has a public sample, but the sample holds episode 0
only. The 288 overlay clips break down as follows (the site render logs were read clip by clip):

| Site overlay clips | Count | Reproducible from the public samples? |
|---|---|---|
| Episode other than 0 | 79 | No. The samples hold `ep0` only. |
| `ep0`, rendered from reviewed or repaired data not in the sample | 7 | No (list below). |
| `ep0`, rendered with the headless Rerun viewer | 52 | Same geometry, inputs and config; different renderer, so the look differs. |
| `ep0`, rendered with the shipped OpenCV renderers | about 150 (71 of them AgiBot Beta) | Yes, almost pixel for pixel. |
| Raw companions (no projection) | 19 (12 of them `ep0`) | The 12 `ep0` ones, as cuts with a different encode. |

**Reviewed or repaired data (7 clips).** `umi/umi_on_legs/tossing` (reviewed gripper widths),
`robotiq/droid_lowres` `TRI_success`, `AUTOLab_success` and `IPRL_success` (reviewed external camera trajectories),
and the three `franka_hand/rh20t_cfg5` clips had unpublished pose repairs at the time of that audit.
The driver now corrects the three audited cfg5 episode-0 sample poses at render time (103.4 mm / 135° TCP-to-mount
transform). It also restores the session-specific wrist poses for the three audited `flexiv/openneo_flexiv` samples;
`align_the_ceramic_bowls` was missing a 31.25° camera-roll correction. Recipe `eef_corrections` match the dataset,
episode and exact legacy pose before applying a repair, preserve corrected or unknown poses, and record applied
corrections in `meta.json`. Sample files remain unchanged; other legacy episodes need corrected input metadata.
The Flexiv correction fixes the main roll error, but the geometric jaw stand-in still misses the visible fingertips
(about 50 px median silhouette endpoint error in the bowl clip). Its linkage motion and camera placement remain uncalibrated.

**Dexora camera geometry is uncalibrated.** All four camera poses and their 70° lens models are priors.
In `articulation` episode 0, the stored poses place both hand frames behind the head camera throughout all
293 frames, despite both hands being visible. The full local export carries the same trajectories as the sample.
The optical prior was applied to a rotated URDF joint frame as though it were the camera body frame. The recorded
head pitch is valid in the published SDK; clamping it to the borrowed URDF limits would introduce another error.
Its axes overlays are diagnostic; calibrated camera mounts and intrinsics are still required.

**ManipForce battery CAD projection.** The supplied assembly is rooted at TCP, matching the recorded state.
The marker-to-TCP offset is applied to the CAD frame only. A fit to the 12 mm white label recess gives 0.93 px
held-out corner RMS with nominal intrinsics. The 12.571 mm opening is inferred from this video and is explicitly
labelled fixed. A `sample_overrides` rule requires the audited episode, source-video hash and legacy EEF pose;
other recordings keep raw playback. The retarget preserves world TCP but changes the optical-camera motion from
the legacy training export, which placed the camera at TCP. No training or sample data is rewritten.

**Bridge wrist candidate.** The audited episode-0 sample has a guarded own-wrist CAD projection with a fitted lens
and camera mount. The recorded opening is remapped to the official controller limits (48 mm full pad gap).
Held-out fingertip errors are 9.7 px median / 21.2 px p90; opening/closing timing remains imperfect. This view does
not validate world camera motion: the legacy converter interpreted Cartesian pose channels as arm joints.
The own-wrist overlay cancels world pose, leaves input files unchanged, and is labelled as a candidate.

**Rerun renders (109 of the 288 overlay clips, 52 of them `ep0`).** These are the current clips of `agibot_world_2026`,
every ALOHA project except `openneo_arx5*`, `rh20t_cfg1-7`, `fmb`, `molmoact`, `iphumi` except `muse`, `openarm`,
`realsource`, `droid`, `roboset`, `dobbe` and `rby1/modpack` (the `site renderer` column of `RECIPES.md` marks them).
They used the same poses, intrinsics, configs and gripper URDFs as the recipes here; the Rerun viewer shades meshes
smoothly and about 20 grey levels lighter, while this release draws flat light grey with hard facets. The RB-Y1 clips
were Rerun renders with `config/rby1_modpack.json`, not a separate tool: this release renders the same views and
placement, and in addition draws the head cameras as KB4 fisheye (the coefficients in `info.json`) where the Rerun
clip used a plain pinhole.

**OpenCV renders (about 150 `ep0` clips).** Rendered with the renderers in `lib/`, the same code as here. Verified
against the site posters for `openneo_aloha`, `openneo_flexiv`, `fastumi`, `genrobot`, `dataclaw` and `droid_lowres`:
masked pixel differences of 5 to 29 grey levels, versus 55 to 100 against the raw frame.

**Recovered commands.** The site commands of `tamen`, `freetacman`, `muse`, `legato`, `aloha_lerobot_mobile`,
`mint_xarm` and `molmoact` were recovered from the source render logs, and the recipes encode them: TAMEn's fitted
tool-centre poses, FreeTacMan's multiview route, MuSe's `umift` profile, LEGATO's tile height 384. LEGATO additionally
decoded its frames at a 3x upscale, which no recipe field expresses. `molmoact` has no command on disk, but its
per-episode intrinsics drive both tools. Bridge V2's sample is the same side2 export the site used; the site clip is
episode 6 and the sample holds episode 0, nothing else differs.

**Known small differences.** `aloha/robomind`'s `cobot magic v2` jaw map was widened after the site render (a7dcfaf),
so its jaws open wider here. Two `genrobot/gripper_v4` site clips used `--cross off` and the `xhand/dexora` clips a
stride of 3 on 20 fps data; the raw-route cuts use a faster encode than the site's. Site posters are the clip midpoint;
`poster.png` is frame 0 and `poster_mid.png` the middle of the rendered budget.

Validation runs used fresh Python 3.10 and 3.12 environments. One public sample from each of the 75 projects was
downloaded and rendered for 0.3 seconds: 71 overlays, 4 intentionally raw-only, 0 failures. The two quickstart examples
were also rendered for their documented durations, plus the ALOHA frame-120 PNG, and the regression tests pass. This
is runtime coverage, not a full render of all clips; it does not measure calibration accuracy.

## How a recipe is chosen, and how to override it

`recipes.json` maps `family/project` to a recipe (`RECIPES.md` is the human-readable table). Fields:

* `route`: `multiview` (every camera stream, `lib/render_multiview_overlay_video.py`), `bimanual_fisheye`
  (right main | left main through a Kannala-Brandt / EUCM lens, `lib/render_bimanual_urdf_overlay_video.py`),
  `agibot_beta` (the CTAG2F120 finger CAD, `lib/render_agibot_beta_overlay_video.py`), or `raw`.
* `config` / `config_by_rig` / `dataset_config`: the viz config. `config_by_rig` is a list of
  `{"when": {...}, "config": ..., "profile": ...}` rules evaluated against `info.json` (`n_videos` = number of video
  features, `robot_type_contains`, `dataset_contains`, `has_feature`, `has_view_prefix`, `left_gripper_model`,
  `right_gripper_model`); the first match wins. `dataset_config` is a per-dataset file pattern
  (`config/site/<key>/{dataset}.json`) used when it exists.
* `profile`: `auto` (multiview first uses the episode's `<side>_gripper_variant`, then `<side>_gripper_model`: a special
  kind such as `umi`, `genrobot`, `dataclaw`, else the `gripper_registry` entry, else the generic primitive), `primitive`,
  `axes`, `registry:<model>`, or one of the special kinds. `model_override` / `standin` replace the dataset's model
  string with another registry profile (the `standin.note` says what stands in for what).
* `calib`: lens file per view (`main` = every `*_main_camera_rgb`, `all` = every view), `file.json:crop|stretch`
  = how the calibration basis is mapped onto the stored video (centred crop to the video aspect, or per-axis
  stretch). `calib_episode` / `calib_device` are patterns for per-episode / per-device lens files
  (`{ds}`, `{ep}`, `{side}`, `{device}`; the DataClaw device id is the dataset name's `dag...` prefix).
* `hfov` (per-view horizontal FOV in degrees), `eef` (a constant tool-centre pose in the main camera,
  `x,y,z,qw,qx,qy,qz`, used when the release has none), `eef_tcp` (the renderer's TCP frame expressed in the
  dataset's eef frame, composed per episode with the dataset's own `<side>_eef_pose_in_main`), `extra`
  (renderer arguments passed through), `own_only` (each view draws its own gripper only: the two hands of the
  rig are not in one world frame), `views` (tile order; otherwise right main, left main, the other main cameras,
  then the rest, capped at `defaults.max_views`), `tile_height`, `stride`, `site_renderer` (informational),
  `no_overlay` (reason; forces route `raw`), `overlay_mode`, `note`.

To override: edit the recipe in `recipes.json`, or run the renderer yourself with the command line printed by
`--dry-run` (or stored in `meta.json` as `command_shell`) and change its arguments; every renderer prints `--help`.
On the multiview route any registry key works as `--profile registry:<model>` and `--profile primitive` draws the
stand-in for any rig; the bimanual renderer accepts only its named kinds.

## The projection chain

Notation: `pose7 = [x, y, z, qw, qx, qy, qz]` is a rigid transform; `T(pose7)` its 4x4 matrix. Every camera
pose is the pose of the camera's **optical** frame in the dataset's world frame, OpenCV axes (x right, y down,
z forward). Per frame `i` the dataset gives `W_T_cam[i] = T(observation.state.<cam>_main_camera_trajectory_xyz_wxyz[i])`
and the width `w[i] = observation.state.<side>_gripper_width_m[i]`; attached and stereo cameras add the static
`<cam>_pose_in_main_xyz_wxyz` offset: `W_T_view = W_T_wrist · T(view_pose_in_main)`.

**Gripper in its own wrist camera.** The gripper is rigid to its camera, so the world cancels and the overlay
depends only on the calibration, the URDF and the width:

* eef-anchored profiles (the dataset calibrates the tool-centre / flange pose in the main camera):
  `opt_T_root = T(<side>_eef_pose_in_main) · [R(root_rpy) | root_xyz]`, the bracket being the registry
  profile's root offset (TCP -> URDF root);
* camera-mounted profiles (the URDF carries the camera link): `opt_T_root = inv( FK(root -> mount) · [R(opt_rpy) | opt_t] )`,
  the bracket being the optical frame in the mount link (`optical_*_in_mount_link` of the registry).

`FK` is the URDF forward kinematics at the joint values `width_to_joints(w[i])` of the profile (a width-to-angle
map per gripper; the mesh of every link is transformed by `FK(root -> link)`).

**Gripper in any other camera** (the other wrist, head, third-person, stereo eye):
`cam_T_root = inv(W_T_view[i]) · W_T_wrist[i] · opt_T_root`.

**Lens.** A point `p = (X, Y, Z)` in the camera frame, `x = X/Z`, `y = Y/Z`, `r = sqrt(x^2 + y^2)`, `theta = atan(r)`:

* pinhole: `u = fx · x + cx`, `v = fy · y + cy` (plumb-bob `k1..k5` through `cv2.projectPoints` when the lens file carries them);
* Kannala-Brandt (KB4, OpenCV `fisheye`, ROS `equidistant`):
  `theta_d = theta · (1 + k1 theta^2 + k2 theta^4 + k3 theta^6 + k4 theta^8)`, `u = fx · theta_d · x / r + cx`,
  `v = fy · theta_d · y / r + cy`; points beyond `theta_max` (default 100 deg) are dropped;
* EUCM (alpha, beta): `d = sqrt(beta (X^2 + Y^2) + Z^2)`, `den = alpha · d + (1 - alpha) · Z`,
  `u = fx · X / den + cx`, `v = fy · Y / den + cy`.

Triangles are filled back to front (painter's order over the meshes of both sides), optionally occluded by the
profile's own occluder links, and blended onto the frame (`--alpha`; 1.0 = opaque, the site look).

**Where the intrinsics come from** (first match wins, per view): a `calib` entry of the recipe (lens file, mapped
to the video with `crop` / `stretch`); the episode row's `videos/<key>/intrinsics_fx_fy_cx_cy` in `meta/episodes`
(pinhole in the stored-video basis; with `<cam>_distortion_k1_k2_k3_k4` from `info.json` when the camera is
flagged fisheye); the viz config's `hfov_deg` / `vfov_deg` / `cx_rel` / `cy_rel` (a fisheye-flagged camera gets
an equidistant model with zero distortion); the recipe's `hfov`. `render.log` names the source per view.

## Assumptions and stand-ins carried by the recipes

See `RECIPES.md` for the per-project table; its notes are copied into each clip's `meta.json`. In summary:

* **Lens models that are assumed or borrowed.** Every UMI-family handheld rig (UMI, FastUMI, Data Scaling Laws, ManiWAV,
  MV-UMI, Touch-in-the-Wild, UMI-on-Legs, ViTaMIn, HuMI, exUMI) is drawn through one GoPro Hero 9/10 + Max Lens Mod
  calibration (`calib/gopro_hero9_maxlens_2_7k_umi*.json`, centre-cropped to the square video); ViTaMIn-B assumes the
  webcam-mode crop chain. The OpenNeoData wrists use assumed D405 / fx-306 pinhole files. LEGATO (T265), FreeTacMan and
  TAMEn (HBVCAM) use nominal equidistant models; AetheRock reads its 190-degree image circle as equidistant. Several viz
  configs carry horizontal-FOV priors instead of a calibration (openneo 70, dexora 70, mint_xarm 56-60, molmoact 70,
  fmb 72.6/57.7). GenRobot 10Kh episodes without a per-episode `camera_info` file fall back to a session mean.
* **Tool-centre poses that are candidates, not calibrations.** DataClaw (the converter-notes candidate, pad centre
  0.12 m ahead of the lens), AetheRock (picked on the video), Vista-UMI (the UMI-Benchmark constant for both hands),
  TAMEn (the site's fitted constants), the OpenNeoData Flexiv / UR TCP remaps, the RoboMIND-UR5 static cameras.
* **Stand-ins where the release has no CAD.** Rigs without a URDF get a primitive: a jaw bar spanning the recorded
  width, pads, the tool-centre axes (DataClaw, HiFi-UMI, UMI-Benchmark, Vista-UMI, FreeTacMan, TAMEn, AetheRock, the
  OpenNeoData rigs). OpenNeo ALOHA draws the stock PiPER drive with datasheet-envelope InTac fins; AIST draws ALOHA-2
  fingers; AgiBot World Beta draws only the CTAG2F120 distal fingers and short links (a fitted partial CAD). Dexora
  draws coordinate frames only (`axes`).
* **Raw playback without a calibrated projection.** DexWild (no palm-camera intrinsics or hand transform) and DexUMI
  (no Inspire hand model; the XHAND1 CAD does not land on the replayed hand). Bridge V2 retains raw playback except
  for the guarded wrist candidate above. ManipForce retains raw playback except for the guarded battery-sample CAD fit above;
  its second camera remains uncalibrated.
* **Camera overrides.** OpenNeo ALOHA per-dataset configs carry `static_pose_xyz_wxyz` and
  `retarget_camera_in_eef`; the multiview renderer applies the static head pose and wrist mount transforms while
  preserving the gripper's world trajectory. They do not change the downloaded sample files.
* **Not reproduced exactly.** The 7 reviewed-data clips, the Rerun look of 109 clips and the small differences listed
  under [Reproduction coverage](#reproduction-coverage). Recipes marked "recovered from the source render log" in `RECIPES.md` carry
  the recovered site settings; their notes say which values are nominal.
* **Shared world frames.** Bimanual handheld rigs whose two hands are not tracked in one world frame (Vista-UMI,
  FastUMI-100K dual, OpenNeo UMI) draw each gripper in its own wrist view only (`own_only`).

## Minimal reimplementation

`lib/check_iphumi_urdf_overlay.py` (about 260 lines) is the smallest end-to-end instance of the chain above:
one frame, one wrist camera, pinhole intrinsics from `meta/episodes`, the URDF anchored at
`<side>_eef_pose_in_main` with the registry root offset, FK at the recorded width, mesh surface points projected and
drawn as dots, plus reference crosses at the tool centre and fingertips. `lib/minimal_pinhole_example.py` (about 140
lines) is the same chain for any camera of the episode (own wrist, attached, third-person through the two world
trajectories) and both anchor kinds, using the registry only for the profile's offsets and width-to-joint map; it
sets `--urdf-root` to this folder's `grippers/` by default. Run both on an iPhUMI sample, from this folder:

```bash
python download_sample.py --dataset iphumi/gated_memory_policy/pick_and_place_back_correction_all --out samples
DS=samples/iphumi/gated_memory_policy/pick_and_place_back_correction_all
python lib/check_iphumi_urdf_overlay.py --dataset-root $DS --episode 0 --frame 0 --side right --samples 600 --output check.png
python lib/minimal_pinhole_example.py  --dataset-root $DS --episode 0 --frame 0 --side right --samples 600 --out minimal.png
```

What "matches" means here: both tools use the same intrinsics (`K = 465.0, 465.0, 318.7, 240.5`), the same anchor
and the same width (85 mm), so their dots land on the same two fingers. Measured on this frame (dots only, the
checker's crosses excluded): the dot-cloud centroids are 8 px apart (7 px for the left finger, 4 px for the right),
and the masks agree with an IoU of 0.66 after a 3 px dilation. Running either tool twice gives the same spread
(centroids 2 to 15 px apart, dilated IoU 0.63 to 0.65), because `trimesh.sample` draws the surface points at random
in these unseeded commands; exact-mask IoU is about 0.15 between runs of the same tool. The minimal example accepts
`--seed 0` for repeatable surface sampling; the checker has no seed flag. The checker also prints the tool-centre and
fingertip image coordinates (`[ref]` lines) for a numeric check.
Start from one of these to port the projection to another renderer; `--help` lists the overrides (intrinsics, width,
root offsets, profile).

## Licensing

**TODO before publication: choose and add a licence file.** No project-level licence file is included in this
checkout or standalone export, and the maintainers must supply the intended code licence before distributing it. The
gripper URDFs and meshes come from their vendors and research projects; available provenance and licence information
is listed in `grippers/SOURCES.md`. The sample episodes retain their source datasets' licences (see each sample's
`info.json`).
