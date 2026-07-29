const CAT_LABELS = {
  biomechanics: { zh: '生物力学', en: 'Biomechanics', cls: 'tag-biomechanics', color: '#C4956A' },
  performance:  { zh: '运动表现', en: 'Performance',  cls: 'tag-performance',  color: '#4A6FA5' },
  supplements:  { zh: '运动补剂', en: 'Supplements',  cls: 'tag-supplements',  color: '#3D7A45' },
  preprint:     { zh: '预印本',   en: 'Preprint',     cls: 'tag-preprint',     color: '#B06A1A' },
};

// Evidence level — an optional `evidence` field on a paper. Absent for now;
// render only when present so older data keeps working untouched.
const EVIDENCE_LABELS = {
  meta:   { zh: 'Meta分析',  en: 'Meta-analysis',   cls: 'ev-meta'   },
  review: { zh: '系统综述',  en: 'Systematic review', cls: 'ev-review' },
  trial:  { zh: 'RCT',       en: 'Randomised trial', cls: 'ev-trial'  },
};

let allPapers = [];
let activeCategory = 'all';
let activeSearch   = '';
let searchTimer    = null;
let catChart       = null;

// ── Helpers ───────────────────────────────────────────────────────────────────
function esc(str) {
  return String(str == null ? '' : str)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function prefersReducedMotion() {
  return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
}

// ── Dark Mode ─────────────────────────────────────────────────────────────────
// Two signals: a stored choice (data-theme attribute, applied inline in <head>)
// always wins; with nothing stored the OS setting decides via CSS.
function isDarkMode() {
  const attr = document.documentElement.getAttribute('data-theme');
  if (attr) return attr === 'dark';
  return !!(window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
}

function toggleTheme() {
  const next = isDarkMode() ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('feng-lab-theme', next);
  if (catChart) updateChartColors();
}

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
    const on = bm.has(id);
    btn.classList.toggle('bookmarked', on);
    btn.title = on ? '取消收藏' : '收藏';
    btn.setAttribute('aria-label', btn.title);
    btn.setAttribute('aria-pressed', String(on));
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
    updateEvidenceFilters();
    renderHeroStats(json);
  } catch (e) {
    const grid = document.getElementById('paperGrid');
    if (grid) {
      grid.removeAttribute('aria-busy');
      grid.innerHTML =
        '<div class="loading">加载失败，请刷新重试 / Failed to load, please refresh.</div>';
    }
  }
}

function renderPapers(papers) {
  const grid = document.getElementById('paperGrid');
  const count = document.getElementById('paperCount');
  if (!grid) return;

  grid.removeAttribute('aria-busy');
  count.textContent = papers.length;
  cardIndex = -1;  // any re-render invalidates the j/k cursor

  if (papers.length === 0) {
    // During a search the archive panel above still has answers — say so
    // rather than implying the whole site is empty.
    grid.innerHTML = activeSearch
      ? '<div class="loading">当天文献无匹配 — 全站归档结果见搜索框下方</div>'
      : '<div class="loading">今日暂无新文献</div>';
    return;
  }

  const bm = getBookmarks();
  grid.innerHTML = papers.map(p => buildCard(p, bm.has(p.id))).join('');
}

