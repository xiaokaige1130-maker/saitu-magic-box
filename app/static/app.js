const REVIEW = {
  selected: { label: "精选", tone: "good" },
  weak: { label: "较差", tone: "warn" },
  empty: { label: "空镜", tone: "info" },
  waste: { label: "废片", tone: "bad" },
};

const VIEW_TITLES = {
  all: "我的主页",
  recommend: "推荐选优",
  selected: "精选照片",
  weak: "较差照片",
  empty: "空镜照片",
  waste: "废片照片",
  duplicate: "重复/相似",
};

const state = {
  view: "all",
  category: "",
  tag: "",
  q: "",
  recommendPercent: 100,
  stats: null,
  selectedId: null,
};

const els = {
  scanBtn: document.querySelector("#scanBtn"),
  folderInput: document.querySelector("#folderInput"),
  outputInput: document.querySelector("#outputInput"),
  pickFolderBtn: document.querySelector("#pickFolderBtn"),
  pickOutputBtn: document.querySelector("#pickOutputBtn"),
  openOutputBtn: document.querySelector("#openOutputBtn"),
  copySelectedBtn: document.querySelector("#copySelectedBtn"),
  copyWasteBtn: document.querySelector("#copyWasteBtn"),
  copyCandidatesBtn: document.querySelector("#copyCandidatesBtn"),
  copyKeepersBtn: document.querySelector("#copyKeepersBtn"),
  organizeBtn: document.querySelector("#organizeBtn"),
  xmpBtn: document.querySelector("#xmpBtn"),
  thresholdInput: document.querySelector("#thresholdInput"),
  thresholdText: document.querySelector("#thresholdText"),
  recursiveInput: document.querySelector("#recursiveInput"),
  status: document.querySelector("#status"),
  sideStatus: document.querySelector("#sideStatus"),
  busyOverlay: document.querySelector("#busyOverlay"),
  content: document.querySelector("#content"),
  summaryCards: document.querySelector("#summaryCards"),
  categoryBar: document.querySelector("#categoryBar"),
  tagBar: document.querySelector("#tagBar"),
  searchInput: document.querySelector("#searchInput"),
  viewTitle: document.querySelector("#viewTitle"),
  navButtons: document.querySelectorAll(".nav button"),
  percentButtons: document.querySelectorAll("#percentBar button"),
};

function setStatus(text) {
  els.status.textContent = text || "";
  if (els.sideStatus) {
    els.sideStatus.textContent = text || "准备就绪";
  }
}

function setBusy(isBusy) {
  els.scanBtn.disabled = isBusy;
  els.scanBtn.textContent = isBusy ? "筛选中..." : "开始筛选";
  els.busyOverlay?.classList.toggle("hidden", !isBusy);
}

async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) {
    const text = await response.text();
    let message = text;
    try {
      const data = JSON.parse(text);
      message = data.detail || text;
    } catch {
      message = text;
    }
    throw new Error(message || `HTTP ${response.status}`);
  }
  const contentType = response.headers.get("content-type") || "";
  return contentType.includes("application/json") ? response.json() : response.text();
}

async function loadStats() {
  state.stats = await api("/api/stats");
  renderSummary();
  renderCategories();
  renderTags();
}

function renderSummary() {
  const stats = state.stats || {};
  const statuses = stats.statuses || {};
  const cards = [
    { view: "all", label: "全部", value: stats.total || 0, sub: "已扫描图片" },
    { view: "selected", label: "精选", value: statuses.selected || 0, sub: "建议交付/精修" },
    { view: "weak", label: "较差", value: statuses.weak || 0, sub: "需要复核" },
    { view: "empty", label: "空镜", value: statuses.empty || 0, sub: "场景/细节" },
    { view: "waste", label: "废片", value: statuses.waste || 0, sub: "重复或严重问题" },
  ];
  els.summaryCards.innerHTML = cards.map((card) => `
    <button class="summary-card ${state.view === card.view ? "active" : ""}" data-summary-view="${card.view}">
      <span>${card.label}</span>
      <strong>${card.value}</strong>
      <small>${card.sub}</small>
    </button>
  `).join("");
  els.summaryCards.querySelectorAll("[data-summary-view]").forEach((button) => {
    button.addEventListener("click", () => setView(button.dataset.summaryView || "all"));
  });
}

