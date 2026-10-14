/* ============================================================
   秋白去水印 · 前端逻辑
   - 单文件/批量 队列模式
   - 单文件：框选 → 处理
   - 批量：复用最近 box 串行处理所有 pending
   ============================================================ */

const $ = (id) => document.getElementById(id);

const els = {
  dropzone: $('dropzone'),
  fileInput: $('file-input'),
  uploadStatus: $('upload-status'),
  stepUpload: $('step-upload'),
  stepSelect: $('step-select'),
  stepResult: $('step-result'),
  stepHistory: $('step-history'),
  videoBox: $('video-box'),
  video: $('video'),
  overlay: $('video-overlay'),
  selection: $('selection'),
  btnPlay: $('btn-play'),
  btnClear: $('btn-clear'),
  selInfo: $('sel-info'),
  methodSel: $('method'),
  radiusInput: $('radius'),
  radiusVal: $('radius-val'),
  resultVideo: $('result-video'),
  resultMeta: $('result-meta'),
  btnSaveAs: $('btn-save-as'),
  btnRestart: $('btn-restart'),
  historyList: $('history-list'),
  historyEmpty: $('history-empty'),
  historyCount: $('history-count'),
  toastHost: $('toast-host'),
  // 队列
  queueWrap: $('queue-wrap'),
  queueList: $('queue-list'),
  queueTitle: $('queue-title'),
  queueProgress: $('queue-progress'),
  btnBatchProcess: $('btn-batch-process'),
  btnSaveAll: $('btn-save-all'),
  btnQueueClear: $('btn-queue-clear'),
  btnHistorySaveAll: $('btn-history-save-all'),
  // nav
  appNav: $('app-nav'),
  // 预览
  previewModal: $('preview-modal'),
  previewVideo: $('preview-video'),
  previewCaption: $('preview-caption'),
};

let state = {
  // 视图：home / history
  view: 'home',
  // 队列
  queue: [],
  // 当前单文件
  currentId: null,
  selectionNorm: null,
  // 共享 box
  sharedBox: null,
  sharedMethod: 'telea',
  sharedRadius: 3,
  // 当前结果
  resultId: null,
  resultUrl: null,
  // 防重入
  batchRunning: false,
  // 选框模式
  selectMode: null,
};
const STATUS_LABEL = {
  pending: '待框选',
  boxed: '已框选',
  processing: '处理中',
  done: '已完成',
  error: '失败',
};

// =========================================================
// Toast
// =========================================================
function toast(msg, type = '', opts = {}) {
  if (opts.dismissAll) dismissAllToasts();
  const el = document.createElement('div');
  el.className = 'toast' + (type ? ' ' + type : '');
  el.textContent = msg;
  els.toastHost.appendChild(el);
  setTimeout(() => {
    el.style.transition = 'opacity .3s, transform .3s';
    el.style.opacity = '0';
    el.style.transform = 'translateY(8px)';
    setTimeout(() => el.remove(), 300);
  }, 2400);
}

function dismissAllToasts() {
  els.toastHost.querySelectorAll('.toast').forEach(el => {
    el.style.transition = 'opacity .15s, transform .15s';
    el.style.opacity = '0';
    el.style.transform = 'translateY(8px)';
    setTimeout(() => el.remove(), 160);
  });
}

// =========================================================
// 队列操作
// =========================================================
function addToQueue(item) {
  state.queue.push({
    id: item.id,
    filename: item.filename,
    src: item.src,
    thumbUrl: item.thumbUrl || null,
    info: item.info,
    status: 'pending',
    box: null,
    method: null,
    radius: null,
    progress: 0,
    resultUrl: null,
    resultId: null,
    error: null,
  });
}

function removeFromQueue(id) {
  state.queue = state.queue.filter(q => q.id !== id);
  if (state.currentId === id) {
    state.currentId = null;
    state.selectionNorm = null;
  }
}

