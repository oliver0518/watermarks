const dropzone = document.getElementById('dropzone');
const fileInput = document.getElementById('file-input');
const uploadStatus = document.getElementById('upload-status');
const stepUpload = document.getElementById('step-upload');
const stepSelect = document.getElementById('step-select');
const stepProcess = document.getElementById('step-process');
const stepResult = document.getElementById('step-result');
const videoBox = document.getElementById('video-box');
const video = document.getElementById('video');
const overlay = document.getElementById('video-overlay');
const selection = document.getElementById('selection');
const btnPlay = document.getElementById('btn-play');
const btnClear = document.getElementById('btn-clear');
const selInfo = document.getElementById('sel-info');
const methodSel = document.getElementById('method');
const radiusInput = document.getElementById('radius');
const radiusVal = document.getElementById('radius-val');
const btnProcess = document.getElementById('btn-process');
const progress = document.getElementById('progress');
const barFill = document.getElementById('bar-fill');
const progressText = document.getElementById('progress-text');
const btnRestart = document.getElementById('btn-restart');
const resultVideo = document.getElementById('result-video');
const downloadLink = document.getElementById('download-link');

let videoId = null;
let srcUrl = null;
let selectionNorm = null; // {x,y,w,h} 归一化 0-1
let videoMeta = null;

radiusInput.addEventListener('input', () => radiusVal.textContent = radiusInput.value);

// ---- 上传 ----
function clickDrop() { fileInput.click(); }
dropzone.addEventListener('click', clickDrop);
fileInput.addEventListener('change', () => { if (fileInput.files[0]) upload(fileInput.files[0]); });
['dragover', 'dragenter'].forEach(ev => dropzone.addEventListener(ev, e => {
  e.preventDefault(); dropzone.classList.add('drag');
}));
['dragleave', 'drop'].forEach(ev => dropzone.addEventListener(ev, e => {
  e.preventDefault(); dropzone.classList.remove('drag');
}));
dropzone.addEventListener('drop', e => {
  const file = e.dataTransfer.files[0];
  if (file) upload(file);
});

async function upload(file) {
  const fd = new FormData();
  fd.append('video', file);
  show(uploadStatus);
  uploadStatus.textContent = '正在上传并解析视频...';
  try {
    const res = await fetch('/api/upload', { method: 'POST', body: fd });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || '上传失败');
    videoId = data.id;
    srcUrl = data.src;
    videoMeta = data.info;
    uploadStatus.textContent = `✅ 解析成功 · ${file.name} · ${data.info.width}×${data.info.height} · ${data.info.duration.toFixed(1)}s`;
    setupSelect();
  } catch (e) {
    uploadStatus.textContent = '❌ ' + e.message;
  }
}

// ---- 框选 ----
function setupSelect() {
  hide(stepUpload);
  show(stepSelect);
  video.src = srcUrl;
  video.load();
  selectionNorm = null;
  resetSelection();
  video.onloadedmetadata = () => {
    video.currentTime = Math.min(0.5, (videoMeta.duration || 0) / 2);
  };
}

videoBox.addEventListener('mouseenter', () => show(overlay));
videoBox.addEventListener('mouseleave', () => hide(overlay));

overlay.addEventListener('mousedown', startSelect);
overlay.addEventListener('touchstart', e => startSelect(e, true), { passive: false });

let dragging = false;
let startX = 0, startY = 0;

// 用 video 实际渲染矩形做归一化（不是 videoBox 容器；letterbox 下两者不一致）
function getVideoRect() {
  return video.getBoundingClientRect();
}

function startSelect(e, isTouch) {
  if (isTouch) e.preventDefault();
  dragging = true;
  const rect = getVideoRect();
  const pt = getPoint(e, isTouch);
  startX = Math.min(Math.max(pt.x - rect.left, 0), rect.width);
  startY = Math.min(Math.max(pt.y - rect.top, 0), rect.height);
  selection.classList.remove('hidden');
  updateSel(startX, startY);
  e.preventDefault();

  const move = ev => { if (!dragging) return; const p = getPoint(ev, isTouch);
    updateSel(startX, startY, p.x - rect.left, p.y - rect.top); };
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

function updateSel(x1, y1, x2, y2) {
  const rect = getVideoRect();
  if (x2 === undefined) { x2 = x1; y2 = y1; }
  const l = Math.min(x1, x2), t = Math.min(y1, y2);
  const r = Math.max(x1, x2), b = Math.max(y1, y2);
  selection.style.left = l + 'px';
  selection.style.top = t + 'px';
  selection.style.width = (r - l) + 'px';
  selection.style.height = (b - t) + 'px';
}

function finalize() {
  const rect = getVideoRect();
  const l = parseFloat(selection.style.left), t = parseFloat(selection.style.top);
  const w = parseFloat(selection.style.width), h = parseFloat(selection.style.height);
  if (w < 5 || h < 5) { resetSelection(); return; }
  selectionNorm = {
    x: l / rect.width, y: t / rect.height,
    w: w / rect.width, h: h / rect.height
  };
  selInfo.textContent = `✅ 已选中区域（比例为 ${(w/rect.width*100).toFixed(1)}% × ${(h/rect.height*100).toFixed(1)}%），可调整或点击下方“处理”`;
  show(stepProcess);
}

function resetSelection() {
  selection.classList.add('hidden');
  selInfo.textContent = '拖动鼠标在画面上框选水印位置';
  hide(stepProcess);
}

btnClear.addEventListener('click', () => { selectionNorm = null; resetSelection(); });

btnPlay.addEventListener('click', () => {
  if (video.paused) { video.play().then(() => btnPlay.textContent = '⏸ 暂停'); }
  else { video.pause(); btnPlay.textContent = '▶ 播放'; }
});

// ---- 处理 ----
btnProcess.addEventListener('click', async () => {
  if (!selectionNorm) { selInfo.textContent = '⚠ 请先框选水印区域'; return; }
  btnProcess.disabled = true;
  show(progress);
  progressText.textContent = '正在处理，请稍候...';
  barFill.style.width = '15%';
  try {
    // 后端逐帧处理耗时较长，使用 fetch 默认超时
    const res = await fetch('/api/process', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        id: videoId,
        box: selectionNorm,
        method: methodSel.value,
        radius: parseInt(radiusInput.value, 10)
      })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || '处理失败');
    barFill.style.width = '100%';
    progressText.textContent = '处理完成！';
    showResult(data.url);
  } catch (e) {
    progressText.textContent = '❌ ' + e.message;
    btnProcess.disabled = false;
  }
});

function showResult(url) {
  setTimeout(() => {
    hide(progress);
    hide(stepSelect); hide(stepProcess);
    show(stepResult);
    resultVideo.src = url;
    video.pause();
    downloadLink.href = url;
    downloadLink.setAttribute('download', '去水印_' + (videoMeta ? srcUrl.split('/').pop() : 'video.mp4'));
  }, 400);
}

// ---- 重新开始 ----
btnRestart.addEventListener('click', () => {
  hide(stepResult); hide(stepSelect); hide(stepProcess);
  show(stepUpload);
  hide(uploadStatus);
  btnProcess.disabled = false;
  fileInput.value = '';
});

function show(el) { el.classList.remove('hidden'); }
function hide(el) { el.classList.add('hidden'); }