function renderCategories() {
  const categories = state.stats?.categories || [];
  els.categoryBar.innerHTML = `<button data-category="" class="${state.category === "" ? "active" : ""}">全部分类</button>` +
    categories
      .map((item) => `<button data-category="${escapeHtml(item.category)}" class="${state.category === item.category ? "active" : ""}">${labelCategory(item.category)} ${item.count}</button>`)
      .join("");
  els.categoryBar.querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", () => {
      state.category = button.dataset.category || "";
      renderCategories();
      loadContent();
    });
  });
}

function renderTags() {
  const tags = state.stats?.tags || [];
  const topTags = tags.slice(0, 10);
  els.tagBar.innerHTML = `<button data-tag="" class="${state.tag === "" ? "active" : ""}">全部标签</button>` +
    topTags
      .map((item) => `<button data-tag="${escapeHtml(item.tag)}" class="${state.tag === item.tag ? "active" : ""}">${escapeHtml(item.tag)} ${item.count}</button>`)
      .join("");
  els.tagBar.querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", () => {
      state.tag = button.dataset.tag || "";
      renderTags();
      loadContent();
    });
  });
}

function labelCategory(value) {
  return {
    with_label: "带型号",
    detail: "详情/集合",
    copy_named: "文件名副本",
    legacy_format: "旧格式",
    png_asset: "PNG素材",
    raw_photo: "RAW照片",
    tiff_photo: "TIFF照片",
    photo: "照片",
  }[value] || value;
}

async function loadContent() {
  setStatus("正在加载...");
  els.viewTitle.textContent = VIEW_TITLES[state.view] || "筛选结果";
  const params = new URLSearchParams({
    view: state.view,
    category: state.category,
    q: state.q,
    tag: state.tag,
    recommend_percent: String(state.recommendPercent),
  });
  const images = await api(`/api/images?${params.toString()}`);
  renderImages(images);
  const percentText = state.view === "recommend" && state.recommendPercent < 100 ? ` · 前 ${state.recommendPercent}%` : "";
  setStatus(`${images.length} 张图片${percentText}`);
}

function renderImages(images) {
  els.content.className = "content-grid";
  if (!images.length) {
    els.content.innerHTML = `<div class="empty">没有匹配图片。可以换一个筛选条件，或重新开始筛图。</div>`;
    return;
  }
  els.content.innerHTML = images.map((item) => imageCard(item)).join("");
  els.content.querySelectorAll(".image-card").forEach((card) => {
    card.addEventListener("click", () => {
      state.selectedId = Number(card.dataset.id);
      markSelectedCard();
    });
  });
  els.content.querySelectorAll("[data-status]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      labelImage(Number(button.dataset.id), { review_status: button.dataset.status }).catch((error) => setStatus(error.message));
    });
  });
  els.content.querySelectorAll("[data-star]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      labelImage(Number(button.dataset.id), { star_rating: Number(button.dataset.star) }).catch((error) => setStatus(error.message));
    });
  });
}

