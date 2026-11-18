const $ = id => document.getElementById(id);
const state = { project: null, mode: 'sources', point: null, metrics: null, inspectSerial: 0 };
const captions = {
  sources: '左右原片 · 点击左眼定位 · 对齐和视差处理保留原图',
  guides: '左右共用同一水平线 · 观察两眼对应结构的垂直偏移',
  blend: '两眼对齐后的半透明叠加',
  anaglyph: '红色取自左眼 · 青色取自右眼 · 使用当前会聚平移',
  cross: '右眼图在左侧 · 左眼图在右侧',
  disparity: '浅暖色为高视差 · 深色方格为无可靠匹配 · 点击测量',
  confidence: '绿 有效 / 灰 无支撑 / 紫 无视差 / 黄 低纹理 / 红 双向不一致',
};
const previewTitles = { blend: '叠加图', anaglyph: '红青预览', cross: '交叉观看图',
  disparity: '视差颜色图', confidence: '视差有效性图' };
const selectable = new Set(['sources', 'guides', 'disparity', 'confidence']);
const numberText = (value, unit = '') => value == null ? '—' : `${value}${unit}`;
const percentage = value => (100 * value).toFixed(1) + '%';

async function api(url, options) {
  const response = await fetch('/stereo' + url, options);
  const payload = await response.json().catch(() => null);
  if (!response.ok) throw new Error(payload?.error || `请求失败（${response.status}）`);
  return payload;
}

function message(value, failed = false) {
  $('message').textContent = value;
  $('message').classList.toggle('error', failed);
  $('message').hidden = !value;
}

function projectURL(suffix, query = {}) {
  const { id, version } = state.project;
  const params = new URLSearchParams({ v: version, ...query });
  return `/stereo/projects/${id}/${suffix}?${params}`;
}

function definitionList(rows) {
  const list = document.createElement('dl');
  for (const [label, value] of rows) {
    const title = document.createElement('dt');
    title.textContent = label;
    const item = document.createElement('dd');
    item.textContent = value;
    list.append(title, item);
  }
  return list;
}

function fillDefinitions(parent, rows) {
  const values = definitionList(rows);
  if (parent.tagName === 'DL') parent.replaceChildren(...values.children);
  else parent.replaceChildren(values);
}

function picture(url, caption, isSelectable) {
  const figure = document.createElement('figure');
  figure.className = 'picture';
  const image = document.createElement('img');
  image.src = url;
  image.alt = caption;
  image.addEventListener('error', () => {
    if (figure.isConnected) message('这张预览无法生成，请检查工程设置。', true);
  });
  if (isSelectable) {
    image.tabIndex = 0;
    image.className = 'inspectable';
    image.addEventListener('click', event => {
      const bounds = image.getBoundingClientRect();
      placePoint((event.clientX - bounds.left) / bounds.width, (event.clientY - bounds.top) / bounds.height);
    });
    image.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        placePoint(0.5, 0.5);
      }
    });
  }
  const label = document.createElement('figcaption');
  label.textContent = caption;
  figure.append(image, label);
  return figure;
}

function drawPointer() {
  $('view').querySelectorAll('.pointer').forEach(item => item.remove());
  const figure = $('view').querySelector('.inspectable')?.parentElement;
  if (!figure || !state.point) return;
  const [width, height] = state.project.size;
  const mark = document.createElement('span');
  mark.className = 'pointer';
  mark.style.left = `${(state.point.x + .5) / width * 100}%`;
  mark.style.top = `${(state.point.y + .5) / height * 100}%`;
  figure.append(mark);
}

