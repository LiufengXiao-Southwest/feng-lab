const CAT_LABELS = {
  biomechanics: { zh: '生物力学', en: 'Biomechanics', cls: 'tag-biomechanics', color: '#C4956A' },
  performance:  { zh: '运动表现', en: 'Performance',  cls: 'tag-performance',  color: '#4A6FA5' },
  supplements:  { zh: '运动补剂', en: 'Supplements',  cls: 'tag-supplements',  color: '#3D7A45' },
  preprint:     { zh: '预印本',   en: 'Preprint',     cls: 'tag-preprint',     color: '#B06A1A' },
};

let allPapers = [];
let activeCategory = 'all';
let activeSearch   = '';
let searchTimer    = null;
let catChart       = null;

// ── Dark Mode ─────────────────────────────────────────────────────────────────
function initTheme() {
  const saved = localStorage.getItem('feng-lab-theme');
  if (saved === 'dark') document.documentElement.setAttribute('data-theme', 'dark');
}

function toggleTheme() {
  const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
  if (isDark) {
    document.documentElement.removeAttribute('data-theme');
    localStorage.setItem('feng-lab-theme', 'light');
  } else {
    document.documentElement.setAttribute('data-theme', 'dark');
    localStorage.setItem('feng-lab-theme', 'dark');
  }
  if (catChart) updateChartColors();
}

// Call before DOM ready so there's no flash
initTheme();

// ── Bookmarks ─────────────────────────────────────────────────────────────────
const BOOKMARK_KEY = 'feng-lab-bookmarks';

function getBookmarks() {
  try { return new Set(JSON.parse(localStorage.getItem(BOOKMARK_KEY) || '[]')); }
  catch { return new Set(); }
}

function saveBookmarks(set) {
  localStorage.setItem(BOOKMARK_KEY, JSON.stringify([...set]));
}

function toggleBookmark(id) {
  const bm = getBookmarks();
  if (bm.has(id)) { bm.delete(id); } else { bm.add(id); }
  saveBookmarks(bm);
  updateBookmarkUI();
  // Update the button on the card
  const btn = document.querySelector(`.btn-bookmark[data-id="${id}"]`);
  if (btn) {
    btn.classList.toggle('bookmarked', bm.has(id));
    btn.title = bm.has(id) ? '取消收藏' : '收藏';
  }
  // If currently viewing bookmarks filter, re-render
  if (activeCategory === 'bookmarks') renderPapers(getFilteredPapers());
}

function updateBookmarkUI() {
  const bm = getBookmarks();
  const count = bm.size;
  const exportBar = document.getElementById('exportBar');
  const bookmarkFilterBtn = document.getElementById('bookmarkFilterBtn');
  const bookmarkCount = document.getElementById('bookmarkCount');

  if (exportBar) exportBar.classList.toggle('show', count > 0);
  if (bookmarkFilterBtn) bookmarkFilterBtn.style.display = count > 0 ? '' : 'none';
  if (bookmarkCount) bookmarkCount.textContent = count;
}