function clearQueue() {
  if (state.batchRunning) { toast('生成中，无法清空', 'warn'); return; }
  const n = state.queue.length;
  state.queue = [];
  state.currentId = null;
  state.selectionNorm = null;
  state.sharedBox = null;
  // 也清掉上传/状态条（避免"成功添加 N 个"残留）
  els.uploadStatus.classList.add('hidden');
  els.uploadStatus.textContent = '';
  renderQueue();
  // 立即清掉所有残留 toast，再显示自己的
  dismissAllToasts();
  if (n > 0) toast(`已清空 ${n} 个文件`, 'ok');
}

function getQueueItem(id) {
  return state.queue.find(q => q.id === id);
}

function updateQueueItem(id, patch) {
  const q = getQueueItem(id);
  if (!q) return;
  Object.assign(q, patch);
  renderQueue();
}

function renderQueue() {
  if (state.queue.length === 0) {
    els.queueWrap.classList.add('hidden');
    return;
  }
  els.queueWrap.classList.remove('hidden');
  const total = state.queue.length;
  const done = state.queue.filter(q => q.status === 'done').length;
  const err = state.queue.filter(q => q.status === 'error').length;
  els.queueTitle.textContent = `队列 · ${total} 个文件`;
  els.queueProgress.textContent = done > 0 || err > 0 ? `${done} 完成${err > 0 ? ` · ${err} 失败` : ''}` : '';

  // 批量按钮：至少一个 boxed 项 + 没在批处理
  const boxedItems = state.queue.filter(q => q.status === 'boxed');
  els.btnBatchProcess.disabled = boxedItems.length === 0 || state.batchRunning;
  els.btnBatchProcess.innerHTML = state.batchRunning
    ? '<span class="ico">⏳</span> 生成中…'
    : `<span class="ico">▶</span> 开始生成${boxedItems.length > 0 ? ` (${boxedItems.length})` : ''}`;
  // 全部下载：至少 1 个 done
  const doneItems = state.queue.filter(q => q.status === 'done');
  if (els.btnSaveAll) {
    els.btnSaveAll.disabled = doneItems.length === 0;
    els.btnSaveAll.innerHTML = `<span class="ico">⤓</span> 全部下载 (${doneItems.length})`;
  }

  els.queueList.innerHTML = '';
  state.queue.forEach(q => {
    const li = document.createElement('li');
    li.className = 'queue-item ' + q.status;
    const sizeMB = q.info?.size ? (q.info.size / 1024 / 1024).toFixed(1) : '';
    const dur = q.info?.duration ? q.info.duration.toFixed(1) : '?';
    const dim = q.info ? `${q.info.width}×${q.info.height}` : '';
    li.innerHTML = `
      <div class="queue-thumb">${q.thumbUrl ? `<img src="${q.thumbUrl}" alt="" loading="lazy">` : ''}</div>
      <div class="queue-meta">
        <div class="name">${escapeHtml(q.filename)}</div>
        <div class="info">${dim} · ${dur}s · ${sizeMB} MB</div>
        ${q.status === 'processing' ? `<div class="queue-progress-bar"><div style="width:${q.progress}%"></div></div>` : ''}
        ${q.error ? `<div class="info" style="color:var(--err)">${escapeHtml(q.error)}</div>` : ''}
      </div>
      <span class="queue-status ${q.status}">${STATUS_LABEL[q.status] || q.status}</span>
      <div class="queue-item-actions">
        ${q.status === 'pending' || q.status === 'error' ? `<button data-act="select" data-id="${q.id}" title="框选水印"><span class="ico">✎</span></button>` : ''}
        ${q.status === 'boxed' ? `<button data-act="select" data-id="${q.id}" title="重新框选"><span class="ico">✎</span></button>` : ''}
        ${q.status === 'boxed' && state.queue.length > 1 ? `<button data-act="apply-all" data-id="${q.id}" title="用此位置同步框选所有文件"><span class="ico">⤢</span> 应用到全部</button>` : ''}
        ${q.status === 'done' ? `<button data-act="view" data-id="${q.id}" title="预览"><span class="ico">👁</span></button>` : ''}
        ${q.status === 'done' ? `<button data-act="save" data-id="${q.id}" title="保存到…"><span class="ico">⤓</span></button>` : ''}
        <button data-act="del" data-id="${q.id}" title="移除" class="danger"><span class="ico">✕</span></button>
      </div>
    `;
    li.querySelector('[data-act=select]')?.addEventListener('click', e => { e.stopPropagation(); selectItem(q.id); });
    li.querySelector('[data-act=view]')?.addEventListener('click', e => { e.stopPropagation(); viewItem(q.id); });
    li.querySelector('[data-act=save]')?.addEventListener('click', e => { e.stopPropagation(); saveItem(q.id); });
    li.querySelector('[data-act=del]')?.addEventListener('click', e => { e.stopPropagation(); removeItem(q.id); });
    // "应用到全部"按钮：把此行的 box 同步到所有其他项
    li.querySelector('[data-act=apply-all]')?.addEventListener('click', e => {
      e.stopPropagation();
      applyBoxToAll(q.id);
    });
    // 双击或点击 thumb → 选中
    li.querySelector('.queue-thumb')?.addEventListener('click', () => selectItem(q.id));
    els.queueList.appendChild(li);
  });
}