function imageCard(item) {
  const status = REVIEW[item.review_status] || REVIEW.selected;
  const tags = String(item.tags || "").split(",").filter(Boolean);
  const starButtons = [1, 2, 3, 4, 5].map((star) => `
    <button class="star-btn ${Number(item.star_rating) >= star ? "on" : ""}" data-id="${item.id}" data-star="${star}" title="${star} 星">${star}</button>
  `).join("");
  return `
    <article class="image-card ${state.selectedId === Number(item.id) ? "selected" : ""}" data-id="${item.id}">
      <a class="thumb-link" href="/image/${item.id}" target="_blank"><img src="/thumb/${item.id}" alt=""></a>
      <div class="meta">
        <div class="card-head">
          <span class="status-pill ${status.tone}">${status.label}</span>
          <span class="score">${Math.round(Number(item.quality_score || 0))}</span>
        </div>
        <div class="name">${escapeHtml(item.name)}</div>
        <div class="sub">${item.width}x${item.height} · ${formatSize(item.size_bytes)} · 清晰 ${Math.round(Number(item.blur_score || 0))}</div>
        <div class="stars">${starButtons}</div>
        <div class="badges">
          <span class="badge">${labelCategory(item.category)}</span>
          ${tags.map((tag) => `<span class="badge ${tagTone(tag)}">${escapeHtml(tag)}</span>`).join("")}
        </div>
        <div class="quick-row">
          <button data-id="${item.id}" data-status="selected">精选</button>
          <button data-id="${item.id}" data-status="weak">较差</button>
          <button data-id="${item.id}" data-status="empty">空镜</button>
          <button data-id="${item.id}" data-status="waste">废片</button>
        </div>
      </div>
    </article>
  `;
}

function tagTone(tag) {
  if (["重复", "严重模糊", "过曝", "欠曝"].includes(tag)) return "bad";
  if (["模糊", "低反差", "低饱和"].includes(tag)) return "warn";
  if (["推荐", "组内最佳"].includes(tag)) return "good";
  return "";
}

function markSelectedCard() {
  els.content.querySelectorAll(".image-card").forEach((card) => {
    card.classList.toggle("selected", Number(card.dataset.id) === state.selectedId);
  });
}

async function labelImage(id, payload) {
  await api(`/api/images/${id}/label`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  setStatus("已更新标记。");
  await loadStats();
  await loadContent();
}

function setView(view) {
  state.view = view;
  state.selectedId = null;
  els.navButtons.forEach((button) => button.classList.toggle("active", button.dataset.view === view));
  renderSummary();
  loadContent().catch((error) => setStatus(error.message));
}

function formatSize(value) {
  const mb = Number(value) / 1024 / 1024;
  return `${mb.toFixed(mb >= 10 ? 0 : 1)} MB`;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  }[char]));
}

els.scanBtn.addEventListener("click", async () => {
  try {
    setBusy(true);
    setStatus("正在筛图...图片多时需要一会儿，请不要关闭窗口。");
    await new Promise((resolve) => setTimeout(resolve, 80));
    const result = await api("/api/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        folder: els.folderInput.value.trim(),
        similar_threshold: Number(els.thresholdInput.value),
        recursive: els.recursiveInput.checked,
      }),
    });
    const failedText = result.failed?.length ? `，${result.failed.length} 个文件未能读取` : "";
    setStatus(`筛图完成：${result.total} 张，${result.exact_groups} 组完全重复，${result.similar_groups} 组相似图${failedText}`);
    state.view = "recommend";
    els.navButtons.forEach((button) => button.classList.toggle("active", button.dataset.view === state.view));
    await loadStats();
    await loadContent();
  } catch (error) {
    setStatus(error.message);
  } finally {
    setBusy(false);
  }
});

async function copyMode(mode, label) {
  if (!window.confirm(`确认复制${label}到输出文件夹？原图不会被删除或移动。`)) {
    return;
  }
  const result = await api("/api/copy", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ folder: els.outputInput.value.trim(), mode }),
  });
  setStatus(`已复制 ${result.copied} 张到 ${result.target}`);
}

async function organizeOutput() {
  if (!window.confirm("确认按精选、较差、空镜、废片复制整理到输出文件夹？原图不会被删除或移动。")) {
    return;
  }
  const result = await api("/api/organize", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ folder: els.outputInput.value.trim() }),
  });
  const counts = Object.entries(result.counts || {}).map(([key, value]) => `${key}${value}`).join(" / ");
  setStatus(`已整理到 ${result.target}：${counts}`);
}

