from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import json
import re
import shutil
import tempfile
from threading import RLock
from uuid import uuid4
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

from image_lab.validation import Conflict, Invalid
from .imaging import load_image, png
from .settings import DEFAULTS, settings_patch, validate_search_width


ID = re.compile(r'[a-f0-9]{12}')
ARCHIVE_FILES = ('project.json', 'left.png', 'right.png')
MAX_ARCHIVE_FILE = 20 * 1024 * 1024


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def clean_title(value):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 80:
        raise Invalid('项目名不能为空，最多 80 个字符')
    return value.strip()


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path, value):
    data = json.dumps(value, ensure_ascii=False, indent=2)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as temporary:
        temporary.write(data)
        name = Path(temporary.name)
    try:
        name.replace(path)
    finally:
        name.unlink(missing_ok=True)


class Workspace:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()

    def directory(self, identifier):
        if not ID.fullmatch(identifier):
            raise Invalid('项目标识无效')
        root = self.root / identifier
        if not root.is_dir():
            raise Invalid('项目不存在')
        return root

    def project(self, identifier):
        return read_json(self.directory(identifier) / 'project.json')

    def projects(self):
        projects = [self.project(path.name) for path in self.root.iterdir()
                    if ID.fullmatch(path.name) and path.is_dir()]
        return sorted(projects, key=lambda item: (item['updated'], item['id']), reverse=True)

    def create(self, title, left, right, *, origin='导入照片', settings=None):
        if left.shape != right.shape:
            raise Invalid('请导入应用朝向后尺寸相同的左右照片')
        height, width = left.shape[:2]
        key = uuid4().hex[:12]
        settings = settings_patch(DEFAULTS, {} if settings is None else settings)
        validate_search_width(settings['matching'], width)
        data = {'id': key, 'title': clean_title(title), 'origin': origin,
                'size': [width, height], 'version': 1, 'created': timestamp(), 'updated': timestamp(),
                'settings': settings}
        directory = self.root / key
        temp = Path(tempfile.mkdtemp(prefix='.import-', dir=self.root))
        try:
            (temp / 'left.png').write_bytes(png(left))
            (temp / 'right.png').write_bytes(png(right))
            write_json(temp / 'project.json', data)
            temp.rename(directory)
        finally:
            if temp.exists():
                shutil.rmtree(temp)
        return data

    def image(self, identifier, eye):
        if eye not in ('left', 'right'):
            raise Invalid('请选择左眼或右眼')
        return self.directory(identifier) / f'{eye}.png'

    def apply(self, identifier, version, changes):
        with self.lock:
            directory = self.directory(identifier)
            current = self.project(identifier)
            if type(version) is not int or current['version'] != version:
                raise Conflict('项目已在其他窗口更新，请刷新后再调整')
            current['settings'] = settings_patch(current['settings'], changes)
            validate_search_width(current['settings']['matching'], current['size'][0])
            current['version'] += 1
            current['updated'] = timestamp()
            write_json(directory / 'project.json', current)
            return current

    def package(self, project):
        directory = self.directory(project['id'])
        buffer = BytesIO()
        with ZipFile(buffer, 'w', ZIP_DEFLATED) as archive:
            archive.writestr(ARCHIVE_FILES[0], json.dumps(project, ensure_ascii=False, indent=2))
            for name in ARCHIVE_FILES[1:]:
                archive.write(directory / name, name)
        return buffer.getvalue()

    def restore(self, stream, title=None):
        try:
            with ZipFile(stream) as archive:
                entries = archive.infolist()
                if sorted(e.filename for e in entries) != sorted(ARCHIVE_FILES):
                    raise Invalid('工程需要两张来源图和一份项目设置')
                if any(e.file_size > MAX_ARCHIVE_FILE for e in entries):
                    raise Invalid('工程中的照片或设置超过容量限制')
                if archive.getinfo('project.json').file_size > 32 * 1024:
                    raise Invalid('工程设置过大')
                data = json.loads(archive.read('project.json'))
                if not isinstance(data, dict) or not isinstance(data.get('settings'), dict):
                    raise Invalid('工程缺少有效的项目设置')
                left, right = (load_image(BytesIO(archive.read(name))) for name in ARCHIVE_FILES[1:])
        except (BadZipFile, UnicodeError, json.JSONDecodeError, ValueError, RuntimeError) as exc:
            if isinstance(exc, Invalid):
                raise
            raise Invalid('无法读取此工程 ZIP') from exc
        return self.create(title if title is not None else data.get('title'), left, right,
                           origin='恢复工程', settings=data['settings'])
