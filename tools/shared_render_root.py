#!/usr/bin/env python3
"""The ONE render root of every projection clip the site serves (camx curation protocol 6.6).

Every overlay clip, raw companion, poster and clip record on the site is encoded from the shared render root named by
``$CAMX_RENDER_ROOT``: ``<root>/<family>/<project>/<dataset>/ep<N>/{stitched.mp4, <view>.mp4, meta.json, ...}``, written only
by the renderer's ``render_root.py`` (``refresh`` / ``seed`` / ``promote``; ``render_status.py`` says fresh or stale). A consumer
never renders a private copy: a stale or missing clip is refreshed INTO the root, then ``tools/release_clips.py encode`` reads
it from there (``--render`` defaults to the root and refuses any other tree). The legacy renderers in tools/ (rerun_clips,
overlay_picks, raw_only_clips, raw_clips, add_clips, white_overlay, rebuild_droid_previews) refuse to run unless
``CAMX_PRIVATE_RENDER=1`` is set explicitly, and nothing they write may be served.
"""
import os
import sys

ENV = 'CAMX_RENDER_ROOT'
OVERRIDE = 'CAMX_PRIVATE_RENDER'


def shared_root():
    """The shared render root from ``$CAMX_RENDER_ROOT`` (resolved), or None when the variable is unset or empty."""
    value = os.environ.get(ENV, '').strip()
    return os.path.realpath(value) if value else None


def resolve_render_tree(given, private_ok=False):
    """The render tree an encoder may read: ``given`` or the shared root.

    Without ``given`` the shared root is used (an error when ``$CAMX_RENDER_ROOT`` is unset). A ``given`` tree that is not the
    shared root is refused unless ``private_ok`` (``--private-render-tree``): a private tree is for review only, never served.
    """
    root = shared_root()
    if given is None:
        if root is None:
            raise SystemExit(f'no render tree: export {ENV} (the shared render root of every served projection clip) or pass --render')
        return root
    tree = os.path.realpath(given)
    if root is not None and tree != root and not private_ok:
        raise SystemExit(f'--render {given} is not the shared render root ({ENV}={root}); served clips come only from the root: '
                         f'refresh stale clips INTO it with render_root.py refresh, then encode from it. '
                         f'--private-render-tree encodes another tree for review only.')
    return tree


def inside(tree, ep_dir):
    """True when ``ep_dir`` really lies under ``tree`` (symlinks resolved, no hidden component such as .staging / .replaced)."""
    root = os.path.realpath(tree)
    real = os.path.realpath(ep_dir)
    if not real.startswith(root + os.sep):
        return False
    return not any(part.startswith('.') for part in real[len(root) + 1:].split(os.sep))


def refuse_private_render(tool):
    """Entry guard of the legacy renderers: stop unless the user opted in with ``CAMX_PRIVATE_RENDER=1``."""
    if os.environ.get(OVERRIDE) == '1':
        print(f'[{tool}] {OVERRIDE}=1: private render; nothing written here may be served (the site serves ${ENV} only)',
              file=sys.stderr, flush=True)
        return
    raise SystemExit(f'{tool}: refusing to render outside the shared render root. Served clips are encoded from ${ENV} by '
                     f'tools/release_clips.py encode; a stale or missing clip is refreshed INTO the root with render_root.py '
                     f'refresh, never rendered privately. Set {OVERRIDE}=1 for a private render that will not be served.')
