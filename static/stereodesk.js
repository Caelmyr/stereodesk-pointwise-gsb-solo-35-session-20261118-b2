const $ = id => document.getElementById(id);
const state = { project: null, mode: 'sources', point: null, metrics: null, line: null,
  profile: null, inspectSerial: 0, profileSerial: 0 };
const captions = {
  sources: '左右原片 · 点击左眼定位 · 对齐和视差处理保留原图',
  guides: '左右共用同一水平线 · 观察两眼对应结构的垂直偏移',
  blend: '两眼对齐后的半透明叠加',
  anaglyph: '红色取自左眼 · 青色取自右眼 · 使用当前会聚平移',
  cross: '右眼图在左侧 · 左眼图在右侧',
  disparity: '浅暖色为高视差 · 深色方格为无可靠匹配 · 点击测量',
  confidence: '绿 有效 / 灰 无支撑 / 紫 无视差 / 黄 低纹理 / 红 双向不一致',
  profile: '在左眼图上斜着拖出一条线 · 剖面按线两侧紧邻的同一片面取样 · 落差和不可靠处断开留空',
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

function drawLine() {
  $('view').querySelectorAll('.profile-line, .line-anchor').forEach(item => item.remove());
  const figure = $('view').querySelector('.line-picker')?.parentElement;
  if (!figure || !state.line) return;
  const [width, height] = state.project.size;
  const [start, end] = state.line;
  const percent = point => ({ left: `${(point[0] + .5) / width * 100}%`,
    top: `${(point[1] + .5) / height * 100}%` });
  const from = percent(start);
  const to = percent(end);
  const stroke = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  stroke.setAttribute('class', 'profile-line');
  stroke.setAttribute('viewBox', `0 0 ${width} ${height}`);
  stroke.setAttribute('preserveAspectRatio', 'none');
  const rule = document.createElementNS('http://www.w3.org/2000/svg', 'line');
  rule.setAttribute('x1', start[0]); rule.setAttribute('y1', start[1]);
  rule.setAttribute('x2', end[0]); rule.setAttribute('y2', end[1]);
  figure.append(stroke);
  stroke.append(rule);
  for (const [kind, spot] of [['start', from], ['end', to]]) {
    const mark = document.createElement('span');
    mark.className = `line-anchor ${kind}`;
    mark.style.left = spot.left;
    mark.style.top = spot.top;
    figure.append(mark);
  }
}

function profileFigure(image) {
  const figure = document.createElement('figure');
  figure.className = 'picture';
  const picker = document.createElement('img');
  picker.className = 'line-picker';
  picker.tabIndex = 0;
  picker.src = image;
  picker.alt = '左眼 · 拉出剖面线';
  let anchor = null;
  let previous = null;
  const toPixel = event => {
    const bounds = picker.getBoundingClientRect();
    const [width, height] = state.project.size;
    const x = Math.min(width - 1, Math.max(0, Math.round((event.clientX - bounds.left) / bounds.width * width)));
    const y = Math.min(height - 1, Math.max(0, Math.round((event.clientY - bounds.top) / bounds.height * height)));
    return [x, y];
  };
  const finish = () => {
    if (!state.line) return;
    const [start, end] = state.line;
    if (Math.hypot(end[0] - start[0], end[1] - start[1]) < 4) {
      state.line = previous;
      drawLine();
      if (state.line) void readProfile();
      else {
        $('profile-chart').replaceChildren();
        $('profile-readout').textContent = '在左眼图上斜着拖出一条剖面线，查看沿线的距离变化。';
      }
      message('剖面线太短，请在左眼图上重新拉一条。', true);
      return;
    }
    message('');
    previous = null;
    void readProfile();
  };
  picker.addEventListener('pointerdown', event => {
    event.preventDefault();
    picker.setPointerCapture(event.pointerId);
    anchor = toPixel(event);
    previous = state.line;
    state.line = [anchor, anchor];
    drawLine();
  });
  picker.addEventListener('pointermove', event => {
    if (!anchor) return;
    state.line = [anchor, toPixel(event)];
    drawLine();
  });
  picker.addEventListener('pointerup', () => {
    if (!anchor) return;
    anchor = null;
    finish();
  });
  picker.addEventListener('pointercancel', () => {
    anchor = null;
  });
  picker.addEventListener('keydown', event => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    event.preventDefault();
    const [width, height] = state.project.size;
    state.line = [[Math.round(width * .6), Math.round(height * .3)],
      [Math.round(width * .72), Math.round(height * .75)]];
    drawLine();
    void readProfile();
  });
  const label = document.createElement('figcaption');
  label.textContent = '左眼 · 拖动拉出剖面线';
  figure.append(picker, label);
  return figure;
}

