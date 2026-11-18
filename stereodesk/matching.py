from dataclasses import dataclass

import cv2
import numpy as np

from .settings import validate_search_width


INVALID_EDGE = 1
INVALID_SCORE = 2
INVALID_TEXTURE = 3
INVALID_CROSS = 4
REASONS = {
    INVALID_EDGE: '另一眼无完整像素支撑',
    INVALID_SCORE: '搜索范围内无视差',
    INVALID_TEXTURE: '纹理强度低',
    INVALID_CROSS: '两眼的视差不一致',
}


@dataclass(frozen=True)
class Disparity:
    left: np.ndarray
    right: np.ndarray
    valid: np.ndarray
    right_valid: np.ndarray
    reason: np.ndarray
    confidence: np.ndarray
    texture: np.ndarray


def input_gray(image):
    return cv2.cvtColor(image, cv2.COLOR_RGBA2GRAY)


def disparity_plane(reference, other, minimum, count, window):
    matcher = cv2.StereoSGBM_create(
        minDisparity=minimum, numDisparities=count, blockSize=window,
        P1=8 * window ** 2, P2=32 * window ** 2, disp12MaxDiff=-1,
        preFilterCap=31, uniquenessRatio=9, speckleWindowSize=48,
        speckleRange=2, mode=cv2.STEREO_SGBM_MODE_SGBM_3WAY,
    )
    result = matcher.compute(reference, other).astype(np.float32) / 16
    return np.where(result <= minimum - 1, np.nan, result)


def local_texture(image, window):
    gray = image.astype(np.float32)
    average = cv2.boxFilter(gray, -1, (window, window))
    squared = cv2.boxFilter(gray * gray, -1, (window, window))
    return np.sqrt(np.maximum(0, squared - average * average))


def sample_horizontal(value, support, xr):
    width = value.shape[1]
    x0 = np.floor(xr).astype(np.int32)
    fraction = xr - x0
    x1 = x0 + (fraction > 1e-5)
    x0_safe = np.clip(x0, 0, width - 1)
    x1_safe = np.clip(x1, 0, width - 1)
    lo = np.take_along_axis(value, x0_safe, axis=1)
    hi = np.take_along_axis(value, x1_safe, axis=1)
    valid = ((x0 >= 0) & (x1 < width) & np.take_along_axis(support, x0_safe, axis=1)
             & np.take_along_axis(support, x1_safe, axis=1))
    return lo + fraction * (hi - lo), valid


def consistency(reference, other, reference_support, other_support, texture, settings):
    has_match = np.isfinite(reference)
    coordinates = np.arange(reference.shape[1], dtype=np.float32)[None, :]
    other_x = coordinates - np.nan_to_num(reference)
    match, target_supported = sample_horizontal(other, other_support, other_x)
    geometry = reference_support & target_supported
    residual = np.abs(reference + match)
    texture_ok = texture >= settings['texture']
    supported = geometry & has_match
    consistent = np.isfinite(match) & (residual <= settings['tolerance'])
    valid = supported & texture_ok & consistent
    reason = np.zeros(reference.shape, np.uint8)
    reason[supported & texture_ok & ~consistent] = INVALID_CROSS
    reason[supported & ~texture_ok] = INVALID_TEXTURE
    reason[geometry & ~has_match] = INVALID_SCORE
    reason[~geometry] = INVALID_EDGE
    residual = np.where(valid, residual, settings['tolerance'])
    confidence = np.where(valid, np.clip(1 - residual / (2 * settings['tolerance']), 0, 1), 0)
    return valid, reason, confidence.astype(np.float32)


def estimate(pair, settings):
    left = input_gray(pair.left)
    right = input_gray(pair.right)
    low, span, window = settings['minimum'], settings['span'], settings['window']
    validate_search_width(settings, left.shape[1])
    ld = disparity_plane(left, right, low, span, window)
    rd = disparity_plane(right, left, -low - span + 1, span, window)
    lt, rt = local_texture(left, window), local_texture(right, window)
    kernel = np.ones((window, window), np.uint8)
    ls = cv2.erode(pair.left_support.astype(np.uint8), kernel, borderType=cv2.BORDER_CONSTANT,
                   borderValue=0).astype(bool)
    rs = cv2.erode(pair.right_support.astype(np.uint8), kernel, borderType=cv2.BORDER_CONSTANT,
                   borderValue=0).astype(bool)
    lv, reason, confidence = consistency(ld, rd, ls, rs, lt, settings)
    rv, _, _ = consistency(rd, ld, rs, ls, rt, settings)
    return Disparity(ld, rd, lv, rv, reason, confidence, lt)