// 把 sourceId 的 box 同步到所有其他项（含已 boxed 的）
function applyBoxToAll(sourceId) {
  const src = getQueueItem(sourceId);
  if (!src || !src.box) return;
  let count = 0;
  for (const q of state.queue) {
    if (q.id === sourceId) continue;
    if (q.status === 'done' || q.status === 'processing') continue;
    q.box = { ...src.box };
    q.method = src.method;
    q.radius = src.radius;
    if (q.status === 'pending' || q.status === 'error') q.status = 'boxed';
    count++;
  }
  renderQueue();
  toast(`已应用 ${src.filename} 的 box 到其他 ${count} 个文件`, 'ok');
}

function selectItem(id) {
  const q = getQueueItem(id);
  if (!q) return;
  if (q.status === 'processing') { toast('正在处理中', 'warn'); return; }
  if (q.status === 'done') { toast('已完成，可直接查看', ''); return; }
  state.currentId = id;
  state.selectionNorm = null;
  state.selectMode = 'box';  // 标记：选框后自动返回
  setupSelect(q);
  // 显示提示：选完会自动返回
  els.selInfo.textContent = '拖动鼠标框选水印，松开后自动保存并返回';
}

function viewItem(id) {
  const q = getQueueItem(id);
  if (!q || q.status !== 'done') return;
  openPreview(q.id, 'queue');
}

function saveItem(id) {
  const q = getQueueItem(id);
  if (!q || q.status !== 'done') return;
  state.resultId = q.id;
  doSaveAs(q);
}

function removeItem(id) {
  removeFromQueue(id);
  renderQueue();
}

els.btnQueueClear.addEventListener('click', clearQueue);

// 队列/历史 共用"全部下载"逻辑
async function doSaveAll(ids, label = '') {
  if (!ids || ids.length === 0) { toast('没有可下载的文件', 'warn'); return; }
  try {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.save_all) {
      const r = await window.pywebview.api.save_all(ids);
      if (!r) { toast('已取消', ''); return; }
      if (r.count > 0) {
        toast(`已保存 ${r.count} 个文件到 ${r.dir}${label ? ' · ' + label : ''}`, 'ok');
      } else {
        toast('保存失败：无有效文件', 'err');
      }
    } else {
      // 浏览器 fallback：逐个下载
      for (const id of ids) {
        const a = document.createElement('a');
        a.href = `/api/history/${id}/download`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        await new Promise(r => setTimeout(r, 200));
      }
      toast(`已触发 ${ids.length} 个下载`, 'ok');
    }
  } catch (e) {
    toast('全部下载失败：' + e.message, 'err');
  }
}

if (els.btnSaveAll) {
  els.btnSaveAll.addEventListener('click', () => {
    const ids = state.queue.filter(q => q.status === 'done').map(q => q.id);
    doSaveAll(ids, '队列');
  });
}
if (els.btnHistorySaveAll) {
  els.btnHistorySaveAll.addEventListener('click', () => {
    const ids = Array.from(els.historyList.querySelectorAll('[data-act=save]'))
      .map(b => b.dataset.id);
    doSaveAll(ids, '历史');
  });
}

