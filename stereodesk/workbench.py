from functools import lru_cache


from .geometry import aligned_pair, guide_overlay, map_to_source, support_rectangle
from .imaging import (blend, cross_eye, diagnostic_preview, disparity_preview, load_image,
                      sample_report, simple_anaglyph, summary)
from .matching import estimate
from .profile import line_profile


def cache_key(values):
    return tuple(sorted(values.items()))


class Workbench:
    def __init__(self, store):
        self.store = store

    @lru_cache(maxsize=2)
    def source_pair(self, identifier):
        return tuple(load_image(self.store.image(identifier, eye)) for eye in ('left', 'right'))

    @lru_cache(maxsize=2)
    def _pair(self, identifier, alignment_key):
        return aligned_pair(*self.source_pair(identifier), dict(alignment_key))

    def pair(self, project):
        return self._pair(project['id'], cache_key(project['settings']['alignment']))

    @lru_cache(maxsize=2)
    def _match(self, identifier, alignment_key, matching_key):
        return estimate(self._pair(identifier, alignment_key), dict(matching_key))

    def match(self, project):
        settings = project['settings']
        return self._match(project['id'], cache_key(settings['alignment']), cache_key(settings['matching']))

    @lru_cache(maxsize=8)
    def _overlap(self, identifier, alignment_key):
        pair = self._pair(identifier, alignment_key)
        return {'shared_fraction': round(float(pair.shared_support.mean()), 4),
                'crop': support_rectangle(pair.shared_support)}

    def overlap(self, project):
        return self._overlap(project['id'], cache_key(project['settings']['alignment']))

    def render(self, project, mode):
        settings = project['settings']
        pair = self.pair(project)
        if mode == 'anaglyph':
            return simple_anaglyph(pair.left, pair.right, settings['display']['convergence'])
        if mode == 'cross':
            return cross_eye(pair.left, pair.right)
        if mode == 'blend':
            return blend(pair.left, pair.right)
        if mode in ('left-guide', 'right-guide'):
            color = (250, 210, 116, 255) if mode == 'left-guide' else (115, 217, 218, 255)
            image = pair.left if mode == 'left-guide' else pair.right
            return guide_overlay(image, settings['display']['guide'], color)
        if mode == 'disparity':
            return disparity_preview(self.match(project), settings['matching'])
        if mode == 'confidence':
            return diagnostic_preview(self.match(project))
        raise KeyError(mode)

    def inspect(self, project, x, y):
        settings = project['settings']
        pair = self.pair(project)
        report = sample_report(self.match(project), settings, x, y)
        right_x = report['right_x']
        if right_x is not None:
            report['right_source'] = map_to_source(pair.right_matrix, right_x, y)
        report['left_rgba'] = pair.left[y, x].tolist()
        report['x'] = x
        report['y'] = y
        return report

    def profile(self, project, start, end):
        return line_profile(self.match(project), project['settings'], start, end)

    def metrics(self, project):
        return {**summary(self.match(project)), **self.overlap(project)}
