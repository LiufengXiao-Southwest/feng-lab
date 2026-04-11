const CAT_LABELS = {
  biomechanics: { zh: '生物力学', en: 'Biomechanics', cls: 'tag-biomechanics' },
  performance:  { zh: '运动表现', en: 'Performance',  cls: 'tag-performance'  },
  supplements:  { zh: '运动补剂', en: 'Supplements',  cls: 'tag-supplements'  },
};

let allPapers = [];
let activeCategory = 'all';

async function loadPapers() {
  try {
    const res = await fetch('data/papers.json');
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
  const authors = p.authors.length > 3
    ? p.authors.slice(0, 3).join(', ') + ' et al.'
    : p.authors.join(', ');

  const keywords = (p.keywords || [])
    .map(k => `<span class="keyword">${k}</span>`)
    .join('');

  const doiHref = p.doi.startsWith('http') ? p.doi : `https://doi.org/${p.doi}`;

  return `
<article class="card">

  <div class="card-top">
    <span class="card-tag ${cat.cls}">${cat.zh} / ${cat.en}</span>
    <span class="card-date">${formatDate(p.date_added)}</span>
  </div>

  <div>
    <div class="card-title-en">${p.title_en}</div>
    <div class="card-title-zh">${p.title_zh}</div>
  </div>

  <div class="card-authors">${authors}</div>

  <div class="card-journal">
    <span class="journal-name">${p.journal}</span>
    <span class="journal-year">${p.year}</span>
  </div>

  <div class="card-divider"></div>

  <div>
    <div class="abstract-label">Abstract / 摘要</div>
    <div class="abstract-en">${p.abstract_en}</div>
    <div class="abstract-zh">${p.abstract_zh}</div>
  </div>

  ${keywords ? `<div class="keywords-wrap">${keywords}</div>` : ''}

  <div class="card-footer">
    <a class="doi-link" href="${doiHref}" target="_blank" rel="noopener">
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8">
        <path d="M6 2H3a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1v-3"/>
        <path d="M10 2h4v4"/>
        <path d="M16 2 9 9"/>
      </svg>
      DOI
    </a>
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

// Bind filter buttons
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.addEventListener('click', () => setFilter(btn.dataset.cat));
  });
  loadPapers();
});