// =========================================================
// 步骤导航
// =========================================================
function showStep(step) {
  for (const k of ['stepUpload', 'stepSelect', 'stepResult']) {
    els[k].classList.add('hidden');
  }
  els['step' + step].classList.remove('hidden');
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

// view 路由（home / history）
function showView(view) {
  state.view = view;
  // 隐藏所有 step
  for (const k of ['stepUpload', 'stepSelect', 'stepResult', 'stepHistory']) {
    els[k].classList.add('hidden');
  }
  if (view === 'home') {
    // 默认显示 upload
    if (state.resultUrl && state.resultId) showStep('Result');
    else showStep('Upload');
  } else if (view === 'history') {
    els.stepHistory.classList.remove('hidden');
    loadHistory();
  }
  // nav 状态
  els.appNav.querySelectorAll('.nav-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.view === view);
  });
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

els.appNav.addEventListener('click', e => {
  const btn = e.target.closest('.nav-btn');
  if (!btn) return;
  showView(btn.dataset.view);
});

function goHome() {
  state.currentId = null;
  state.selectionNorm = null;
  state.resultId = null;
  state.resultUrl = null;
  els.resultVideo.removeAttribute('src');
  els.resultVideo.load();
  els.selection.classList.add('hidden');
  showStep('Upload');
  renderQueue();
  loadHistory();
}

// =========================================================
// 1. 上传（单/多）
// =========================================================
els.dropzone.addEventListener('click', () => els.fileInput.click());
els.fileInput.addEventListener('change', () => {
  if (els.fileInput.files.length) handleFiles(els.fileInput.files);
});
['dragover', 'dragenter'].forEach(ev => els.dropzone.addEventListener(ev, e => {
  e.preventDefault(); els.dropzone.classList.add('drag');
}));
['dragleave', 'drop'].forEach(ev => els.dropzone.addEventListener(ev, e => {
  e.preventDefault(); els.dropzone.classList.remove('drag');
}));
els.dropzone.addEventListener('drop', e => {
  if (e.dataTransfer.files.length) handleFiles(e.dataTransfer.files);
});

async function handleFiles(fileList) {
  const files = Array.from(fileList).filter(f => f.type.startsWith('video/'));
  if (files.length === 0) { toast('请选择视频文件', 'err'); return; }
  els.uploadStatus.className = 'status';
  els.uploadStatus.classList.remove('hidden');
  els.uploadStatus.textContent = `正在上传 ${files.length} 个文件…`;
  const fd = new FormData();
  files.forEach(f => fd.append('video', f));
  try {
    const res = await fetch('/api/upload', { method: 'POST', body: fd });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || '上传失败');
    // 单文件：data.id；多文件：data.items
    const items = data.items || [{ id: data.id, filename: data.filename || files[0].name, src: data.src, info: data.info }];
    items.forEach(it => {
      if (it.id) addToQueue(it);
    });
    const okCount = items.filter(it => it.id).length;
    const errCount = items.length - okCount;
    els.uploadStatus.textContent = errCount > 0
      ? `✓ ${okCount} 个成功 · ✕ ${errCount} 个失败`
      : `✓ 成功添加 ${okCount} 个文件到队列`;
    els.fileInput.value = '';
    renderQueue();
    if (errCount > 0) toast(`${errCount} 个文件失败`, 'err');
    else toast(`已添加 ${okCount} 个文件`, 'ok');
  } catch (e) {
    els.uploadStatus.classList.add('err');
    els.uploadStatus.textContent = '✕ ' + e.message;
    toast(e.message, 'err');
  }
}

// =========================================================
// 2. 单文件框选
// =========================================================
function setupSelect(q) {
  showStep('Select');
  els.video.src = q.src;
  els.video.load();
  state.selectionNorm = null;
  resetSelection();
  els.video.onloadedmetadata = () => {
    els.video.currentTime = Math.min(0.5, (q.info.duration || 0) / 2);
  };
}

