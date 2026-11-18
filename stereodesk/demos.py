from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


@dataclass(frozen=True)
class Demo:
    name: str
    details: str
    seed: int
    shifts: tuple[int, int, int]


DEMOS = {
    'studio': Demo('纸艺展台', '规则立体对。三层实际视差分别约为 4、16、32 px。', 38, (4, 16, 32)),
    'overlap': Demo('交叠道具', '栏板和后方展台的遮挡面积较大，用于查看双向检查。', 81, (4, 12, 41)),
    'flat': Demo('低纹理展墙', '中间有一块近乎平坦的材质，适合比较可信区与颜色图。', 26, (5, 19, 30)),
}
WIDTH = 768
HEIGHT = 476
FONT = ImageFont.load_default(size=19)


def color_field(rng, w, h, base, variation=14):
    granular = rng.normal(0.0, variation, (h, w))
    coarse = rng.normal(0.0, 5.0, (max(2, h // 16), max(2, w // 16))).astype(np.float32)
    rough = granular + cv2.resize(coarse, (w, h), interpolation=cv2.INTER_CUBIC)
    light = np.linspace(1.08, 0.91, w)[None, :, None] * np.linspace(0.91, 1.07, h)[:, None, None]
    pixels = np.clip(np.array(base) * light + rough[..., None], 0, 255)
    return Image.fromarray(pixels.astype(np.uint8)).convert('RGBA')


def backdrop(rng, low_texture):
    wall = color_field(rng, WIDTH + 112, HEIGHT, (65, 86, 99), 10 if not low_texture else 1)
    draw = ImageDraw.Draw(wall, 'RGBA')
    for y in range(12, HEIGHT, 25):
        start = 25 if y % 2 else 10
        for x in range(start, WIDTH + 112, 27):
            if not low_texture or x < 210 or x > 620:
                draw.ellipse((x, y, x + 3, y + 3), fill=(121, 152, 162, 255))
    draw.line((0, 378, WIDTH + 112, 378), fill=(35, 49, 62, 255), width=4)
    draw.text((93, 73), 'PAPER STUDIO', fill=(203, 218, 213, 255), font=FONT)
    draw.line((93, 104, 237, 104), fill=(126, 166, 170, 255), width=2)
    return wall


def screen(rng, low_texture):
    width, height = 390, 292
    paper = color_field(rng, width, height, (73, 144, 139), 13 if not low_texture else 0.8)
    draw = ImageDraw.Draw(paper, 'RGBA')
    draw.rectangle((4, 4, width - 5, height - 5), outline=(138, 204, 181, 255), width=2)
    draw.arc((25, 33, 198, 204), 40, 315, fill=(216, 222, 148, 255), width=4)
    draw.arc((58, 69, 165, 175), 0, 340, fill=(216, 222, 148, 255), width=4)
    draw.line((118, 115, 307, 227), fill=(216, 222, 148, 255), width=3)
    draw.text((115, 238), 'STEREO STUDY   /   02', fill=(222, 232, 194, 255), font=FONT)
    return paper


def arch(rng):
    width, height = 294, 312
    paper = color_field(rng, width, height, (206, 131, 81), 12)
    mask = Image.new('L', (width, height))
    outline = ImageDraw.Draw(mask)
    outline.rounded_rectangle((7, 0, 285, 305), radius=108, fill=255)
    outline.rounded_rectangle((104, 111, 242, height + 48), radius=65, fill=0)
    draw = ImageDraw.Draw(paper, 'RGBA')
    for inset in (18, 27, 41):
        draw.rounded_rectangle((inset, inset, width - inset, height + 12),
                               radius=105 - inset, outline=(244, 185, 120, 255), width=1)
    for y in range(49, height - 13, 17):
        draw.line((25, y, 70, y), fill=(137, 81, 59, 255), width=1)
        draw.ellipse((51, y - 3, 55, y + 1), fill=(249, 205, 159, 255))
    paper.putalpha(mask)
    return paper


def make_demo(name):
    details = DEMOS[name]
    rng = np.random.default_rng(details.seed)
    wall = backdrop(rng, name == 'flat')
    middle = screen(rng, name == 'flat')
    foreground = arch(rng)
    x = 302 if name == 'overlap' else 438
    placements = [((0, 0), wall), ((252, 91), middle), ((x, 133), foreground)]
    views = []
    for side in (0, 1):
        image = Image.new('RGBA', (WIDTH, HEIGHT))
        for ((left, top), layer), disparity in zip(placements, details.shifts):
            image.alpha_composite(layer, (left - side * disparity, top))
        views.append(np.array(image))
    return views


def demo_index():
    return [{'id': key, 'name': demo.name, 'details': demo.details} for key, demo in DEMOS.items()]
