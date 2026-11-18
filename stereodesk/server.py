from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile
import json

from flask import Blueprint, jsonify, redirect, render_template, request, send_file

from image_lab.validation import Conflict, Invalid
from .demos import DEMOS, demo_index, make_demo
from .geometry import extract_pair
from .imaging import disparity_numpy, load_image, png, row_csv
from .storage import Workspace
from .workbench import Workbench


PREVIEWS = {'anaglyph', 'cross', 'blend', 'left-guide', 'right-guide', 'disparity', 'confidence'}
CUTOUT_KINDS = {'object.png', 'object-preview.png', 'cutout.json'}


def required_file(name):
    file = request.files.get(name)
    if file is None or not file.filename:
        raise Invalid('请选择需要导入的文件')
    return file.stream


def required_json():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise Invalid('请发送 JSON 对象')
    return data


def response(data, mimetype, filename=None):
    return send_file(BytesIO(data), mimetype=mimetype, as_attachment=filename is not None,
                     download_name=filename, max_age=0)


def int_query(key, minimum, maximum, fallback=None):
    raw = request.args.get(key)
    if raw is None and fallback is not None:
        return fallback
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise Invalid(f'{key} 必须是整数坐标') from exc
    if not minimum <= value <= maximum:
        raise Invalid('坐标超出当前图片')
    return value


def register(app, root):
    store = Workspace(root)
    desk = Workbench(store)
    stereo = Blueprint('stereo', __name__, url_prefix='/stereo')

    def current(identifier):
        project = store.project(identifier)
        requested = request.args.get('v')
        if requested is not None and str(project['version']) != requested:
            raise Conflict('预览修订已变更，请重新打开此工程')
        return project

    def point(project):
        width, height = project['size']
        return int_query('x', 0, width - 1), int_query('y', 0, height - 1)

    def cutout_export(project, kind):
        x, y = point(project)
        item = desk.cutout(project, x, y)
        if kind == 'cutout.json':
            return jsonify({**item.report(), 'x': x, 'y': y})
        image = item.rgba if kind == 'object.png' else desk.cutout_preview(project, x, y)
        return response(png(image), 'image/png', f'stereodesk-object-{x}-{y}.png')

    @app.get('/')
    def home():
        return redirect('/stereo/')

    @stereo.get('/')
    def index():
        return render_template('stereodesk.html')

    @stereo.get('/health')
    def health():
        return jsonify({'ok': True, 'workspace': 'StereoDesk'})

    @stereo.get('/projects')
    def projects():
        return jsonify({'projects': store.projects(), 'demos': demo_index()})

    @stereo.post('/import')
    def import_project():
        left = load_image(required_file('left'))
        right = load_image(required_file('right'))
        data = store.create(request.form.get('title', '未命名照片对'), left, right)
        return jsonify(data), 201

    @stereo.post('/demos/<name>')
    def demo_project(name):
        if name not in DEMOS:
            raise Invalid('此演示不存在')
        left, right = make_demo(name)
        metadata = DEMOS[name]
        data = store.create(metadata.name, left, right, origin='合成演示',
                            settings={'scale': {'baseline_mm': 66, 'focal_px': 620}})
        return jsonify(data), 201

    @stereo.post('/restore')
    def restore_project():
        return jsonify(store.restore(required_file('archive'), request.form.get('title'))), 201

    @stereo.get('/projects/<identifier>')
    def get_project(identifier):
        return jsonify(current(identifier))

    @stereo.patch('/projects/<identifier>')
    def patch_project(identifier):
        data = required_json()
        return jsonify(store.apply(identifier, data.get('version'), data.get('changes')))

    @stereo.get('/projects/<identifier>/source/<eye>.png')
    def source_image(identifier, eye):
        current(identifier)
        return send_file(store.image(identifier, eye), mimetype='image/png', max_age=0)

    @stereo.get('/projects/<identifier>/preview/<mode>.png')
    def preview(identifier, mode):
        if mode not in PREVIEWS:
            raise Invalid('当前预览模式不可用')
        return response(png(desk.render(current(identifier), mode)), 'image/png')

    @stereo.get('/projects/<identifier>/metrics')
    def metrics(identifier):
        return jsonify(desk.metrics(current(identifier)))

    @stereo.get('/projects/<identifier>/overlap')
    def overlap(identifier):
        return jsonify(desk.overlap(current(identifier)))

    @stereo.get('/projects/<identifier>/inspect')
    def inspect(identifier):
        project = current(identifier)
        width, height = project['size']
        x = int_query('x', 0, width - 1)
        y = int_query('y', 0, height - 1)
        return jsonify(desk.inspect(project, x, y))

    @stereo.get('/projects/<identifier>/cutout')
    def cutout_report(identifier):
        project = current(identifier)
        x, y = point(project)
        return jsonify(desk.cutout(project, x, y).report())

    @stereo.get('/projects/<identifier>/export/<kind>')
    def export(identifier, kind):
        project = current(identifier)
        if kind == 'project.zip':
            return response(store.package(project), 'application/zip', 'stereodesk-project.zip')
        if kind == 'aligned.zip':
            pair = desk.pair(project)
            left, right, crop = extract_pair(pair.left, pair.right, pair.shared_support)
            buf = BytesIO()
            with ZipFile(buf, 'w', ZIP_DEFLATED) as archive:
                archive.writestr('left.png', png(left))
                archive.writestr('right.png', png(right))
                archive.writestr('crop.json', json.dumps({'canvas': project['size'], 'bounds': crop}))
            return response(buf.getvalue(), 'application/zip', 'stereodesk-aligned.zip')
        if kind == 'disparity.npy':
            return response(disparity_numpy(desk.match(project)), 'application/octet-stream', kind)
        if kind == 'row.csv':
            height = project['size'][1]
            y = int_query('y', 0, height - 1, height // 2)
            return response(row_csv(desk.match(project), project['settings'], y), 'text/csv', kind)
        if kind in CUTOUT_KINDS:
            return cutout_export(project, kind)
        if kind.endswith('.png') and kind[:-4] in PREVIEWS:
            return response(png(desk.render(project, kind[:-4])), 'image/png', kind)
        raise Invalid('无法识别此导出类型')

    app.register_blueprint(stereo)
