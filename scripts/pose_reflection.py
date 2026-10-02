"""Invert a horizontal image augmentation in COCO heatmap coordinates."""
import numpy as np
COCO_MIRROR=(0,2,1,4,3,6,5,8,7,10,9,12,11,14,13,16,15)
def restore_heatmaps(heatmaps):
    if heatmaps.ndim != 4 or heatmaps.shape[1] != 17:
        raise ValueError('Expected N x COCO17 x height x width heatmaps')
    return np.ascontiguousarray(heatmaps[:,COCO_MIRROR,:,::-1])
