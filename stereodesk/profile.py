import math

import numpy as np

from image_lab.validation import Invalid
from .settings import report_length


MAX_SAMPLES = 1024
MIN_LENGTH = 2.0
MIN_RUN = 5
MIN_SIDE = 2
MAX_REPAIR = 3
BAND = 1.5
OFF_LINE = 0.5


def cluster(values, gap):
    """Split nearby disparities into groups separated by at least ``gap``."""
    ordered = np.sort(np.asarray(values, dtype=np.float64))
    groups = []
    start = 0
    for index in range(1, ordered.size):
        if ordered[index] - ordered[index - 1] > gap:
            groups.append(ordered[start:index])
            start = index
    groups.append(ordered[start:])
    return groups


def agreeing(values, target, gap):
    return values[np.abs(values - target) <= gap]


def nearest(values, valid, points):
    """Nearest-pixel disparity lookup; unsupported points stay NaN."""
    height, width = values.shape
    xi = np.rint(points[..., 0]).astype(np.int64)
    yi = np.rint(points[..., 1]).astype(np.int64)
    inside = (xi >= 0) & (xi < width) & (yi >= 0) & (yi < height)
    xi = np.clip(xi, 0, width - 1)
    yi = np.clip(yi, 0, height - 1)
    ok = inside & valid[yi, xi]
    return np.where(ok, values[yi, xi], np.nan), ok, np.stack((xi, yi), axis=-1)


def window(values, valid, xi, yi, radius):
    """A square window of pixels around every sample, plus its pixel offsets."""
    height, width = values.shape
    spans = np.arange(-radius, radius + 1)
    offset_x, offset_y = np.meshgrid(spans, spans, indexing='ij')
    offset_x = offset_x.ravel()[None, :]
    offset_y = offset_y.ravel()[None, :]
    px = xi[:, None] + offset_x
    py = yi[:, None] + offset_y
    inside = (px >= 0) & (px < width) & (py >= 0) & (py < height)
    clipped_x = np.clip(px, 0, width - 1)
    clipped_y = np.clip(py, 0, height - 1)
    ok = inside & valid[clipped_y, clipped_x]
    return np.where(ok, values[clipped_y, clipped_x], np.nan), ok, offset_x, offset_y


def band(offset_x, offset_y, across_x, across_y, along_x, along_y):
    """The pixels immediately on either side of the line, not along it."""
    across = offset_x * across_x + offset_y * across_y
    along = offset_x * along_x + offset_y * along_y
    keep = (np.abs(across) > OFF_LINE) & (np.abs(along) <= BAND)
    return (keep & (across < 0))[0], (keep & (across > 0))[0]


def surface(negative, positive, gap):
    """One surface present immediately on both sides of the line, if any."""
    negative = negative[np.isfinite(negative)]
    positive = positive[np.isfinite(positive)]
    if negative.size < MIN_SIDE or positive.size < MIN_SIDE:
        return None
    groups = sorted(cluster(np.concatenate((negative, positive)), gap),
                    key=len, reverse=True)
    for group in groups:
        middle = float(np.median(group))
        if agreeing(negative, middle, gap).size < MIN_SIDE:
            continue
        if agreeing(positive, middle, gap).size < MIN_SIDE:
            continue
        return middle
    return None


def along_runs(centre, valid, gap):
    """How many samples in a row the line itself keeps this disparity."""
    lengths = [0] * len(centre)
    for index in range(len(centre)):
        if not valid[index]:
            continue
        start = index
        while (start > 0 and valid[start - 1]
               and abs(centre[start - 1] - centre[index]) <= gap):
            start -= 1
        end = index
        while (end + 1 < len(centre) and valid[end + 1]
               and abs(centre[end + 1] - centre[index]) <= gap):
            end += 1
        lengths[index] = end - start + 1
    return lengths


def runs_of(flag):
    """Index ranges of consecutive True entries."""
    ranges = []
    start = None
    for index, value in enumerate(flag):
        if value and start is None:
            start = index
        elif not value and start is not None:
            ranges.append((start, index - 1))
            start = None
    if start is not None:
        ranges.append((start, len(flag) - 1))
    return ranges


