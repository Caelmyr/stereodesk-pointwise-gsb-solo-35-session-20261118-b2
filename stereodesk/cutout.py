"""Pick one near object out of the left eye and keep it where it is.

The click chooses a disparity layer: neighbouring matches that agree with the
clicked point's disparity become the object core.  The core is then trimmed
and finished with the left photograph's own colours, so that a paper edge the
matcher could not measure is still kept while a back panel seen through an
opening is not pulled into the object.  Pixels that neither disparity nor
colour can settle stay transparent.
"""
from dataclasses import dataclass

import cv2
import numpy as np

from image_lab.validation import Invalid


SEARCH_RADIUS = 36
SEED_REACH = 26
MIN_GROUP = 40
GROUP_GAP = 2.0
CORE_FRACTION = 0.25
MIN_BAND = 3.0
MARGIN_FRACTION = 0.3
MIN_MARGIN = 24
TRIM_RATIO = 0.45
GROW_RATIO = 0.6
COLOR_SIGMA = 2.5
GROW_STEPS = 12


@dataclass(frozen=True)
class Cutout:
    rgba: np.ndarray
    alpha: np.ndarray
    disparity: float
    area: int
    recovered: int
    coverage: float
    box: tuple

    def report(self):
        return {'disparity': round(self.disparity, 2), 'area': self.area,
                'recovered': self.recovered, 'coverage': round(self.coverage, 4),
                'box': list(self.box)}


def _lab(rgba):
    return cv2.cvtColor(rgba[..., :3], cv2.COLOR_RGB2LAB).astype(np.float32)


def _disc(radius):
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1,) * 2)


def _erode(mask, radius):
    return cv2.erode(mask.astype(np.uint8), _disc(radius)).astype(bool)


def _palette(samples, count):
    samples = np.asarray(samples, np.float32).reshape(-1, 3)
    if len(samples) == 0:
        return np.zeros((0, 3), np.float32)
    if len(samples) > 15000:
        samples = samples[np.random.default_rng(0).choice(len(samples), 15000, replace=False)]
    count = min(count, len(samples))
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    _, _, centers = cv2.kmeans(samples, count, None, criteria, 2, cv2.KMEANS_PP_CENTERS)
    return centers


def _nearest_color(lab, centers):
    flat = lab.reshape(-1, 3)
    distance = np.full(len(flat), 1e9, np.float32)
    for center in centers:
        delta = flat - center
        distance = np.minimum(distance, np.einsum('ij,ij->i', delta, delta))
    return np.sqrt(distance).reshape(lab.shape[:2])


def _groups(result, x, y):
    """Split the confidently matched pixels around the click by disparity."""
    height, width = result.valid.shape
    y0, y1 = max(0, y - SEARCH_RADIUS), min(height, y + SEARCH_RADIUS + 1)
    x0, x1 = max(0, x - SEARCH_RADIUS), min(width, x + SEARCH_RADIUS + 1)
    ys, xs = np.nonzero(result.valid[y0:y1, x0:x1])
    if not len(ys):
        return []
    ys, xs = ys + y0, xs + x0
    values = result.left[ys, xs]
    order = np.argsort(values)
    values, ys, xs = values[order], ys[order], xs[order]
    breaks = [0] + [index for index in range(1, len(values))
                    if values[index] - values[index - 1] > GROUP_GAP] + [len(values)]
    groups = []
    for start, stop in zip(breaks, breaks[1:]):
        if stop - start >= MIN_GROUP:
            groups.append((float(np.median(values[start:stop])), xs[start:stop], ys[start:stop]))
    return groups


def _seed(image, result, x, y):
    """Choose the matched group that plausibly belongs to what was clicked."""
    if result.valid.shape != image.shape[:2]:
        raise Invalid('视差结果与左眼图像尺寸不一致')
    lab = _lab(image)
    clicked = lab[y, x]
    best = None
    for disparity, xs, ys in _groups(result, x, y):
        distance = np.linalg.norm(lab[ys, xs] - clicked, axis=1)
        offset = np.hypot(xs - x, ys - y)
        index = int(np.argmin(distance + 0.5 * offset))
        if offset[index] > SEED_REACH:
            continue
        score = float(np.percentile(distance, 25)) + 0.15 * float(offset[index])
        if best is None or score < best[0]:
            best = (score, disparity, int(xs[index]), int(ys[index]))
    if best is None:
        raise Invalid('这里附近没有可信视差，请在纸艺主体上再点一下')
    return best[1], best[2], best[3]


def _core(result, disparity, x, y):
    """Follow the clicked disparity layer: neighbouring matches on the same
    layer are the object, matches on another layer stay out."""
    band = max(MIN_BAND, CORE_FRACTION * abs(disparity))
    matched = result.valid & (np.abs(result.left - disparity) <= band)
    _, labels = cv2.connectedComponents(matched.astype(np.uint8), connectivity=8)
    seed = labels[y, x]
    if seed == 0:
        ys, xs = np.nonzero(labels)
        nearest = int(np.argmin((xs - x) ** 2 + (ys - y) ** 2))
        seed = labels[ys[nearest], xs[nearest]]
    core = labels == seed
    if core.sum() < MIN_GROUP:
        raise Invalid('点选处的主体太小，无法分离')
    return core, band