function exportAllBibTeX() {
  const bm = getBookmarks();
  const papers = allPapers.filter(p => bm.has(p.id));
  if (!papers.length) return;
  const bibtex = papers.map(p => {
    const firstAuthor = (p.authors || ['Unknown'])[0].split(' ').pop();
    const key = firstAuthor + (p.year || '');
    const authors = (p.authors || []).join(' and ');
    return `@article{${key},\n  title   = {${(p.title_en || '').replace(/[{}]/g, '')}},\n  author  = {${authors}},\n  journal = {${p.journal || ''}},\n  year    = {${p.year || ''}},\n  doi     = {${p.doi || ''}}\n}`;
  }).join('\n\n');

  const blob = new Blob([bibtex], { type: 'text/plain' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'feng-lab-bookmarks.bib';
  a.click();
  URL.revokeObjectURL(url);
  showToast(`已导出 ${papers.length} 篇文献 BibTeX ✓`);
}

function clearAllBookmarks() {
  saveBookmarks(new Set());
  updateBookmarkUI();
  document.querySelectorAll('.btn-bookmark').forEach(btn => btn.classList.remove('bookmarked'));
  if (activeCategory === 'bookmarks') {
    setFilter('all');
  }
  showToast('已清空收藏夹');
}

// ── Skeleton Screen ───────────────────────────────────────────────────────────
function buildSkeletonCards(count = 6) {
  return Array.from({ length: count }, () => `
<div class="skeleton-card">
  <div class="skeleton-line sk-tag"></div>
  <div>
    <div class="skeleton-line sk-title"></div>
    <div class="skeleton-line sk-title-sm" style="margin-top:8px"></div>
  </div>
  <div class="skeleton-line sk-author"></div>
  <div class="skeleton-line sk-journal"></div>
  <div style="height:1px;background:var(--border)"></div>
  <div style="display:flex;flex-direction:column;gap:6px">
    <div class="skeleton-line sk-abs1"></div>
    <div class="skeleton-line sk-abs2"></div>
    <div class="skeleton-line sk-abs3"></div>
  </div>
  <div class="sk-btn-row">
    <div class="skeleton-line sk-btn"></div>
    <div class="skeleton-line sk-btn"></div>
    <div class="skeleton-line sk-btn"></div>
  </div>
</div>`).join('');
}

// ── Data Loading ──────────────────────────────────────────────────────────────
async function loadPapers() {
  const grid = document.getElementById('paperGrid');
  if (grid) grid.innerHTML = buildSkeletonCards(6);

  try {
    const base = location.pathname.replace(/\/[^/]*$/, '');
    const res = await fetch(base + '/data/papers.json');
    const json = await res.json();
    allPapers = json.papers || [];

    const d = document.getElementById('lastUpdated');
    if (d) d.textContent = json.last_updated || '—';

    renderPapers(allPapers);
    updateBookmarkUI();
    renderStats();
  } catch (e) {
    const grid = document.getElementById('paperGrid');
    if (grid) grid.innerHTML =
      '<div class="loading">加载失败，请刷新重试 / Failed to load, please refresh.</div>';
  }
}

function renderPapers(papers) {
  const grid = document.getElementById('paperGrid');
  const count = document.getElementById('paperCount');
  if (!grid) return;

  count.textContent = papers.length;

  if (papers.length === 0) {
    grid.innerHTML = '<div class="loading">暂无文献 / No papers found.</div>';
    return;
  }

  const bm = getBookmarks();
  grid.innerHTML = papers.map(p => buildCard(p, bm.has(p.id))).join('');
}

function buildCard(p, isBookmarked = false) {
  const cat = CAT_LABELS[p.category] || { zh: p.category, en: p.category, cls: '' };
  const authors = (p.authors || []).length > 3
    ? p.authors.slice(0, 3).join(', ') + ' et al.'
    : (p.authors || []).join(', ');

  const keywords = (p.keywords || [])
    .map(k => `<span class="keyword">${k}</span>`)
    .join('');

  const doi     = p.doi || '';
  const doiHref = doi.startsWith('http') ? doi : (doi ? `https://doi.org/${doi}` : '');
  const pdfUrl  = p.pdf_url || '';
  const isOA    = p.is_open_access || false;

  const oaBadge = isOA ? `<span class="oa-badge">Open Access</span>` : '';
  const ifBadge = p.impact_factor ? `<span class="if-badge">IF ${p.impact_factor}</span>` : '';
  const citBadge = (p.citation_count && p.citation_count > 0)
    ? `<span class="cit-badge">◈ ${p.citation_count}</span>` : '';

  const doiBtn = doiHref
    ? `<a class="btn-doi" href="${doiHref}" target="_blank" rel="noopener" title="原文页面">
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8">
          <path d="M6 2H3a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1v-3"/>
          <path d="M10 2h4v4"/><path d="M16 2 9 9"/>
        </svg>原文</a>`
    : '';

  let readBtn = '';
  if (pdfUrl) {
    const safeTitle = (p.title_en || '').replace(/"/g, '&quot;');
    readBtn = `<button class="btn-read" onclick="openReader('${pdfUrl.replace(/'/g,"\\'")}','${safeTitle}')" title="在线阅读">
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8">
        <rect x="2" y="1" width="10" height="14" rx="1"/>
        <path d="M5 5h6M5 8h6M5 11h4"/>
      </svg>阅读</button>`;
  } else if (doiHref) {
    readBtn = `<a class="btn-read" href="${doiHref}" target="_blank" rel="noopener" title="跳转查看">
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8">
        <rect x="2" y="1" width="10" height="14" rx="1"/>
        <path d="M5 5h6M5 8h6M5 11h4"/>
      </svg>查看</a>`;
  }

  const safeId = (p.id || '').replace(/'/g, "\\'");
  const bookmarkBtn = `<button class="btn-bookmark${isBookmarked ? ' bookmarked' : ''}" data-id="${p.id || ''}" onclick="toggleBookmark('${safeId}')" title="${isBookmarked ? '取消收藏' : '收藏'}">★</button>`;

  const titleZh  = p.title_zh    ? `<div class="card-title-zh">${p.title_zh}</div>` : '';
  const absLabel = p.abstract_zh ? '摘要 / Abstract' : 'Abstract';
  const absZh    = p.abstract_zh ? `<div class="abstract-zh">${p.abstract_zh}</div>` : '';
  const absEn    = p.abstract_zh
    ? `<div class="abstract-en abstract-en-secondary">${p.abstract_en || ''}</div>`
    : `<div class="abstract-en">${p.abstract_en || ''}</div>`;

  return `
<article class="card">

  <div class="card-top">
    <div class="card-tags">
      <span class="card-tag ${cat.cls}">${cat.zh} / ${cat.en}</span>
      ${oaBadge}
      ${ifBadge}
    </div>
    <span class="card-date">${formatDate(p.date_added)}</span>
  </div>

  <div>
    <div class="card-title-en">${p.title_en || ''}</div>
    ${titleZh}
  </div>

  <div class="card-authors">${authors}</div>

  <div class="card-journal">
    <span class="journal-name">${p.journal || ''}</span>
    <span class="journal-year">${p.year || ''}</span>
    ${citBadge}
  </div>

  <div class="card-divider"></div>

  <div>
    <div class="abstract-label">${absLabel}</div>
    ${absZh}
    ${absEn}
  </div>

  ${keywords ? `<div class="keywords-wrap">${keywords}</div>` : ''}

  <div class="card-footer">
    <div class="card-actions">
      ${readBtn}
      ${doiBtn}
      <button class="btn-cite" onclick="copyBibTeX('${safeId}')">
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8">
          <path d="M4 2h8a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1z"/>
          <path d="M6 2v4l1.5-1 1.5 1V2"/>
        </svg>引用
      </button>
      ${bookmarkBtn}
    </div>
  </div>

</article>`;
}

function formatDate(str) {
  if (!str) return '';
  const [y, m, d] = str.split('-');
  return `${y}/${m}/${d}`;
}

function getFilteredPapers() {
  let papers;

  if (activeCategory === 'all') {
    papers = allPapers;
  } else if (activeCategory === 'week') {
    const cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - 7);
    const cutoffStr = cutoff.toISOString().slice(0, 10);
    papers = allPapers
      .filter(p => (p.date_added || '') >= cutoffStr)
      .sort((a, b) => (b.citation_count || 0) - (a.citation_count || 0));
  } else if (activeCategory === 'bookmarks') {
    const bm = getBookmarks();
    papers = allPapers.filter(p => bm.has(p.id));
  } else {
    papers = allPapers.filter(p => p.category === activeCategory);
  }

  if (activeSearch) {
    const q = activeSearch.toLowerCase();
    papers = papers.filter(p =>
      (p.title_en   || '').toLowerCase().includes(q) ||
      (p.title_zh   || '').toLowerCase().includes(q) ||
      (p.abstract_en|| '').toLowerCase().includes(q) ||
      (p.abstract_zh|| '').toLowerCase().includes(q) ||
      (p.authors    || []).join(' ').toLowerCase().includes(q) ||
      (p.journal    || '').toLowerCase().includes(q)
    );
  }
  return papers;
}

function setFilter(cat) {
  activeCategory = cat;
  document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.cat === cat);
  });
  renderPapers(getFilteredPapers());
}