function profileChart(report) {
  const figure = document.createElement('figure');
  figure.className = 'profile-chart';
  const caption = document.createElement('figcaption');
  caption.textContent = report.units === 'mm'
    ? '沿线距离剖面 · 毫米' : '沿线视差剖面 · 像素（未填标距）';
  const known = report.values.filter(value => value != null);
  if (!known.length) {
    const empty = document.createElement('p');
    empty.className = 'profile-empty';
    empty.textContent = '这条线上没有可靠匹配，剖面留空。';
    figure.append(caption, empty);
    return figure;
  }
  const width = 720;
  const height = 260;
  const pad = { left: 58, right: 16, top: 30, bottom: 34 };
  const low = Math.min(...known);
  const high = Math.max(...known);
  const span = high - low || Math.max(1, high * .02);
  const floor = low - span * .08;
  const ceiling = high + span * .08;
  const xAt = index => pad.left + index / Math.max(1, report.samples - 1) * (width - pad.left - pad.right);
  const yAt = value => pad.top + (1 - (value - floor) / (ceiling - floor)) * (height - pad.top - pad.bottom);
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', caption.textContent);
  const line = (x1, y1, x2, y2, className) => {
    const item = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    item.setAttribute('x1', x1); item.setAttribute('y1', y1);
    item.setAttribute('x2', x2); item.setAttribute('y2', y2);
    item.setAttribute('class', className);
    svg.append(item);
  };
  const text = (x, y, value, className, anchor = 'start') => {
    const item = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    item.setAttribute('x', x); item.setAttribute('y', y);
    item.setAttribute('class', className);
    item.setAttribute('text-anchor', anchor);
    item.textContent = value;
    svg.append(item);
  };
  for (let step = 0; step <= 4; step += 1) {
    const value = floor + (ceiling - floor) * step / 4;
    const y = yAt(value);
    line(pad.left, y, width - pad.right, y, 'profile-grid');
    text(pad.left - 8, y + 4, value.toFixed(report.units === 'mm' ? 0 : 1), 'profile-axis', 'end');
  }
  line(pad.left, pad.top, pad.left, height - pad.bottom, 'profile-axis-line');
  line(pad.left, height - pad.bottom, width - pad.right, height - pad.bottom, 'profile-axis-line');
  const total = Math.hypot(report.end[0] - report.start[0], report.end[1] - report.start[1]);
  text(pad.left, height - 10, '0', 'profile-axis', 'middle');
  text(width - pad.right, height - 10, `${Math.round(total)} px`, 'profile-axis', 'end');
  const marks = document.createElementNS('http://www.w3.org/2000/svg', 'g');
  for (const [from, to] of report.segments) {
    const group = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    for (let index = from + 1; index <= to; index += 1) {
      const value = report.values[index];
      const previous = report.values[index - 1];
      if (value == null || previous == null) continue;
      const item = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      item.setAttribute('x1', xAt(index - 1)); item.setAttribute('y1', yAt(previous));
      item.setAttribute('x2', xAt(index)); item.setAttribute('y2', yAt(value));
      item.setAttribute('class', 'profile-trace');
      group.append(item);
    }
    marks.append(group);
  }
  svg.append(marks);
  const breaks = report.disparity.reduce((count, value, index) =>
    count + (value == null && index > 0 && report.disparity[index - 1] != null ? 1 : 0), 0);
  text(pad.left, pad.top - 4, `${report.matched} / ${report.samples} 点有可靠匹配`, 'profile-note');
  if (breaks) {
    text(width - pad.right, pad.top - 4,
      `${breaks} 处断开（落差或不可靠处留空）`, 'profile-note', 'end');
  }
  figure.append(caption, svg);
  return { figure, breaks };
}

