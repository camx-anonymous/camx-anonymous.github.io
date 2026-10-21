# TAMEN reviewed overlays

The three public TAMEN clips use the `tamen` Rerun profile and the reviewed
`config/tamen_early_recordings.json` model in the portable `camx_visualization`
package. They draw fitted tactile pad centres and a gap bar; they do not draw
gripper CAD. The earlier overlays used oversized pad boxes, an uncorrected
marker gap and a fixed jaw orientation.

| Dataset under `umi/tamen` | Export episode | Source recording |
| --- | ---: | --- |
| cable_mounting | 1 | Cable_Mounting_2 |
| dish_washing | 1 | Dish_Washing_2 |
| herbal_transfer | 0 | Herbal_Transfer_1 |

Run the portable package from its directory, substituting a matching dataset
root and the episode above:

```sh
python reproject.py --dataset "$DATASET_ROOT" --episode 1 \
  --out "$RENDER_OUT" --seconds 10 --fps 10 --look white
```

The recipe selects the early-recording model only when the dataset name,
episode, source-video hash, episode-parquet hash and both stored EEF poses match
the reviewed sample. Check the job's matched sample override before replacing
a clip. A mismatch retains the historical model; it does not establish that an
unknown recording belongs to the early group.

Publish the resulting 99-frame, 10 fps stereo MP4 in right-camera/left-camera
order. Extract output frame 49 for the poster, update the three corresponding
catalog entries and use the MP4 SHA256 as `render_fingerprint`. Keep the raw
companions synchronized and preserve the dataset export ID. The current media
hashes, source-frame indices and measurement scope are recorded in
[`data/tamen_overlay_review.json`](../../data/tamen_overlay_review.json).

The measurements cover visible open-jaw LED-ring centres in each gripper's own
wrist camera. Other-hand projection and closed-jaw geometry remain unvalidated,
so overall acceptance remains `unmeasured`. The visualization update changes no
dataset values or downloadable dataset samples.