function drawPreview() {
  const mode = state.mode;
  const view = $('view');
  view.classList.toggle('double', mode === 'sources' || mode === 'guides');
  for (const button of $('modes').querySelectorAll('button')) {
    button.setAttribute('aria-pressed', String(button.dataset.mode === mode));
  }
  $('view-note').textContent = captions[mode];
  $('export-preview').hidden = mode === 'sources' || mode === 'guides';
  if (mode === 'sources') {
    view.replaceChildren(picture(projectURL('source/left.png'), '左眼 · 原片', true),
      picture(projectURL('source/right.png'), '右眼 · 原片', false));
  } else if (mode === 'guides') {
    view.replaceChildren(picture(projectURL('preview/left-guide.png'), '左眼 · 基准', true),
      picture(projectURL('preview/right-guide.png'), '右眼 · 校正', false));
  } else {
    view.replaceChildren(picture(projectURL(`preview/${mode}.png`), previewTitles[mode], selectable.has(mode)));
    $('export-preview').href = projectURL(`export/${mode}.png`);
  }
  drawPointer();
}

async function readPoint(x, y) {
  const serial = ++state.inspectSerial;
  const active = state.project;
  $('point-readout').textContent = `测量 (${x}, ${y})…`;
  try {
    const search = new URLSearchParams({ v: active.version, x, y });
    const point = await api(`/projects/${active.id}/inspect?${search}`);
    if (state.project !== active || state.inspectSerial !== serial) return;
    fillDefinitions($('point-readout'), [
      ['左眼坐标', `${x}, ${y}`],
      ['右眼原片', point.right_source?.join(', ') || '—'],
      ['视差', numberText(point.disparity, ' px')],
      ['估计距离', numberText(point.distance_mm, ' mm')],
      ['可信度', point.valid ? percentage(point.confidence) : point.reason],
    ]);
  } catch (error) {
    if (state.project === active && state.inspectSerial === serial) $('point-readout').textContent = error.message;
  }
}

function setRowLink() {
  $('export-row').href = projectURL('export/row.csv', state.point ? { y: state.point.y } : {});
  $('export-row').textContent = state.point ? `下载第 ${state.point.y} 行 CSV` : '下载中间行 CSV';
}

function placePoint(rx, ry) {
  const [width, height] = state.project.size;
  const x = Math.min(width - 1, Math.max(0, Math.floor(rx * width)));
  const y = Math.min(height - 1, Math.max(0, Math.floor(ry * height)));
  state.point = { x, y };
  drawPointer();
  setRowLink();
  void readPoint(x, y);
}

async function readOverlap(project) {
  try {
    const info = await api(`/projects/${project.id}/overlap?v=${project.version}`);
    if (state.project !== project) return;
    const [x0, y0, x1, y1] = info.crop;
    fillDefinitions($('overlap-readout'), [
      ['共同支撑', percentage(info.shared_fraction)],
      ['共同裁切图', `${x1 - x0} × ${y1 - y0} px`],
    ]);
    $('export-aligned').hidden = x1 <= x0 || y1 <= y0;
  } catch (error) {
    if (state.project === project) $('overlap-readout').textContent = error.message;
  }
}

async function readMetrics() {
  const project = state.project;
  if (state.metrics === project) return;
  state.metrics = project;
  $('metrics-readout').textContent = '计算中…';
  try {
    const report = await api(`/projects/${project.id}/metrics?v=${project.version}`);
    if (state.project !== project) return;
    fillDefinitions($('metrics-readout'), [
      ['可信像素', report.valid_pixels.toLocaleString()],
      ['覆盖率', percentage(report.coverage)],
      ['视差中位数', numberText(report.median_disparity, ' px')],
      ['视差 5–95%', report.percentiles ? report.percentiles.join(' – ') + ' px' : '—'],
      ...Object.entries(report.reasons).map(([reason, count]) => [reason, count.toLocaleString()]),
    ]);
  } catch (error) {
    if (state.project === project) {
      state.metrics = null;
      $('metrics-readout').textContent = error.message;
    }
  }
}

