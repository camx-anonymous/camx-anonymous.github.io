#!/usr/bin/env python3
"""render_bimanual_urdf_overlay_video.py (camera-cross-embodiment) with every mesh drawn like the curation site's headless-Rerun
exports: one light grey albedo (urdf_logger.OVERLAY_COLOR 200/200/215), soft lighting, opaque when run with ``--alpha 1.0``.
The tool-centre axes keep their colours (x red, y green, z blue). Used by tools/rerun_clips.py for the fisheye rigs, which the
Rerun viewer cannot draw through (Kannala-Brandt / EUCM lenses).

The renderer file itself is not edited: its source is loaded with the ambient term raised and the colour lookup overridden,
so every argument of the renderer applies unchanged:

  python tools/white_overlay.py --dataset-root <dataset> --episode 0 --profile umi --calib <lens.json> --alpha 1.0 --output clip.mp4
Env:
  CAMX_VIZ  directory holding render_bimanual_urdf_overlay_video.py. Default: this file's own directory (the self-contained
            release layout, <release>/lib). From another checkout point it at <checkout>/camx/visualization.
"""
import os, sys, types

_HERE = os.path.dirname(os.path.abspath(__file__))
VIZ = os.path.expanduser(os.environ.get('CAMX_VIZ') or _HERE)
if not os.path.isfile(os.path.join(VIZ, 'render_bimanual_urdf_overlay_video.py')):
    sys.exit(f'white_overlay.py: no render_bimanual_urdf_overlay_video.py in {VIZ}; set CAMX_VIZ=<checkout>/camx/visualization')
WHITE = (236, 220, 220)   # BGR: OVERLAY_COLOR 200/200/215 scaled so the lit faces reach it
sys.path.insert(0, VIZ)
path = os.path.join(VIZ, 'render_bimanual_urdf_overlay_video.py')
src = open(path).read()
assert src.count('0.45 + 0.55 *') == 1, 'renderer shading term changed, check the patch'
src = src.replace('0.45 + 0.55 *', '0.58 + 0.42 *')      # ambient 0.45 -> 0.58: the flat-lit look of the Rerun viewer
R = types.ModuleType('render_bimanual_urdf_overlay_video'); R.__file__ = path; sys.modules[R.__name__] = R
exec(compile(src, path, 'exec'), R.__dict__)


class _White(dict):
    """The profile's colour table with every mesh white; the axis entries stay as they are."""
    def get(self, key, default=None):
        return super().get(key, default) if str(key).startswith('axis_') else WHITE


_orig = R.render_layer


def render_layer(image, meshes, *a, **k):
    if not isinstance(meshes.profile.colors, _White): meshes.profile.colors = _White(meshes.profile.colors)
    return _orig(image, meshes, *a, **k)


R.render_layer = render_layer
R._label = lambda *a, **k: None   # no per-tile text (side, episode, frame, jaw width): the Rerun exports carry none
if __name__ == '__main__':
    R.main()