async function readProfile() {
  const active = state.project;
  if (!active || !state.line) return;
  const serial = ++state.profileSerial;
  const [start, end] = state.line;
  $('profile-readout').textContent = '沿剖面线取样…';
  drawLine();
  try {
    const [x0, y0] = start;
    const [x1, y1] = end;
    const search = new URLSearchParams({ v: active.version, start: `${x0},${y0}`, end: `${x1},${y1}` });
    const report = await api(`/projects/${active.id}/profile?${search}`);
    if (state.project !== active || state.profileSerial !== serial) return;
    state.profile = report;
    drawProfile();
  } catch (error) {
    if (state.project === active && state.profileSerial === serial) {
      state.profile = null;
      $('profile-chart').replaceChildren();
      $('profile-readout').textContent = error.message;
    }
  }
}

function drawProfile() {
  const report = state.profile;
  const holder = $('profile-chart');
  holder.replaceChildren();
  drawLine();
  if (!report) {
    $('profile-readout').textContent = '在左眼图上斜着拖出一条剖面线，查看沿线的距离变化。';
    return;
  }
  const [x0, y0] = report.start;
  const [x1, y1] = report.end;
  const known = report.values.filter(value => value != null);
  const highest = known.length ? Math.max(...known) : null;
  const lowest = known.length ? Math.min(...known) : null;
  const metric = report.units === 'mm';
  fillDefinitions($('profile-readout'), [
    ['剖面线', `(${x0}, ${y0}) → (${x1}, ${y1})`],
    ['采样', `${report.matched} / ${report.samples} 点`],
    ['连续段', `${report.segments.length} 段`],
    [metric ? '距离范围' : '视差范围', known.length
      ? `${lowest} – ${highest} ${metric ? 'mm' : 'px'}` : '—'],
    ['单位', metric ? '毫米 · 工程标距' : '像素 · 未填标距'],
  ]);
  if (report.unmatched_scale) {
    $('profile-readout').textContent =
      '线上的视差都在零点之内，按工程标距读不出距离；请检查「零点」或视差搜索设置。';
    $('profile-chart').replaceChildren();
    return;
  }
  const { figure, breaks } = profileChart(report);
  holder.append(figure);
  $('view-note').textContent = breaks
    ? `${captions.profile} · 这条线有 ${breaks} 处断开，落差和不可靠处保持留空`
    : captions.profile;
}

function drawPreview() {
  const mode = state.mode;
  const view = $('view');
  view.classList.toggle('double', mode === 'sources' || mode === 'guides');
  view.classList.toggle('profile', mode === 'profile');
  for (const button of $('modes').querySelectorAll('button')) {
    button.setAttribute('aria-pressed', String(button.dataset.mode === mode));
  }
  $('view-note').textContent = captions[mode];
  $('export-preview').hidden = mode === 'sources' || mode === 'guides' || mode === 'profile';
  $('profile-panel').hidden = mode !== 'profile';
  if (mode === 'sources') {
    view.replaceChildren(picture(projectURL('source/left.png'), '左眼 · 原片', true),
      picture(projectURL('source/right.png'), '右眼 · 原片', false));
  } else if (mode === 'guides') {
    view.replaceChildren(picture(projectURL('preview/left-guide.png'), '左眼 · 基准', true),
      picture(projectURL('preview/right-guide.png'), '右眼 · 校正', false));
  } else if (mode === 'profile') {
    view.replaceChildren(profileFigure(projectURL('source/left.png')));
    drawProfile();
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
  state.profileSerial += 1;
  if (!keepView) {
    state.mode = 'sources';
    state.point = null;
    state.line = null;
    state.profile = null;
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
  if (state.line) void readProfile();
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