els.videoBox.addEventListener('mouseenter', () => els.overlay.classList.remove('hidden'));
els.videoBox.addEventListener('mouseleave', () => els.overlay.classList.add('hidden'));

els.overlay.addEventListener('mousedown', startSelect);
els.overlay.addEventListener('touchstart', e => startSelect(e, true), { passive: false });

let dragging = false, startX = 0, startY = 0;

function getVideoRect() { return els.video.getBoundingClientRect(); }

function startSelect(e, isTouch) {
  if (isTouch) e.preventDefault();
  dragging = true;
  const rect = getVideoRect();
  const pt = getPoint(e, isTouch);
  startX = clamp(pt.x - rect.left, 0, rect.width);
  startY = clamp(pt.y - rect.top, 0, rect.height);
  els.selection.classList.remove('hidden');
  updateSel(startX, startY);
  e.preventDefault();
  const move = ev => {
    if (!dragging) return;
    const p = getPoint(ev, isTouch);
    updateSel(startX, startY, p.x - rect.left, p.y - rect.top);
  };
  const up = () => { dragging = false; finalize(); cleanup(); };
  const cleanup = () => {
    document.removeEventListener('mousemove', move);
    document.removeEventListener('mouseup', up);
    document.removeEventListener('touchmove', move);
    document.removeEventListener('touchend', up);
  };
  document.addEventListener('mousemove', move);
  document.addEventListener('mouseup', up);
  document.addEventListener('touchmove', move, { passive: false });
  document.addEventListener('touchend', up);
}

function getPoint(e, isTouch) {
  if (isTouch) {
    e.preventDefault();
    const t = e.touches[0];
    return { x: t.clientX, y: t.clientY };
  }
  return { x: e.clientX, y: e.clientY };
}

function clamp(v, lo, hi) { return Math.min(Math.max(v, lo), hi); }

function updateSel(x1, y1, x2, y2) {
  const rect = getVideoRect();
  if (x2 === undefined) { x2 = x1; y2 = y1; }
  const l = Math.min(x1, x2), t = Math.min(y1, y2);
  const r = Math.max(x1, x2), b = Math.max(y1, y2);
  els.selection.style.left = l + 'px';
  els.selection.style.top = t + 'px';
  els.selection.style.width = (r - l) + 'px';
  els.selection.style.height = (b - t) + 'px';
}

function finalize() {
  const rect = getVideoRect();
  const l = parseFloat(els.selection.style.left);
  const t = parseFloat(els.selection.style.top);
  const w = parseFloat(els.selection.style.width);
  const h = parseFloat(els.selection.style.height);
  if (w < 5 || h < 5) { resetSelection(); return; }
  const box = {
    x: l / rect.width, y: t / rect.height,
    w: w / rect.width, h: h / rect.height,
  };
  state.selectionNorm = box;
  const wPct = (w / rect.width * 100).toFixed(1);
  const hPct = (h / rect.height * 100).toFixed(1);

  // 选框模式：保存到队列项 + 返回队列
  if (state.selectMode === 'box' && state.currentId) {
    const q = getQueueItem(state.currentId);
    if (q) {
      q.box = box;
      q.method = els.methodSel.value;
      q.radius = parseInt(els.radiusInput.value, 10);
      q.status = 'boxed';
      renderQueue();
      toast(`已框选 ${wPct}% × ${hPct}%`, 'ok');
    }
    goHome();
    return;
  }

  // 兼容旧模式：进 step-process
  els.selInfo.textContent = `已选 ${wPct}% × ${hPct}% · 点开始处理，或返回队列`;
  showStep('Process');
}

function resetSelection() {
  els.selection.classList.add('hidden');
  els.selInfo.textContent = '拖动鼠标在画面上框选水印位置';
}

