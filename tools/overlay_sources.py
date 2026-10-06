"""Explicit, reversible data derivatives used by the overlay review.

Source releases stay untouched. A missing corrected derivative is an error for
that dataset rather than silently regenerating a known-bad overlay.
"""
import os


def dataset_root(root, relative):
    if relative == 'robotiq/droid_lowres/TRI_success':
        corrected = os.path.expanduser(os.environ.get(
            'CAMX_DROID_TRI_CORRECTED_ROOT',
            '~/robotics/reports/camx-overlay-audit-20261005/round3/droid132/'
            'neighbor_transfer/datasets/robotiq/droid_lowres/TRI_success'))
        if not os.path.isfile(os.path.join(corrected, 'meta', 'info.json')):
            raise FileNotFoundError(
                'TRI episode 0 requires the reviewed exterior-calibration transfer. '
                'Set CAMX_DROID_TRI_CORRECTED_ROOT to its dataset directory: ' + corrected)
        return corrected
    if relative == 'umi/umi_on_legs/tossing':
        corrected = os.path.expanduser(os.environ.get(
            'CAMX_UMI_TOSSING_CORRECTED_ROOT',
            '~/robotics/reports/camx-overlay-audit-20261005/round3/handheld/'
            'corrected_data/umi/umi_on_legs/tossing'))
        if not os.path.isfile(os.path.join(corrected, 'meta', 'info.json')):
            raise FileNotFoundError(
                'Tossing widths require the reviewed source-tag reconstruction. '
                'Set CAMX_UMI_TOSSING_CORRECTED_ROOT to its dataset directory: ' + corrected)
        return corrected
    if relative == 'widowx/bridge_v2/bridge_v2':
        # The side2 re-conversion (4,681 episodes whose only stream is the real wrist camera): released 2026-10-04 10:40
        # with meta/_SUCCESS, but its camx_480p link is on the coordinator's hold (PLAN.md family map, LOG 2026-10-04 09:55),
        # so the site reads the export directly. The site's dataset row was built from the same tree.
        side2 = os.path.expanduser(os.environ.get('CAMX_BRIDGE_V2_ROOT', '/storage/hdd4/yihuai/bridge_data/processed_data_side2/bridge_v2'))
        if not os.path.isfile(os.path.join(side2, 'meta', 'info.json')):
            raise FileNotFoundError('Bridge V2 clips need the side2 wrist-camera export. Set CAMX_BRIDGE_V2_ROOT to its dataset directory: ' + side2)
        return side2
    return os.path.join(root, relative)