function setSearch(q) {
  activeSearch = q.trim();
  renderPapers(getFilteredPapers());
}

// ── Stats Chart ───────────────────────────────────────────────────────────────
function renderStats() {
  const cats = ['biomechanics', 'performance', 'supplements', 'preprint'];
  const counts = cats.map(c => allPapers.filter(p => p.category === c).length);
  const labels = cats.map(c => CAT_LABELS[c].zh);
  const colors = cats.map(c => CAT_LABELS[c].color);

  const canvas = document.getElementById('catChart');
  if (!canvas) return;

  const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
  const textColor = isDark ? '#A0907E' : '#8B7D6B';

  if (catChart) catChart.destroy();
  catChart = new Chart(canvas, {
    type: 'doughnut',
    data: {
      labels,
      datasets: [{
        data: counts,
        backgroundColor: colors.map(c => c + 'CC'),
        borderColor: colors,
        borderWidth: 1.5,
        hoverOffset: 6,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: '62%',
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => ` ${ctx.label}: ${ctx.raw} 篇`
          }
        }
      }
    }
  });

  const total = counts.reduce((a, b) => a + b, 0);
  const barWrap = document.getElementById('statsBarWrap');
  if (!barWrap) return;

  const bars = cats.map((c, i) => {
    const pct = total ? Math.round(counts[i] / total * 100) : 0;
    return `
      <div class="stats-bar-row">
        <span class="stats-bar-label">${CAT_LABELS[c].zh}</span>
        <div class="stats-bar-track">
          <div class="stats-bar-fill" style="width:${pct}%;background:${colors[i]}"></div>
        </div>
        <span class="stats-bar-count">${counts[i]}</span>
      </div>`;
  }).join('');

  barWrap.innerHTML = `<div class="stats-bar-title">分类分布 / Category Breakdown</div>${bars}
    <div style="margin-top:10px;font-size:0.72rem;color:var(--text-muted)">共收录 ${allPapers.length} 篇文献</div>`;
}