els.btnClear.addEventListener('click', () => { state.selectionNorm = null; resetSelection(); });
els.btnPlay.addEventListener('click', () => {
  if (els.video.paused) { els.video.play(); els.btnPlay.innerHTML = '<span class="ico">⏸</span> 暂停'; }
  else { els.video.pause(); els.btnPlay.innerHTML = '<span class="ico">▶</span> 播放'; }
});
els.radiusInput.addEventListener('input', () => els.radiusVal.textContent = els.radiusInput.value);

// =========================================================
// 3. 处理（队列批量）
// =========================================================
async function processOne(id, box, method, radius) {
  updateQueueItem(id, { status: 'processing', progress: 0 });
  let timer = null;
  const fakeProgress = () => {
    const q = getQueueItem(id);
    if (q) {
      q.progress = Math.min(92, (q.progress || 0) + Math.random() * 4 + 1);
    }
    renderQueue();
  };
  timer = setInterval(fakeProgress, 400);
  try {
    const res = await fetch('/api/process', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id, box, method, radius }),
    });
    clearInterval(timer);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || '处理失败');
    const outUrl = `/api/history/${id}/view`;
    updateQueueItem(id, {
      status: 'done', progress: 100, resultUrl: outUrl, resultId: id,
    });
    return true;
  } catch (e) {
    clearInterval(timer);
    updateQueueItem(id, { status: 'error', error: e.message });
    toast(e.message, 'err');
    return false;
  }
}

function viewResult(id, info) {
  const q = getQueueItem(id);
  if (!q) return;
  state.resultId = id;
  state.resultUrl = q.resultUrl;
  els.resultVideo.src = q.resultUrl;
  if (info) {
    els.resultMeta.textContent = `${info.width}×${info.height} · ${info.fps}fps`;
  } else {
    els.resultMeta.textContent = `${q.info.width}×${q.info.height} · ${q.info.duration.toFixed(1)}s`;
  }
  showStep('Result');
  loadHistory();
}

// =========================================================
// 4. 批量
// =========================================================
els.btnBatchProcess.addEventListener('click', async () => {
  if (state.batchRunning) return;
  const boxed = state.queue.filter(q => q.status === 'boxed');
  if (boxed.length === 0) { toast('没有已框选的文件，请先在每个文件上点 ✎ 选框', 'warn'); return; }
  state.batchRunning = true;
  renderQueue();
  let okCount = 0, errCount = 0;
  for (const q of boxed) {
    const r = await processOne(q.id, q.box, q.method || 'telea', q.radius || 3);
    if (r) okCount++; else errCount++;
  }
  state.batchRunning = false;
  renderQueue();
  toast(`生成完成 · ${okCount} 成功${errCount > 0 ? ` · ${errCount} 失败` : ''}`, errCount > 0 ? 'warn' : 'ok');
  loadHistory();
});

// =========================================================
// 5. 保存到（原生对话框）
// =========================================================
async function doSaveAs(q) {
  if (!q || !q.id) return;
  try {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.save_as) {
      const target = await window.pywebview.api.save_as(q.id);
      if (target && target.path) toast('已保存到 ' + target.path, 'ok');
      else if (target && target.error) toast('保存失败：' + target.error, 'err');
      else toast('已取消保存', '');
    } else {
      const a = document.createElement('a');
      a.href = `/api/history/${q.id}/download`;
      a.download = '去水印_' + q.filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      toast('已触发下载', 'ok');
    }
  } catch (e) {
    toast('保存失败：' + e.message, 'err');
  }
}

els.btnSaveAs.addEventListener('click', () => {
  if (state.resultId) doSaveAs({ id: state.resultId, filename: 'video.mp4' });
});

els.btnRestart.addEventListener('click', () => {
  goHome();
  showView('home');
});

// =========================================================
// 预览模态框
// =========================================================
function openPreview(id, source) {
  // source: 'queue' | 'history'
  let src = null, caption = '';
  if (source === 'queue') {
    const q = getQueueItem(id);
    if (!q) return;
    src = q.resultUrl;
    caption = `${q.filename} · ${q.info.width}×${q.info.height} · ${q.info.duration.toFixed(1)}s`;
  } else if (source === 'history') {
    // history id 找到 download url
    src = `/api/history/${id}/view`;
    caption = '历史记录预览';
  }
  if (!src) return;
  els.previewVideo.src = src;
  els.previewCaption.textContent = caption;
  els.previewModal.classList.remove('hidden');
  els.previewModal.setAttribute('aria-hidden', 'false');
}

