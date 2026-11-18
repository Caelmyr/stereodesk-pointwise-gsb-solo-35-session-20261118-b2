from dataclasses import dataclass

import cv2
import numpy as np

from image_lab.validation import Invalid


@dataclass(frozen=True)
class AlignedPair:
    left: np.ndarray
    right: np.ndarray
    left_support: np.ndarray
    right_support: np.ndarray
    right_matrix: np.ndarray

    @property
    def shared_support(self):
        return self.left_support & self.right_support


def right_transform(width, height, settings):
    center = ((width - 1) / 2, (height - 1) / 2)
    transform = cv2.getRotationMatrix2D(center, settings['angle'], 1.0)
    transform[:, 2] += (settings['dx'], settings['dy'])
    return transform


def warp_rgba(image, matrix, size, *, inverse=False):
    pixels = image.astype(np.float32) / 255
    pixels[..., :3] *= pixels[..., 3:4]
    flags = cv2.INTER_LINEAR | (cv2.WARP_INVERSE_MAP if inverse else 0)
    warped = cv2.warpAffine(pixels, matrix, size, flags=flags,
                            borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
    alpha = warped[..., 3:4]
    np.divide(warped[..., :3], alpha, out=warped[..., :3], where=alpha > 1e-6)
    return np.rint(np.clip(warped, 0.0, 1.0) * 255).astype(np.uint8)


def aligned_pair(left, right, alignment):
    height, width = left.shape[:2]
    matrix = right_transform(width, height, alignment)
    transformed = warp_rgba(right, matrix, (width, height))
    return AlignedPair(left, transformed, left[..., 3] >= 254,
                       transformed[..., 3] >= 254, matrix)


def map_to_source(matrix, x, y):
    inverse = cv2.invertAffineTransform(matrix)
    result = inverse @ np.array([x, y, 1.0])
    return [round(float(coord), 2) for coord in result]


def rectangle_area(rect):
    x0, y0, x1, y1 = rect
    return (x1 - x0) * (y1 - y0)


def support_rectangle(support):
    """Find the largest fully supported rectangle, preserving top-left on ties."""
    height, width = support.shape
    if support.all():
        return 0, 0, width, height
    heights = np.zeros(width, dtype=np.int32)
    best = (0, 0, 0, 0)
    best_area = 0
    for y, row in enumerate(support):
        heights = np.where(row, heights + 1, 0)
        stack = []
        for x, value in enumerate(heights.tolist() + [0]):
            start = x
            while stack and stack[-1][1] > value:
                start, high = stack.pop()
                area = high * (x - start)
                top = y + 1 - high
                if area > best_area or (area == best_area and (top, start) < (best[1], best[0])):
                    best_area = area
                    best = start, top, x, y + 1
            if value and (not stack or stack[-1][1] < value):
                stack.append((start, value))
    return best


def extract_pair(left, right, support):
    x0, y0, x1, y1 = support_rectangle(support)
    if x1 <= x0 or y1 <= y0:
        raise Invalid('两眼当前没有可用的共同裁图')
    return left[y0:y1, x0:x1], right[y0:y1, x0:x1], (x0, y0, x1, y1)


def guide_overlay(image, row, color):
    output = image.copy()
    height, width = image.shape[:2]
    y = min(height - 1, round(row * (height - 1)))
    for delta in range(-96, 97, 24):
        adjacent = y + delta
        if 0 <= adjacent < height and delta:
            cv2.line(output, (0, adjacent), (width - 1, adjacent), color, 1)
    cv2.line(output, (0, y), (width - 1, y), color, 2)
    return output