async function generateXmp() {
  const result = await api("/api/xmp", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ folder: els.outputInput.value.trim(), mode: state.view in REVIEW ? state.view : "selected" }),
  });
  setStatus(`已生成 ${result.written} 个 XMP 到 ${result.target}`);
}

els.copySelectedBtn.addEventListener("click", () => copyMode("selected", "精选照片").catch((error) => setStatus(error.message)));
els.copyWasteBtn.addEventListener("click", () => copyMode("waste", "废片照片").catch((error) => setStatus(error.message)));
els.copyCandidatesBtn.addEventListener("click", () => copyMode("candidates", "重复候选").catch((error) => setStatus(error.message)));
els.copyKeepersBtn.addEventListener("click", () => copyMode("keepers", "组内最佳").catch((error) => setStatus(error.message)));
els.organizeBtn.addEventListener("click", () => organizeOutput().catch((error) => setStatus(error.message)));
els.xmpBtn.addEventListener("click", () => generateXmp().catch((error) => setStatus(error.message)));

async function pickFolder(input, title) {
  setStatus("正在打开文件夹选择窗口...");
  const result = await api("/api/pick-folder", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ initial: input.value.trim(), title }),
  });
  if (result.folder) {
    input.value = result.folder;
    setStatus(`已选择：${result.folder}`);
  } else {
    setStatus("已取消选择。");
  }
}

async function openOutputFolder() {
  const result = await api("/api/open-folder", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ folder: els.outputInput.value.trim() }),
  });
  setStatus(`已打开：${result.opened}`);
}

els.pickFolderBtn.addEventListener("click", () => pickFolder(els.folderInput, "选择原图文件夹").catch((error) => setStatus(error.message)));
els.pickOutputBtn.addEventListener("click", () => pickFolder(els.outputInput, "选择输出文件夹").catch((error) => setStatus(error.message)));
els.openOutputBtn.addEventListener("click", () => openOutputFolder().catch((error) => setStatus(error.message)));
els.thresholdInput.addEventListener("input", () => {
  els.thresholdText.textContent = els.thresholdInput.value;
});

els.navButtons.forEach((button) => {
  button.addEventListener("click", () => setView(button.dataset.view || "all"));
});

els.percentButtons.forEach((button) => {
  button.addEventListener("click", () => {
    state.recommendPercent = Number(button.dataset.percent || 100);
    els.percentButtons.forEach((item) => item.classList.toggle("active", item === button));
    if (state.view !== "recommend") {
      setView("recommend");
    } else {
      loadContent().catch((error) => setStatus(error.message));
    }
  });
});

let searchTimer = null;
els.searchInput.addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    state.q = els.searchInput.value.trim();
    loadContent().catch((error) => setStatus(error.message));
  }, 250);
});

document.addEventListener("keydown", (event) => {
  const target = event.target;
  if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLButtonElement) {
    return;
  }
  if (!state.selectedId) {
    return;
  }
  if (/^[1-5]$/.test(event.key)) {
    labelImage(state.selectedId, { star_rating: Number(event.key) }).catch((error) => setStatus(error.message));
  } else if (event.key.toLowerCase() === "f") {
    labelImage(state.selectedId, { review_status: "selected" }).catch((error) => setStatus(error.message));
  } else if (event.key.toLowerCase() === "w") {
    labelImage(state.selectedId, { review_status: "weak" }).catch((error) => setStatus(error.message));
  } else if (event.key.toLowerCase() === "e") {
    labelImage(state.selectedId, { review_status: "empty" }).catch((error) => setStatus(error.message));
  } else if (event.key.toLowerCase() === "d") {
    labelImage(state.selectedId, { review_status: "waste" }).catch((error) => setStatus(error.message));
  }
});

loadStats().then(loadContent).catch((error) => setStatus(error.message));