function updateChartColors() {
  if (catChart) renderStats();
}

function toggleStats() {
  const sec = document.getElementById('statsSection');
  if (!sec) return;
  const show = sec.classList.toggle('show');
  if (show && allPapers.length) renderStats();
}

// ── Deep Read ─────────────────────────────────────────────────────────────────
async function loadDeepRead() {
  try {
    const base = location.pathname.replace(/\/[^/]*$/, '');
    const res  = await fetch(base + '/data/deep_read.json');
    const dr   = await res.json();
    renderDeepRead(dr);
    document.getElementById('deepReadSection').style.display = '';
  } catch (e) {
    console.warn('No deep read data:', e);
  }
}

function renderDeepRead(dr) {
  const oaBadge = dr.is_open_access ? '<span class="oa-badge">Open Access</span>' : '';
  const ifBadge = dr.impact_factor
    ? `<span class="dr-if">IF ${dr.impact_factor}</span>` : '';

  document.getElementById('drPreviewCard').innerHTML = `
    <div class="dr-preview-meta">
      <div class="dr-preview-badges">${oaBadge}${ifBadge}</div>
      <div class="dr-preview-title-en">${dr.title_en || ''}</div>
      <div class="dr-preview-title-zh">${dr.title_zh || ''}</div>
    </div>
    <a class="dr-preview-cta" href="deep-read.html">
      进入精读
      <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M6 4 L10 8 L6 12"/>
      </svg>
    </a>`;
}

