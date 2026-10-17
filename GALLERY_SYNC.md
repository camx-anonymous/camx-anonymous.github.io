# Keeping the public and local projection galleries synchronized

The completed local release gallery is the source for `/gallery/` on the public
website. Do not render a second set of previews for that page. The publisher
preserves the selected episodes, rendered frame count/rate, comparisons,
calibration caveats and dated screening notes. It compresses the stitched MP4s
with NVENC (up to 360 rows) and serves individual cameras by cropping the same
strip in the browser. Source and published media hashes are recorded separately.

```bash
python3 tools/sync_gallery.py --source /path/to/local/site \
  --website /path/to/website-checkout --work /path/to/publish-work \
  --gpu 1 --jobs 2 --push --verify-live https://camx-anonymous.github.io
```

Without `--push`, this builds and validates the website checkout only. A completed,
quiet source tree is required. Frame-count/rate mismatches, changed inputs,
missing assets, invalid camera tiles and a site above 990 MB stop publication.
The encoder uses two workers and has no CPU codec fallback. The work directory
holds reusable encodes and an exclusive publication lock.

The publisher owns only `gallery/` and `data/gallery-sync.json`. It commits only
those paths and refuses to push unpublished commits containing unrelated changes.
Existing website sample archives and historical multi-episode previews are kept.
The dataset browser's `gallery-link.js` makes the synchronized gallery its current
preview source; `/overlays/` explicitly labels its older examples as historical.

A user systemd timer runs this command every ten minutes on the gallery host.
`camx-gallery-publish.timer` is enabled; `camx-gallery-publish.service` logs errors
and retries on the next timer event. The source must remain unchanged for at least
60 seconds. GitHub Pages deployment can add several minutes. This is eventual
synchronization while the host, credentials and GitHub Pages are available, not an
instantaneous or unconditional guarantee. The service verifies the live receipt
and gallery-manifest hashes after each push; its work directory's `status.json`
records the most recent successful check.

The October 16 screening report is a frozen observation of the original public
previews, one per 75 projects, not all dataset leaves. Gallery notes state the
screened episode and link to its image. They do not relabel newer renders as
failed or alter source data/calibrations. The report and its supporting images
are mirrored alongside the gallery.
