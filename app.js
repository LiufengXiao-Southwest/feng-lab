const CAT_LABELS = {
  biomechanics: { zh: '生物力学', en: 'Biomechanics', cls: 'tag-biomechanics' },
  performance:  { zh: '运动表现', en: 'Performance',  cls: 'tag-performance'  },
  supplements:  { zh: '运动补剂', en: 'Supplements',  cls: 'tag-supplements'  },
};

let allPapers = [];
let activeCategory = 'all';

async function loadPapers() {
  try {
    const base = location.pathname.replace(/\/[^/]*$/, '');
    const res = await fetch(base + '/data/papers.json');
    const json = await res.json();
    allPapers = json.papers || [];

    // Update last updated date
    const d = document.getElementById('lastUpdated');
    if (d) d.textContent = json.last_updated || '—';

    renderPapers(allPapers);
  } catch (e) {
    document.getElementById('paperGrid').innerHTML =
      '<div class="loading">加载失败，请刷新重试 / Failed to load, please refresh.</div>';
  }
}

function renderPapers(papers) {
  const grid = document.getElementById('paperGrid');
  const count = document.getElementById('paperCount');

  count.textContent = papers.length;

  if (papers.length === 0) {
    grid.innerHTML = '<div class="loading">暂无文献 / No papers found.</div>';
    return;
  }

  grid.innerHTML = papers.map(p => buildCard(p)).join('');
}

function buildCard(p) {
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

  // OA badge
  const oaBadge = isOA
    ? `<span class="oa-badge">Open Access</span>`
    : '';

  // DOI link button
  const doiBtn = doiHref
    ? `<a class="btn-doi" href="${doiHref}" target="_blank" rel="noopener" title="原文页面">
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8">
          <path d="M6 2H3a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1v-3"/>
          <path d="M10 2h4v4"/><path d="M16 2 9 9"/>
        </svg>原文</a>`
    : '';

  // Read button — opens modal for OA PDFs, else goes to DOI page
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

  const titleZh  = p.title_zh    ? `<div class="card-title-zh">${p.title_zh}</div>` : '';
  const absLabel = p.abstract_zh ? 'Abstract / 摘要' : 'Abstract';
  const absZh    = p.abstract_zh ? `<div class="abstract-zh">${p.abstract_zh}</div>` : '';

  return `
<article class="card">

  <div class="card-top">
    <div class="card-tags">
      <span class="card-tag ${cat.cls}">${cat.zh} / ${cat.en}</span>
      ${oaBadge}
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
  </div>

  <div class="card-divider"></div>

  <div>
    <div class="abstract-label">${absLabel}</div>
    <div class="abstract-en">${p.abstract_en || ''}</div>
    ${absZh}
  </div>

  ${keywords ? `<div class="keywords-wrap">${keywords}</div>` : ''}

  <div class="card-footer">
    <div class="card-actions">
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

function setFilter(cat) {
  activeCategory = cat;
  document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.cat === cat);
  });
  const filtered = cat === 'all'
    ? allPapers
    : allPapers.filter(p => p.category === cat);
  renderPapers(filtered);
}

// ── Deep Read ────────────────────────────────────────────────────────────────
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

// ── PDF Reader Modal ─────────────────────────────────────────────────────────
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

  // Try direct embed first; fall back to Google Docs viewer
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

// Close on Escape key
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeReader();
});

// ── Init ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.addEventListener('click', () => setFilter(btn.dataset.cat));
  });
  loadPapers();
  loadDeepRead();
});
