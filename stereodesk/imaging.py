import csv
from io import BytesIO, StringIO

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from image_lab.validation import Invalid
from .geometry import warp_rgba
from .matching import REASONS
from .settings import report_length


MAX_PIXELS = 2_400_000
PALETTE = [(20, 30, 52), (31, 95, 141), (41, 161, 140), (162, 201, 94), (255, 226, 134)]
STATUS_COLORS = [(54, 140, 117), (66, 77, 95), (96, 77, 118), (196, 145, 67), (202, 92, 101)]


def load_image(file):
    try:
        with Image.open(file) as opened:
            width, height = opened.size
            if width < 96 or height < 64 or width * height > MAX_PIXELS:
                raise Invalid('图像宽高至少 96 × 64，且最多 240 万像素')
            if opened.format not in ('PNG', 'JPEG', 'WEBP', 'TIFF') or getattr(opened, 'n_frames', 1) != 1:
                raise Invalid('需要单帧 PNG、JPG、WebP 或 TIFF')
            image = ImageOps.exif_transpose(opened).convert('RGBA')
            if image.width < 96 or image.height < 64:
                raise Invalid('应用照片朝向后，宽高至少为 96 × 64')
            return np.array(image)
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise Invalid('无法读取照片内容') from exc


def png(image):
    output = BytesIO()
    Image.fromarray(image).save(output, 'PNG', compress_level=4)
    return output.getvalue()


def simple_anaglyph(left, right, convergence):
    height, width = left.shape[:2]
    transform = np.array([[1, 0, convergence], [0, 1, 0]], np.float32)
    shifted = warp_rgba(right, transform, (width, height))
    output = np.empty_like(left)
    output[..., 0] = left[..., 0]
    output[..., 1:3] = shifted[..., 1:3]
    output[..., 3] = np.minimum(left[..., 3], shifted[..., 3])
    output[output[..., 3] == 0] = 0
    return output


def cross_eye(left, right):
    height = left.shape[0]
    divider = np.full((height, 10, 4), (31, 39, 47, 255), np.uint8)
    return np.concatenate((right, divider, left), axis=1)


def blend(left, right):
    alpha_l = left[..., 3:4].astype(np.float32) / 255
    alpha_r = right[..., 3:4].astype(np.float32) / 255
    scale = alpha_l + alpha_r
    mix = alpha_l * left[..., :3] + alpha_r * right[..., :3]
    color = np.divide(mix, scale, out=np.zeros_like(mix), where=scale > 0)
    alpha = np.maximum(left[..., 3:4], right[..., 3:4])
    return np.concatenate((np.rint(color).astype(np.uint8), alpha), axis=2)


def gradient(field, lo, hi, palette):
    ramp = np.linspace(lo, hi, len(palette), endpoint=True)
    return np.stack([np.interp(field, ramp, channels) for channels in zip(*palette)], axis=-1).astype(np.uint8)


def disparity_preview(result, matching):
    minimum = matching['minimum']
    color = gradient(np.nan_to_num(result.left, nan=minimum), minimum,
                     minimum + matching['span'], PALETTE)
    background = np.full(color.shape, (28, 35, 46), np.uint8)
    y, x = np.indices(result.valid.shape)
    background[((x // 8) + (y // 8)) % 2 == 1] = (36, 46, 57)
    return np.where(result.valid[..., None], color, background)


def diagnostic_preview(result):
    colors = np.asarray(STATUS_COLORS, dtype=np.uint8)
    return colors[result.reason]


def summary(result):
    known = result.left[result.valid]
    counts = {label: int((result.reason == reason).sum()) for reason, label in REASONS.items()}
    return {
        'valid_pixels': int(result.valid.sum()),
        'coverage': round(float(result.valid.mean()), 4),
        'median_disparity': round(float(np.median(known)), 3) if len(known) else None,
        'percentiles': [round(float(x), 2) for x in np.percentile(known, (5, 95))] if len(known) else None,
        'reasons': counts,
    }


def sample_report(result, settings, x, y):
    valid = bool(result.valid[y, x])
    disparity = float(result.left[y, x]) if valid else None
    distance = report_length(disparity, settings['scale']) if valid else None
    return {
        'valid': valid, 'disparity': round(disparity, 3) if valid else None,
        'right_x': round(x - disparity, 3) if valid else None,
        'reason': REASONS.get(int(result.reason[y, x])),
        'confidence': round(float(result.confidence[y, x]), 3),
        'texture': round(float(result.texture[y, x]), 3),
        'distance_mm': round(distance, 3) if distance is not None else None,
    }


def disparity_numpy(result):
    output = BytesIO()
    np.save(output, np.where(result.valid, result.left, np.nan).astype(np.float32), allow_pickle=False)
    return output.getvalue()


def row_csv(result, settings, y):
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(('x', 'y', 'valid', 'disparity_px', 'distance_mm', 'confidence', 'reason'))
    for x in range(result.left.shape[1]):
        point = sample_report(result, settings, x, y)
        writer.writerow((x, y, int(point['valid']), point['disparity'], point['distance_mm'],
                         point['confidence'], point['reason']))
    return output.getvalue().encode('utf-8-sig')