// Evidence-level filter buttons only make sense once the data carries the field.
function updateEvidenceFilters() {
  Object.keys(EVIDENCE_LABELS).forEach(key => {
    const btn = document.querySelector(`.filter-btn[data-cat="ev-${key}"]`);
    if (!btn) return;
    const has = allPapers.some(p => p.evidence === key);
    btn.style.display = has ? '' : 'none';
  });
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
  // Only a JCR-sourced number is an impact factor. SCImago's citations-per-doc
  // and OpenAlex's 2-year mean citedness are different measures on different
  // denominators, so labelling either of them "IF" would misstate the figure to
  // anyone scanning the cards — the tooltip alone is not enough.
  const isRealIF = /JCR/i.test(p.if_source || '');
  const ifLabel = isRealIF ? 'IF' : (p.if_source || '被引');
  const ifTitle = p.if_source
    ? ` title="${isRealIF ? '影响因子' : '注意：这不是影响因子'} / Source: ${esc(p.if_source)}"`
    : '';
  const ifBadge = p.impact_factor
    ? `<span class="if-badge${isRealIF ? '' : ' if-badge-proxy'}"${ifTitle}>`
      + `${esc(ifLabel)} ${esc(p.impact_factor)}</span>`
    : '';
  // `journal_tier` — 中科院 / JCR 分区, e.g. "运动科学2区 TOP"
  const tierBadge = p.journal_tier
    ? `<span class="tier-badge" title="期刊分区 / Journal tier">${esc(p.journal_tier)}</span>` : '';
  const citBadge = (p.citation_count && p.citation_count > 0)
    ? `<span class="cit-badge">◈ ${esc(p.citation_count)}</span>` : '';

  const ev = EVIDENCE_LABELS[p.evidence];
  const evBadge = ev
    ? `<span class="ev-badge ${ev.cls}" title="证据等级 / Evidence: ${esc(ev.en)}">${esc(ev.zh)}</span>` : '';

  const doiBtn = doiHref
    ? `<a class="btn-doi" href="${doiHref}" target="_blank" rel="noopener" title="原文页面" aria-label="打开原文页面（新标签页）">
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
          <path d="M6 2H3a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1v-3"/>
          <path d="M10 2h4v4"/><path d="M16 2 9 9"/>
        </svg>原文</a>`
    : '';

  let readBtn = '';
  if (pdfUrl) {
    const safeTitle = (p.title_en || '').replace(/"/g, '&quot;');
    readBtn = `<button class="btn-read" onclick="openReader('${pdfUrl.replace(/'/g,"\\'")}','${safeTitle}')" title="在线阅读" aria-label="在线阅读 PDF">
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
        <rect x="2" y="1" width="10" height="14" rx="1"/>
        <path d="M5 5h6M5 8h6M5 11h4"/>
      </svg>阅读</button>`;
  } else if (doiHref) {
    readBtn = `<a class="btn-read" href="${doiHref}" target="_blank" rel="noopener" title="跳转查看" aria-label="跳转查看原文（新标签页）">
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
        <rect x="2" y="1" width="10" height="14" rx="1"/>
        <path d="M5 5h6M5 8h6M5 11h4"/>
      </svg>查看</a>`;
  }

  // Optional full-text location (PMC record, repository copy …) alongside the
  // publisher link. `fulltext_label` is a ready-made Chinese label when the
  // backend supplies one; otherwise fall back to the raw type, then to 「全文」.
  const ftType  = p.fulltext_type ? String(p.fulltext_type).replace(/_/g, ' ').toUpperCase() : '';
  const ftLabel = p.fulltext_label || (ftType ? `全文 · ${ftType}` : '全文');
  const fulltextBtn = p.fulltext_url
    ? `<a class="btn-fulltext" href="${esc(p.fulltext_url)}" target="_blank" rel="noopener"
          title="${esc(ftLabel)}" aria-label="打开${esc(ftLabel)}（新标签页）">
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
          <path d="M8 2.5S6 1 3.5 1H1v11h2.5C6 12 8 13.5 8 13.5s2-1.5 4.5-1.5H15V1h-2.5C10 1 8 2.5 8 2.5z"/>
          <path d="M8 2.5v11"/>
        </svg>${esc(ftLabel)}</a>`
    : '';

  const safeId = (p.id || '').replace(/'/g, "\\'");
  const bookmarkLabel = isBookmarked ? '取消收藏' : '收藏';
  const bookmarkBtn = `<button class="btn-bookmark${isBookmarked ? ' bookmarked' : ''}" data-id="${esc(p.id)}" onclick="toggleBookmark('${safeId}')" title="${bookmarkLabel}" aria-label="${bookmarkLabel}" aria-pressed="${isBookmarked}">★</button>`;
  const cardTopRight = `<div class="card-top-right">${bookmarkBtn}<span class="card-date">${esc(formatDate(p.date_added))}</span></div>`;

  const titleZh  = p.title_zh    ? `<div class="card-title-zh">${esc(p.title_zh)}</div>` : '';

  // Optional one-line takeaway, shown right under the titles.
  const tldrEn = p.tldr_en ? `<div class="card-tldr-en">${esc(p.tldr_en)}</div>` : '';
  const tldr = p.tldr_zh
    ? `<div class="card-tldr">
         <span class="card-tldr-label">结论</span>
         <div><div>${esc(p.tldr_zh)}</div>${tldrEn}</div>
       </div>`
    : '';

  const absLabel = p.abstract_zh ? '摘要 / Abstract' : 'Abstract';
  const absZh    = p.abstract_zh ? `<div class="abstract-zh">${esc(p.abstract_zh)}</div>` : '';
  const absEn    = p.abstract_zh
    ? `<div class="abstract-en abstract-en-secondary">${esc(p.abstract_en)}</div>`
    : `<div class="abstract-en">${esc(p.abstract_en)}</div>`;

  return `
<article class="card" tabindex="-1" data-id="${esc(p.id)}" aria-label="${esc(p.title_zh || p.title_en || '文献')}">

  <div class="card-top">
    <div class="card-tags">
      <span class="card-tag ${cat.cls}">${cat.zh} / ${cat.en}</span>
      ${evBadge}
      ${oaBadge}
      ${ifBadge}
      ${tierBadge}
    </div>
    ${cardTopRight}
  </div>

  <div>
    <div class="card-title-en">${esc(p.title_en)}</div>
    ${titleZh}
    ${tldr}
  </div>

  <div class="card-authors">${authors}</div>

  <div class="card-journal">
    <span class="journal-name">${esc(p.journal)}</span>
    <span class="journal-year">${esc(p.year)}</span>
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
    <button class="btn-cite" onclick="copyBibTeX('${safeId}')" title="复制 BibTeX" aria-label="复制 BibTeX 引用">
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
        <path d="M4 2h8a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1z"/>
        <path d="M6 2v4l1.5-1 1.5 1V2"/>
      </svg>引用
    </button>
    <div class="card-actions">
      ${fulltextBtn}
      ${readBtn}
      ${doiBtn}
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
  } else if (activeCategory.startsWith('ev-')) {
    const level = activeCategory.slice(3);
    papers = allPapers.filter(p => p.evidence === level);
  } else {
    papers = allPapers.filter(p => p.category === activeCategory);
  }

  if (activeSearch) {
    const q = activeSearch.toLowerCase();
    papers = papers.filter(p =>
      (p.title_en   || '').toLowerCase().includes(q) ||
      (p.title_zh   || '').toLowerCase().includes(q) ||
      (p.tldr_zh    || '').toLowerCase().includes(q) ||
      (p.tldr_en    || '').toLowerCase().includes(q) ||
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
  runGlobalSearch(activeSearch);
}

// ── Hero Stats ────────────────────────────────────────────────────────────────
function renderHeroStats(json) {
  const papers = json.papers || [];
  const today = new Date().toISOString().slice(0, 10);
  const todayCount = papers.filter(p => (p.date_added || '').startsWith(today)).length;
  const lastDate = json.last_updated || '';

  const el = (id, val) => { const e = document.getElementById(id); if (e) e.textContent = val; };
  el('heroTotal', papers.length);
  el('heroToday', todayCount || '0');
  // Show last updated as MM/DD
  if (lastDate) {
    const parts = lastDate.split('-');
    el('heroLastDate', parts.length === 3 ? `${parts[1]}/${parts[2]}` : lastDate);
  }
}

// ── Stats Chart ───────────────────────────────────────────────────────────────
// chart.js is ~200 KB and lives behind a toggle (hidden entirely on mobile),
// so it is fetched from vendor/ the first time the panel is opened.
let chartLoader = null;

function ensureChart() {
  if (window.Chart) return Promise.resolve(true);
  if (chartLoader) return chartLoader;
  chartLoader = new Promise(resolve => {
    const s = document.createElement('script');
    s.src = 'vendor/chart.umd.min.js';
    s.onload  = () => resolve(true);
    s.onerror = () => { chartLoader = null; resolve(false); };
    document.head.appendChild(s);
  });
  return chartLoader;
}

function renderStats() {
  const cats = ['biomechanics', 'performance', 'supplements', 'preprint'];
  const counts = cats.map(c => allPapers.filter(p => p.category === c).length);
  const labels = cats.map(c => CAT_LABELS[c].zh);
  const colors = cats.map(c => CAT_LABELS[c].color);

  // The doughnut is optional — the bar breakdown below always renders.
  const canvas = document.getElementById('catChart');
  if (canvas && window.Chart) {
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
        animation: prefersReducedMotion() ? false : undefined,
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
  }

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
  const btn = document.getElementById('statsToggleBtn');
  if (!sec) return;
  const show = sec.classList.toggle('show');
  if (btn) {
    btn.classList.toggle('active', show);
    btn.setAttribute('aria-expanded', String(show));
  }
  if (show && allPapers.length) {
    ensureChart().then(() => renderStats());
  }
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
    ? `<span class="dr-if">IF ${esc(dr.impact_factor)}</span>` : '';
  const citBadge = (dr.citation_count && dr.citation_count > 0)
    ? `<span class="cit-badge">◈ ${esc(dr.citation_count)}</span>` : '';
  const journalLine = [dr.journal, dr.year].filter(Boolean).join(' · ');

  document.getElementById('drPreviewCard').innerHTML = `
    <div class="dr-preview-meta">
      <div class="dr-preview-badges">${oaBadge}${ifBadge}${citBadge}</div>
      <div class="dr-preview-title-en">${esc(dr.title_en)}</div>
      <div class="dr-preview-title-zh">${esc(dr.title_zh)}</div>
      ${journalLine ? `<div style="margin-top:8px;font-size:0.72rem;color:var(--text-muted);font-style:italic;font-family:var(--font-serif)">${journalLine}</div>` : ''}
    </div>
    <a class="dr-preview-cta" href="deep-read.html">
      进入精读
      <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2">
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

// ── Global Search (whole archive) ─────────────────────────────────────────────
// The homepage only holds the current day. The 190-entry archive is indexed
// client-side with MiniSearch the first time the search box is focused, so the
// first paint stays free of the 416 KB archive.json download.
const GLOBAL_SEARCH_LIMIT = 12;

let searchIndex   = null;   // MiniSearch instance
let searchLoading = null;   // in-flight build promise
let searchFailed  = false;

// Chinese needs real segmentation — the built-in tokenizer treats a whole
// CJK run as one term. Intl.Segmenter is native everywhere modern; the
// fallback splits per character.
const zhSegmenter = ('Segmenter' in Intl)
  ? new Intl.Segmenter('zh-CN', { granularity: 'word' })
  : null;

const CJK_RUN   = /[぀-ヿ㐀-鿿豈-﫿]+/g;
const LATIN_RUN = /[a-z0-9À-ɏ]+/gi;

function tokenizeMixed(text) {
  const raw = String(text == null ? '' : text).toLowerCase();
  const tokens = raw.match(LATIN_RUN) || [];

  (raw.match(CJK_RUN) || []).forEach(run => {
    if (zhSegmenter) {
      for (const seg of zhSegmenter.segment(run)) {
        const t = seg.segment.trim();
        if (t) tokens.push(t);
      }
    } else {
      for (const ch of run) tokens.push(ch);
    }
  });

  return tokens;
}

// archive.json repeats a paper on every day it stayed in the digest — index
// each paper once, keeping the most recent appearance for the date link.
function dedupeArchive(dates) {
  const byId = new Map();
  Object.keys(dates || {}).forEach(date => {
    (dates[date] || []).forEach(p => {
      const key = p.id || (p.doi || p.title_en || '') + date;
      const prev = byId.get(key);
      if (!prev || date > prev._date) byId.set(key, Object.assign({}, p, { _date: date, _sid: key }));
    });
  });
  return [...byId.values()];
}

function buildSearchIndex() {
  if (searchIndex) return Promise.resolve(searchIndex);
  if (searchLoading) return searchLoading;

  searchLoading = (async () => {
    if (typeof MiniSearch === 'undefined') throw new Error('MiniSearch not loaded');

    const base = location.pathname.replace(/\/[^/]*$/, '');
    const res  = await fetch(base + '/data/archive.json');
    const json = await res.json();
    const docs = dedupeArchive(json.dates);

    const mini = new MiniSearch({
      idField: '_sid',
      fields: ['title_zh', 'title_en', 'keywords', 'journal'],
      storeFields: ['id', 'title_zh', 'title_en', 'journal', 'year', 'category', 'doi', 'date_added', '_date'],
      tokenize: tokenizeMixed,
      processTerm: term => term,   // tokenizer already lowercases
      extractField: (doc, field) => {
        const v = doc[field];
        if (Array.isArray(v)) return v.join(' ');
        return v == null ? '' : String(v);
      },
      searchOptions: {
        prefix: true,
        fuzzy: 0.2,
        boost: { title_zh: 3, title_en: 2 },
      },
    });

    mini.addAll(docs);
    searchIndex = mini;
    return mini;
  })().catch(err => {
    console.warn('Global search unavailable:', err);
    searchFailed = true;
    searchLoading = null;
    throw err;
  });

  return searchLoading;
}

function getSearchPanel() {
  return document.getElementById('searchResults');
}

function showSearchPanel(html) {
  const panel = getSearchPanel();
  const input = document.getElementById('searchInput');
  if (!panel) return;
  panel.innerHTML = html;
  panel.classList.add('show');
  if (input) input.setAttribute('aria-expanded', 'true');
}

function closeSearchPanel() {
  const panel = getSearchPanel();
  const input = document.getElementById('searchInput');
  if (panel) panel.classList.remove('show');
  if (input) input.setAttribute('aria-expanded', 'false');
}

function buildSearchResultRow(hit, date) {
  const cat = CAT_LABELS[hit.category];
  const catTag = cat ? `<span class="card-tag ${cat.cls}">${cat.zh}</span>` : '';
  const href = `archive.html#date=${encodeURIComponent(date || '')}&p=${encodeURIComponent(hit.id || '')}`;

  return `
<a class="search-result" href="${href}" role="option">
  <div class="search-result-title">${esc(hit.title_en || hit.title_zh || '')}</div>
  ${hit.title_zh ? `<div class="search-result-zh">${esc(hit.title_zh)}</div>` : ''}
  <div class="search-result-meta">
    ${catTag}
    <span class="journal-name">${esc(hit.journal || '')}</span>
    <span>${esc(hit.year || '')}</span>
    <span>· ${esc(date || '')}</span>
  </div>
</a>`;
}

function renderGlobalResults(query, hits) {
  if (!hits.length) {
    showSearchPanel(`<div class="search-results-empty">全站未找到「${esc(query)}」相关文献</div>`);
    return;
  }

  // `_date` is the most recent archive day this paper appeared on.
  const rows = hits.slice(0, GLOBAL_SEARCH_LIMIT)
    .map(h => buildSearchResultRow(h, h._date || h.date_added))
    .join('');

  showSearchPanel(`
    <div class="search-results-head">
      <span>全站归档 · ${hits.length} 条结果</span>
      <span>↵ 跳转归档</span>
    </div>
    ${rows}`);
}

function runGlobalSearch(query) {
  const q = (query || '').trim();
  if (!q) { closeSearchPanel(); return; }
  if (searchFailed) return;

  buildSearchIndex()
    .then(mini => {
      // The box may have moved on while the index was building.
      const input = document.getElementById('searchInput');
      if (input && input.value.trim() !== q) return;
      renderGlobalResults(q, mini.search(q));
    })
    .catch(() => {
      showSearchPanel('<div class="search-results-empty">全站检索暂不可用</div>');
    });
}

// ── Keyboard Navigation ───────────────────────────────────────────────────────
const SHORTCUTS = [
  { keys: ['/'],           desc: '聚焦搜索框' },
  { keys: ['j'],           desc: '下一篇文献' },
  { keys: ['k'],           desc: '上一篇文献' },
  { keys: ['b'],           desc: '收藏 / 取消收藏当前文献' },
  { keys: ['?'],           desc: '显示本快捷键面板' },
  { keys: ['Esc'],         desc: '关闭面板 / 弹窗' },
];

let cardIndex = -1;

function isTypingTarget(el) {
  if (!el) return false;
  const tag = el.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable;
}

function getCards() {
  return [...document.querySelectorAll('#paperGrid .card')];
}

function moveCardFocus(delta) {
  const cards = getCards();
  if (!cards.length) return;

  cardIndex = Math.max(0, Math.min(cards.length - 1, cardIndex + delta));
  cards.forEach((c, i) => c.classList.toggle('card-active', i === cardIndex));

  const card = cards[cardIndex];
  card.focus({ preventScroll: true });
  card.scrollIntoView({ block: 'center', behavior: prefersReducedMotion() ? 'auto' : 'smooth' });
}

function bookmarkFocusedCard() {
  const cards = getCards();
  const card = cards[cardIndex];
  if (!card) { showToast('先用 j / k 选中一篇文献'); return; }
  const id = card.dataset.id;
  if (id) toggleBookmark(id);
}

function toggleShortcutHelp(force) {
  let modal = document.getElementById('kbdModal');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'kbdModal';
    modal.className = 'kbd-modal';
    modal.setAttribute('role', 'dialog');
    modal.setAttribute('aria-modal', 'true');
    modal.setAttribute('aria-label', '键盘快捷键');
    modal.innerHTML = `
      <div class="kbd-overlay" onclick="toggleShortcutHelp(false)"></div>
      <div class="kbd-panel">
        <div class="kbd-panel-title">键盘快捷键</div>
        <div class="kbd-panel-sub">Keyboard shortcuts</div>
        <div class="kbd-list">
          ${SHORTCUTS.map(s => `
            <div class="kbd-row">
              <span>${esc(s.desc)}</span>
              <span>${s.keys.map(k => `<kbd>${esc(k)}</kbd>`).join(' ')}</span>
            </div>`).join('')}
        </div>
        <button class="kbd-close" onclick="toggleShortcutHelp(false)">关闭 / Close</button>
      </div>`;
    document.body.appendChild(modal);
  }

  const show = force === undefined ? !modal.classList.contains('active') : !!force;
  modal.classList.toggle('active', show);
  if (show) modal.querySelector('.kbd-close').focus();
}

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    closeReader();
    closeSearchPanel();
    toggleShortcutHelp(false);
    return;
  }

  // Never hijack a key the visitor is typing into a field, or a browser
  // shortcut (Ctrl/Cmd/Alt combinations).
  if (isTypingTarget(e.target) || e.ctrlKey || e.metaKey || e.altKey) return;

  switch (e.key) {
    case '/': {
      const input = document.getElementById('searchInput');
      if (input) { e.preventDefault(); input.focus(); input.select(); }
      break;
    }
    case '?':
      e.preventDefault();
      toggleShortcutHelp();
      break;
    case 'j':
      e.preventDefault();
      moveCardFocus(1);
      break;
    case 'k':
      e.preventDefault();
      moveCardFocus(-1);
      break;
    case 'b':
      e.preventDefault();
      bookmarkFocusedCard();
      break;
  }
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

    // Warm the archive index on first focus — nothing is fetched before this.
    searchInput.addEventListener('focus', () => {
      buildSearchIndex().catch(() => {});
      if (searchInput.value.trim()) runGlobalSearch(searchInput.value);
    }, { once: false });

    // Enter opens the top hit
    searchInput.addEventListener('keydown', e => {
      if (e.key === 'Enter') {
        const first = document.querySelector('#searchResults .search-result');
        if (first) { e.preventDefault(); window.location.href = first.getAttribute('href'); }
      }
    });
  }

  // Clicking outside the search box dismisses the global results
  document.addEventListener('click', e => {
    if (!e.target.closest('.search-wrap')) closeSearchPanel();
  });

  loadPapers();
  loadDeepRead();
});
