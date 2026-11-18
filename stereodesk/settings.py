from copy import deepcopy
from image_lab.validation import Invalid, number as read_number


DEFAULTS = {
    'alignment': {'dx': 0.0, 'dy': 0.0, 'angle': 0.0},
    'matching': {'minimum': 0, 'span': 48, 'window': 5, 'tolerance': 1.5, 'texture': 2.5},
    'scale': {'baseline_mm': 0.0, 'focal_px': 0.0, 'zero_offset': 0.0},
    'display': {'convergence': 0.0, 'guide': 0.5},
}
FIELDS = {
    'alignment': {'dx': (-256, 256), 'dy': (-160, 160), 'angle': (-20, 20)},
    'matching': {'minimum': (-64, 64), 'span': (16, 128), 'window': (3, 11),
                 'tolerance': (0.5, 4), 'texture': (0.0, 30)},
    'scale': {'baseline_mm': (0.0, 2000), 'focal_px': (0.0, 50000), 'zero_offset': (-256, 256)},
    'display': {'convergence': (-128, 128), 'guide': (0.0, 1.0)},
}
INTEGERS = {'minimum', 'span', 'window'}


def validate_section(key, values, current):
    bounds = FIELDS[key]
    if not isinstance(values, dict) or values.keys() - bounds.keys():
        raise Invalid('设置含有未知字段')
    section = dict(current)
    for field, raw in values.items():
        low, high = bounds[field]
        value = read_number(raw, field, minimum=low, maximum=high)
        if field in INTEGERS:
            if value != int(value):
                raise Invalid(f'{field} 需要整数')
            value = int(value)
        section[field] = value
    if key == 'matching':
        if section['span'] % 16 or section['window'] % 2 != 1:
            raise Invalid('视差跨度需为 16 的倍数，窗口需要奇数')
    if key == 'scale':
        baseline, focal = section['baseline_mm'], section['focal_px']
        if (baseline > 0) != (focal > 0):
            raise Invalid('标距需要同时填写相机基线和焦距')
    return section


def settings_patch(current, changes):
    if not isinstance(changes, dict) or changes.keys() - FIELDS.keys():
        raise Invalid('不能应用未知设置')
    updated = deepcopy(current)
    for key, values in changes.items():
        updated[key] = validate_section(key, values, current[key])
    return updated


def validate_search_width(matching, width):
    minimum, span, window = matching['minimum'], matching['span'], matching['window']
    if max(abs(minimum), abs(minimum + span)) + window + 20 >= width:
        raise Invalid('当前视差搜索范围相对图宽过大')


def report_length(d, scale):
    corrected = d - scale['zero_offset']
    if corrected <= 0 or not scale['baseline_mm']:
        return None
    return scale['baseline_mm'] * scale['focal_px'] / corrected
