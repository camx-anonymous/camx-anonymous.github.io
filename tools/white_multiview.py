#!/usr/bin/env python3
"""render_multiview_overlay_video.py (camera-cross-embodiment) in the look of tools/white_overlay.py: it draws through the bimanual
renderer's render_layer / _label, so loading that module patched (every mesh and primitive in the Rerun grey, soft lighting, no
per-tile text; the tool-centre axes keep their colours) is all it takes. Run with ``--alpha 1.0``; every argument applies unchanged.
Used by tools/rerun_clips.py for the rigs the headless Rerun viewer cannot do: no gripper CAD (primitive stand-in), fisheye lens
with a multi-view layout, per-view lens overrides.
"""
import os, runpy, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import white_overlay as W  # noqa: E402 -- registers the patched render_bimanual_urdf_overlay_video in sys.modules

path = os.path.join(W.VIZ, 'render_multiview_overlay_video.py')
sys.argv[0] = path
runpy.run_path(path, run_name='__main__')
