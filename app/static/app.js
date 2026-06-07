const state = {
  view: "all",
  category: "",
  q: "",
  stats: null,
};

const els = {
  scanBtn: document.querySelector("#scanBtn"),
  folderInput: document.querySelector("#folderInput"),
  outputInput: document.querySelector("#outputInput"),
  pickFolderBtn: document.querySelector("#pickFolderBtn"),
  pickOutputBtn: document.querySelector("#pickOutputBtn"),
  openOutputBtn: document.querySelector("#openOutputBtn"),
  copyCandidatesBtn: document.querySelector("#copyCandidatesBtn"),
  copyKeepersBtn: document.querySelector("#copyKeepersBtn"),
  thresholdInput: document.querySelector("#thresholdInput"),
  thresholdText: document.querySelector("#thresholdText"),
  recursiveInput: document.querySelector("#recursiveInput"),
  status: document.querySelector("#status"),
  sideStatus: document.querySelector("#sideStatus"),
  busyOverlay: document.querySelector("#busyOverlay"),
  content: document.querySelector("#content"),
  statsBar: document.querySelector("#statsBar"),
  categoryBar: document.querySelector("#categoryBar"),
  searchInput: document.querySelector("#searchInput"),
  navButtons: document.querySelectorAll(".nav button"),
};

function setStatus(text) {
  els.status.textContent = text || "";
  if (els.sideStatus) {
    els.sideStatus.textContent = text || "准备就绪";
  }
}

function setBusy(isBusy) {
  els.scanBtn.disabled = isBusy;
  els.scanBtn.textContent = isBusy ? "扫描中..." : "扫描图片";
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
  return response.json();
}

async function loadStats() {
  state.stats = await api("/api/stats");
  renderStats();
  renderCategories();
}

function renderStats() {
  const stats = state.stats || {};
  els.statsBar.innerHTML = [
    ["总数", stats.total || 0],
    ["完全重复", stats.exact_groups || 0],
    ["文件名副本", stats.name_groups || 0],
    ["相似组", stats.similar_groups || 0],
  ]
    .map(([label, value]) => `<span class="chip">${label}: ${value}</span>`)
    .join("");
}

function renderCategories() {
  const categories = state.stats?.categories || [];
  els.categoryBar.innerHTML = `<button data-category="" class="${state.category === "" ? "active" : ""}">全部分类</button>` +
    categories
      .map((item) => `<button data-category="${item.category}" class="${state.category === item.category ? "active" : ""}">${labelCategory(item.category)} ${item.count}</button>`)
      .join("");
  els.categoryBar.querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", () => {
      state.category = button.dataset.category || "";
      renderCategories();
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
    product_image: "商品图",
  }[value] || value;
}

async function loadContent() {
  setStatus("正在加载...");
  if (state.view === "recommend") {
    const data = await api("/api/recommendations");
    renderRecommendations(data);
    setStatus(`${data.duplicate_candidates.length} 张处理候选`);
    return;
  }
  if (["exact", "name", "similar"].includes(state.view) && !state.category && !state.q) {
    const groups = await api(`/api/groups/${state.view}`);
    renderGroups(groups);
  setStatus(`${groups.length} 个分组`);
    return;
  }
  const params = new URLSearchParams({ view: state.view, category: state.category, q: state.q });
  const images = await api(`/api/images?${params.toString()}`);
  renderImages(images);
  setStatus(`${images.length} 张图片`);
}

function renderRecommendations(data) {
  els.content.className = "content-grid";
  const candidates = data.duplicate_candidates || [];
  if (!candidates.length) {
    els.content.innerHTML = `<div class="empty">暂无处理候选。先扫描图片，或调高相似严格度后重新扫描。</div>`;
    return;
  }
  els.content.innerHTML = candidates.map((item) => `
    <article class="image-card">
      <a href="/image/${item.id}" target="_blank"><img src="/thumb/${item.id}" alt=""></a>
      <div class="meta">
        <div class="name">${escapeHtml(item.name)}</div>
        <div class="sub">处理候选 · 建议保留 #${item.keeper_id}</div>
        <div class="sub">${item.reason}</div>
        <div class="badges"><span class="badge warn">处理候选</span><span class="badge">${labelCategory(item.category)}</span></div>
      </div>
    </article>
  `).join("");
}

function imageCard(item, options = {}) {
  const role = options.role || "";
  const badges = [
    role === "keeper" ? `<span class="badge good">建议保留</span>` : "",
    role === "candidate" ? `<span class="badge warn">处理候选</span>` : "",
    item.exact_group ? `<span class="badge warn">完全重复 ${item.exact_group}</span>` : "",
    item.name_group ? `<span class="badge">文件名副本 ${item.name_group}</span>` : "",
    item.similar_group ? `<span class="badge">相似 ${item.similar_group}</span>` : "",
  ].join("");
  return `
    <article class="image-card">
      <a href="/image/${item.id}" target="_blank"><img src="/thumb/${item.id}" alt=""></a>
      <div class="meta">
        <div class="name">${escapeHtml(item.name)}</div>
        <div class="sub">${item.width}x${item.height} · ${formatSize(item.size_bytes)}</div>
        <div class="sub">blur ${Math.round(item.blur_score)} · score ${Math.round(item.quality_score)}</div>
        <div class="badges"><span class="badge">${labelCategory(item.category)}</span>${badges}</div>
      </div>
    </article>
  `;
}

function renderImages(images) {
  els.content.className = "content-grid";
  els.content.innerHTML = images.length ? images.map((item) => imageCard(item)).join("") : `<div class="empty">没有匹配图片。</div>`;
}

function renderGroups(groups) {
  els.content.className = "content-grid";
  if (!groups.length) {
    els.content.innerHTML = `<div class="empty">暂无分组。可以降低严格度后重新扫描。</div>`;
    return;
  }
  els.content.innerHTML = groups
    .map((group) => `
      <section class="group">
        <div class="group-head">
          <strong>${group.reason} ${group.group_id}</strong>
          <span class="sub">${group.count} 张 · 最佳评分 ${Math.round(group.best_score || 0)}</span>
        </div>
        <div class="group-grid">${group.images.map((item, index) => imageCard(item, { role: index === 0 ? "keeper" : "candidate" })).join("")}</div>
      </section>
    `)
    .join("");
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
    setStatus("正在扫描...图片多时需要几十秒，请不要重复点击。");
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
    setStatus(`扫描完成：${result.total} 张，${result.exact_groups} 组完全重复，${result.similar_groups} 组相似图`);
    await loadStats();
    await loadContent();
  } catch (error) {
    setStatus(error.message);
  } finally {
    setBusy(false);
  }
});

async function copyMode(mode) {
  const label = mode === "keepers" ? "保留建议" : "处理候选";
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

els.copyCandidatesBtn.addEventListener("click", () => copyMode("candidates").catch((error) => setStatus(error.message)));
els.copyKeepersBtn.addEventListener("click", () => copyMode("keepers").catch((error) => setStatus(error.message)));

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
  button.addEventListener("click", () => {
    els.navButtons.forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    state.view = button.dataset.view || "all";
    loadContent();
  });
});

let searchTimer = null;
els.searchInput.addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    state.q = els.searchInput.value.trim();
    loadContent();
  }, 250);
});

loadStats().then(loadContent).catch((error) => setStatus(error.message));