function closePreview() {
  els.previewVideo.pause();
  els.previewVideo.removeAttribute('src');
  els.previewVideo.load();
  els.previewModal.classList.add('hidden');
  els.previewModal.setAttribute('aria-hidden', 'true');
}

els.previewModal.addEventListener('click', e => {
  if (e.target.dataset.close !== undefined) closePreview();
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && !els.previewModal.classList.contains('hidden')) closePreview();
});

// 队列复选框：勾上 = "用此 box 同步到该项"
function applyBoxToQueueItem(id, sourceBox) {
  const q = getQueueItem(id);
  if (!q || !sourceBox) return;
  q.box = { ...sourceBox };
  q.method = state.sharedMethod;
  q.radius = state.sharedRadius;
  if (q.status === 'pending' || q.status === 'error') {
    q.status = 'boxed';
  }
  renderQueue();
}

// =========================================================
// 历史记录
// =========================================================
async function loadHistory() {
  try {
    const res = await fetch('/api/history');
    if (!res.ok) return;
    const list = await res.json();
    renderHistory(list);
    if (els.historyCount) {
      const n = (list || []).length;
      els.historyCount.textContent = n;
      els.historyCount.setAttribute('data-zero', n === 0 ? '1' : '0');
    }
    if (els.btnHistorySaveAll) {
      els.btnHistorySaveAll.disabled = !(list && list.length > 0);
      els.btnHistorySaveAll.innerHTML = `<span class="ico">⤓</span> 全部下载 (${(list||[]).length})`;
    }
  } catch (e) { console.error(e); }
}

function renderHistory(list) {
  els.historyList.innerHTML = '';
  if (!list || list.length === 0) {
    els.historyEmpty.classList.remove('hidden');
    return;
  }
  els.historyEmpty.classList.add('hidden');
  list.forEach(item => {
    const li = document.createElement('li');
    li.className = 'history-item';
    const time = new Date(item.processedAt * 1000).toLocaleString('zh-CN', { hour12: false });
    const sizeMB = (item.size / 1024 / 1024).toFixed(1);
    li.innerHTML = `
      <div class="history-thumb"><img src="${item.thumbUrl}" alt="" loading="lazy"></div>
      <div class="history-meta">
        <div class="name">${escapeHtml(item.originalName)}</div>
        <div class="info">${item.width}×${item.height} · ${item.duration.toFixed(1)}s · ${sizeMB} MB · ${time}</div>
      </div>
      <div class="history-actions">
        <button data-act="preview" data-id="${item.id}" title="预览"><span class="ico">👁</span></button>
        <button data-act="save" data-id="${item.id}" title="保存到…"><span class="ico">⤓</span></button>
        <button data-act="del" data-id="${item.id}" title="删除" class="danger"><span class="ico">🗑</span></button>
      </div>
    `;
    li.querySelector('[data-act=preview]').addEventListener('click', () => openPreview(item.id, 'history'));
    li.querySelector('[data-act=save]').addEventListener('click', () => doSaveAs({ id: item.id, filename: item.originalName }));
    li.querySelector('[data-act=del]').addEventListener('click', () => deleteHistoryItem(item));
    els.historyList.appendChild(li);
  });
}

async function deleteHistoryItem(item) {
  if (!confirm(`删除 "${item.originalName}" 的处理记录？`)) return;
  try {
    const res = await fetch(`/api/history/${item.id}`, { method: 'DELETE' });
    if (!res.ok) throw new Error('删除失败');
    toast('已删除', 'ok');
    loadHistory();
  } catch (e) { toast(e.message, 'err'); }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// =========================================================
// Init
// =========================================================
loadHistory();
showStep('Upload');
renderQueue();