function refresh(project, keepView = false) {
  state.project = project;
  state.metrics = null;
  if (!keepView) {
    state.mode = 'sources';
    state.point = null;
  }
  $('empty').hidden = true;
  $('controls').hidden = false;
  $('active').hidden = false;
  $('project-title').textContent = project.title;
  $('source-kind').textContent = project.origin;
  $('project-detail').textContent = project.origin + ' · ' + project.size.join(' × ') + ' px';
  $('revision').textContent = `修订 ${project.version}`;
  for (const fieldset of $('settings-form').querySelectorAll('[data-section]')) {
    for (const control of fieldset.querySelectorAll('input')) {
      control.value = project.settings[fieldset.dataset.section][control.name];
    }
  }
  $('export-project').href = projectURL('export/project.zip');
  $('export-aligned').href = projectURL('export/aligned.zip');
  $('export-aligned').hidden = true;
  $('export-disparity').href = projectURL('export/disparity.npy');
  $('overlap-readout').textContent = '计算中…';
  $('metrics-readout').textContent = '打开视差图或点击计算。';
  $('point-readout').textContent = '点击左原片、视差图或可信区定位测量点。';
  setRowLink();
  drawPreview();
  void readOverlap(project);
  if (['disparity', 'confidence'].includes(state.mode)) void readMetrics();
  if (state.point) void readPoint(state.point.x, state.point.y);
}

async function loadLibrary() {
  const info = await api('/projects');
  const list = $('project-list');
  list.replaceChildren(new Option('选择已保存工程', ''));
  for (const entry of info.projects) list.append(new Option(entry.title, entry.id));
  list.value = state.project?.id || '';
  $('demos').replaceChildren(...info.demos.map(demo => {
    const button = document.createElement('button');
    button.className = 'demo';
    button.type = 'button';
    button.title = demo.details;
    button.textContent = demo.name;
    button.addEventListener('click', () => void loadDemo(demo.id, button));
    return button;
  }));
}

async function newProject(button, prepare) {
  button.disabled = true;
  message('正在打开照片对…');
  try {
    refresh(await prepare());
    message('');
    await loadLibrary();
  } catch (error) {
    message(error.message, true);
  } finally {
    button.disabled = false;
  }
}

function loadDemo(name, button) {
  return newProject(button, () => api('/demos/' + name, { method: 'POST' }));
}

function addUpload(form, route) {
  form.addEventListener('submit', event => {
    event.preventDefault();
    const body = new FormData(form);
    void newProject(event.submitter, () => api(route, { method: 'POST', body }));
  });
}

addUpload($('upload-form'), '/import');
addUpload($('restore-form'), '/restore');
$('quick-demo').addEventListener('click', event => void loadDemo('studio', event.currentTarget));
$('project-list').addEventListener('change', async event => {
  const id = event.target.value;
  if (!id) return;
  try {
    const project = await api('/projects/' + id);
    refresh(project);
    message('');
  } catch (error) {
    message(error.message, true);
  }
});
$('modes').addEventListener('click', event => {
  const button = event.target.closest('button[data-mode]');
  if (!button || !state.project) return;
  state.mode = button.dataset.mode;
  drawPreview();
  if (['disparity', 'confidence'].includes(state.mode)) void readMetrics();
});
$('analyze').addEventListener('click', () => void readMetrics());
$('settings-form').addEventListener('submit', async event => {
  event.preventDefault();
  const active = state.project;
  const button = event.submitter;
  button.disabled = true;
  const changes = {};
  for (const fieldset of event.currentTarget.querySelectorAll('[data-section]')) {
    const section = {};
    for (const input of fieldset.querySelectorAll('input')) section[input.name] = input.valueAsNumber;
    changes[fieldset.dataset.section] = section;
  }
  try {
    const project = await api('/projects/' + active.id, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ version: active.version, changes }),
    });
    if (state.project === active) {
      refresh(project, true);
      message('当前照片对设置已保存。');
    }
  } catch (error) {
    if (state.project === active) message(error.message, true);
  } finally {
    button.disabled = false;
  }
});
loadLibrary().catch(error => message(error.message, true));