// ── BibTeX ────────────────────────────────────────────────────────────────────
function copyBibTeX(id) {
  const p = allPapers.find(x => x.id === id);
  if (!p) return;
  const firstAuthor = (p.authors || ['Unknown'])[0].split(' ').pop();
  const key = firstAuthor + (p.year || '');
  const authors = (p.authors || []).join(' and ');
  const doi = p.doi || '';
  const bibtex = `@article{${key},
  title   = {${(p.title_en || '').replace(/[{}]/g, '')}},
  author  = {${authors}},
  journal = {${p.journal || ''}},
  year    = {${p.year || ''}},
  doi     = {${doi}}
}`;
  navigator.clipboard.writeText(bibtex)
    .then(() => showToast('BibTeX 已复制 ✓'))
    .catch(() => {
      const ta = document.createElement('textarea');
      ta.value = bibtex;
      ta.style.cssText = 'position:fixed;opacity:0';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      showToast('BibTeX 已复制 ✓');
    });
}

function showToast(msg) {
  let t = document.getElementById('toast');
  if (!t) {
    t = document.createElement('div');
    t.id = 'toast';
    t.className = 'toast';
    document.body.appendChild(t);
  }
  t.textContent = msg;
  t.classList.add('toast-show');
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.remove('toast-show'), 2200);
}

// ── PDF Reader Modal ──────────────────────────────────────────────────────────
function openReader(pdfUrl, title) {
  let modal = document.getElementById('readerModal');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'readerModal';
    modal.className = 'reader-modal';
    modal.innerHTML = `
      <div class="reader-overlay" onclick="closeReader()"></div>
      <div class="reader-panel">
        <div class="reader-header">
          <span class="reader-title" id="readerTitle"></span>
          <div class="reader-controls">
            <a class="reader-btn-new" id="readerNewTab" target="_blank" rel="noopener">
              <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8">
                <path d="M6 2H3a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1v-3"/>
                <path d="M10 2h4v4"/><path d="M16 2 9 9"/>
              </svg>新标签页打开
            </a>
            <button class="reader-btn-close" onclick="closeReader()">✕</button>
          </div>
        </div>
        <iframe id="readerFrame" class="reader-frame" allowfullscreen></iframe>
      </div>`;
    document.body.appendChild(modal);
  }

  document.getElementById('readerTitle').textContent = title;
  document.getElementById('readerNewTab').href = pdfUrl;

  const frame = document.getElementById('readerFrame');
  frame.src = '';
  setTimeout(() => {
    frame.src = `https://docs.google.com/viewer?url=${encodeURIComponent(pdfUrl)}&embedded=true`;
  }, 50);

  modal.classList.add('active');
  document.body.style.overflow = 'hidden';
}

function closeReader() {
  const modal = document.getElementById('readerModal');
  if (modal) {
    modal.classList.remove('active');
    document.getElementById('readerFrame').src = '';
    document.body.style.overflow = '';
  }
}

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeReader();
});

// ── Init ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  // Dark mode toggle
  const toggleBtn = document.getElementById('themeToggle');
  if (toggleBtn) toggleBtn.addEventListener('click', toggleTheme);

  // Filter buttons
  document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.addEventListener('click', () => setFilter(btn.dataset.cat));
  });

  // Search
  const searchInput = document.getElementById('searchInput');
  if (searchInput) {
    searchInput.addEventListener('input', () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => setSearch(searchInput.value), 280);
    });
    searchInput.addEventListener('search', () => setSearch(searchInput.value));
  }

  loadPapers();
  loadDeepRead();
});