def segments(values, step):
    """Contiguous ranges whose resolved disparities never jump by more than ``step``."""
    result = []
    start = None
    previous = None
    for index, value in enumerate(values):
        if value is None:
            if start is not None:
                result.append([start, index - 1])
                start = None
            previous = None
            continue
        if start is None:
            start = index
        elif abs(value - previous) > step:
            result.append([start, index - 1])
            start = index
        previous = value
    if start is not None:
        result.append([start, len(values) - 1])
    return result


def line_profile(result, settings, start, end):
    x0, y0 = (float(value) for value in start)
    x1, y1 = (float(value) for value in end)
    length = math.hypot(x1 - x0, y1 - y0)
    if length < MIN_LENGTH:
        raise Invalid('剖面线过短，请在左眼图上拉出更长的线')
    count = int(min(MAX_SAMPLES, max(2, math.ceil(length) + 1)))
    t = np.linspace(0.0, 1.0, count)
    xs = x0 + (x1 - x0) * t
    ys = y0 + (y1 - y0) * t
    matching, scale = settings['matching'], settings['scale']
    radius = max(2, matching['window'] // 2 + 1)
    gap = max(1.0, float(matching['tolerance']))
    step = max(2.0, 2.0 * float(matching['tolerance']))
    along_x, along_y = (x1 - x0) / length, (y1 - y0) / length
    across_x, across_y = -along_y, along_x
    values = np.nan_to_num(result.left, nan=0.0)
    centre, centre_valid, pixels = nearest(values, result.valid, np.stack((xs, ys), axis=-1))
    near, near_valid, offset_x, offset_y = window(
        values, result.valid, pixels[..., 0], pixels[..., 1], radius)
    negative, positive = band(offset_x, offset_y, across_x, across_y, along_x, along_y)
    matches = np.abs(near - centre[:, None]) <= gap
    left_agree = (near_valid & negative & matches).sum(axis=1)
    right_agree = (near_valid & positive & matches).sum(axis=1)
    runs = along_runs(centre, centre_valid, gap)

    resolved = [None] * count
    repaired = [False] * count
    for index in range(count):
        if centre_valid[index]:
            own = float(centre[index])
            # Either side of the line has to show the same surface.  That keeps
            # a thin rail that only grazes the line, while a stray value sitting
            # on a different surface has nothing agreeing beside it and is
            # replaced below.
            if (left_agree[index] and right_agree[index]) or runs[index] >= MIN_RUN:
                resolved[index] = own
                continue
        replacement = surface(near[index][negative], near[index][positive], gap)
        if replacement is not None:
            resolved[index] = replacement
            repaired[index] = True

    # A short gap in the line is only crossed when the pixels alongside it show
    # one and the same surface; longer stretches without a reliable match stay
    # blank instead of being joined up with a made-up slope.
    for first, last in runs_of(repaired):
        if last - first + 1 > MAX_REPAIR:
            for index in range(first, last + 1):
                resolved[index] = None

    scale_ready = bool(scale['baseline_mm'] and scale['focal_px'])
    plotted = []
    for value in resolved:
        if value is None:
            plotted.append(None)
            continue
        distance = report_length(value, scale) if scale_ready else value
        plotted.append(None if distance is None else round(distance, 2))
    unmatched_scale = scale_ready and not any(value is not None for value in plotted)
    return {
        'start': [round(x0, 2), round(y0, 2)],
        'end': [round(x1, 2), round(y1, 2)],
        'length': round(length, 2),
        'samples': count,
        'units': 'mm' if scale_ready else 'px',
        'unmatched_scale': unmatched_scale,
        'x': [round(float(value), 2) for value in xs],
        'y': [round(float(value), 2) for value in ys],
        'values': plotted,
        'disparity': [None if value is None else round(value, 3) for value in resolved],
        'segments': segments(resolved, step),
        'matched': sum(1 for value in plotted if value is not None),
    }