def _window(mask, shape):
    ys, xs = np.nonzero(mask)
    margin = max(MIN_MARGIN, int(MARGIN_FRACTION * np.sqrt(mask.sum())))
    height, width = shape
    return (slice(max(0, ys.min() - margin), min(height, ys.max() + margin + 1)),
            slice(max(0, xs.min() - margin), min(width, xs.max() + margin + 1)))


def _color_ratio(image, result, core_w, valid_w, disparity, band, window):
    """Score the working window by how much it looks like the core rather than the rest."""
    lab = _lab(image)[window]
    disparity_w = result.left[window]
    background = valid_w & (np.abs(np.nan_to_num(disparity_w, nan=1e9) - disparity) > band)
    foreground = _erode(core_w, 3)
    behind = _erode(background, 2) if background.sum() > 200 else background
    if foreground.sum() < 30 or behind.sum() < 30:
        raise Invalid('主体周围缺少可比较的纹理，无法判断边缘')
    front_palette = _palette(lab[foreground], 6)
    front = _nearest_color(lab, front_palette)
    # Clear the background sample of pixels that are either spatially against
    # the object or already look like it; otherwise edge spill would teach the
    # gate that the object is its own opposite.
    spread = float(np.percentile(front[core_w], 95))
    clear = front > max(3 * COLOR_SIGMA, spread + 2 * COLOR_SIGMA)
    clear &= ~cv2.dilate(core_w.astype(np.uint8), _disc(6)).astype(bool)
    behind = behind & clear
    if behind.sum() < 30:
        raise Invalid('主体与周围颜色过于接近，无法判断边缘')
    back = _nearest_color(lab, _palette(lab[behind], 6))
    return 1 / (1 + np.exp(np.clip((front - back) / COLOR_SIGMA, -40, 40)))


def _polish(image, result, core_w, valid_w, disparity, band, seed_x, seed_y, window):
    """Trim core pixels that clearly belong to the surroundings, then grow into
    unmatched pixels that still look like the object."""
    ratio = _color_ratio(image, result, core_w, valid_w, disparity, band, window)
    y0, x0 = window[0].start, window[1].start
    mask = core_w & (ratio >= TRIM_RATIO)
    _, labels = cv2.connectedComponents(mask.astype(np.uint8), connectivity=8)
    local_y, local_x = seed_y - y0, seed_x - x0
    label = labels[local_y, local_x]
    if label == 0:
        ys, xs = np.nonzero(mask)
        if not len(ys):
            raise Invalid('未能分离出所选纸艺，请在其他位置再点一下')
        nearest = int(np.argmin((xs - local_x) ** 2 + (ys - local_y) ** 2))
        label = labels[ys[nearest], xs[nearest]]
    mask = labels == label
    layer = valid_w & (np.abs(result.left[window] - disparity) <= band)
    for _ in range(GROW_STEPS):
        near = cv2.dilate(mask.astype(np.uint8), _disc(2)).astype(bool)
        addition = near & ~mask & (~valid_w | layer) & (ratio >= GROW_RATIO)
        if not addition.any():
            break
        mask |= addition
    return mask


def _alpha(mask):
    soft = cv2.GaussianBlur(mask.astype(np.float32), (0, 0), 0.9)
    return np.clip((soft - 0.35) / 0.3, 0.0, 1.0)


def separate(image, result, x, y):
    """Return the clicked object as a full-canvas RGBA cutout."""
    height, width = image.shape[:2]
    if not (0 <= x < width and 0 <= y < height):
        raise Invalid('点选位置超出左眼图像')
    disparity, seed_x, seed_y = _seed(image, result, x, y)
    core, band = _core(result, disparity, seed_x, seed_y)
    window = _window(core, core.shape)
    core_w = core[window]
    valid_w = result.valid[window]
    mask_w = _polish(image, result, core_w, valid_w, disparity, band,
                     seed_x, seed_y, window)
    alpha = np.zeros((height, width), np.float32)
    alpha[window] = _alpha(mask_w)
    mask = alpha >= 0.5
    ys, xs = np.nonzero(mask)
    if not len(ys):
        raise Invalid('未能分离出所选纸艺，请在其他位置再点一下')
    matched = mask_w & valid_w
    known = result.left[window][matched]
    rgba = image.copy()
    rgba[..., 3] = np.rint(alpha * 255).astype(np.uint8)
    rgba[alpha <= 0] = 0
    return Cutout(rgba=rgba, alpha=alpha,
                  disparity=float(np.median(known)) if len(known) else disparity,
                  area=int(mask.sum()), recovered=int(mask_w.sum() - matched.sum()),
                  coverage=float(matched.sum() / mask_w.sum()),
                  box=(int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1))


def checkerboard_preview(cutout, tile=16):
    height, width = cutout.alpha.shape
    y, x = np.indices((height, width))
    checker = (((y // tile) + (x // tile)) % 2).astype(np.uint8)
    shade = (checker * 42 + 46).astype(np.float32)
    background = np.dstack([shade, shade, shade])
    alpha = cutout.alpha[..., None]
    color = cutout.rgba[..., :3].astype(np.float32) * alpha + background * (1 - alpha)
    return np.dstack([np.rint(color).astype(np.uint8), np.full((height, width), 255, np.uint8)])
