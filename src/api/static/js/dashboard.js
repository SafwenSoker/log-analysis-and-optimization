const PAGE_SIZE = 50;
let currentPage = 0;
let totalBuilds  = 0;

const STATUS_COLORS = {
  SUCCESS: '#198754', FAILURE: '#dc3545', UNSTABLE: '#fd7e14',
  ABORTED: '#6c757d', UNKNOWN: '#adb5bd',
};

async function loadModelStatus() {
  const banner = document.getElementById('modelBanner');
  const text   = document.getElementById('modelBannerText');
  const acc    = document.getElementById('statAccuracy');
  try {
    const s = await fetch('/api/model/status').then(r => r.json());
    if (s.trained) {
      banner.className = 'alert alert-success d-flex align-items-center gap-3 mb-3 py-2';
      text.textContent = `Model: ${s.model} · Accuracy: ${(s.accuracy * 100).toFixed(1)}% · F1: ${(s.f1_weighted * 100).toFixed(1)}% · Trained: ${s.trained_at?.slice(0, 10) || '—'} · ${s.n_samples} samples`;
      acc.textContent  = `${(s.accuracy * 100).toFixed(0)}%`;
    } else {
      banner.className = 'alert alert-warning d-flex align-items-center gap-3 mb-3 py-2';
      text.textContent = 'No trained model found. Ingest logs first, then click Train Model.';
      acc.textContent  = '—';
    }
  } catch (e) {
    text.textContent = 'Could not load model status.';
  }
}

async function loadStats() {
  const data = await fetch('/api/builds/stats').then(r => r.json());
  document.getElementById('statTotal').textContent    = data.total_builds ?? '—';
  document.getElementById('statSuccess').textContent  = data.by_status?.SUCCESS  ?? 0;
  document.getElementById('statFailure').textContent  = data.by_status?.FAILURE  ?? 0;
  document.getElementById('statFlaky').textContent    = data.flaky_count ?? '—';
  const unstable = (data.by_status?.UNSTABLE ?? 0) + (data.by_status?.ABORTED ?? 0);
  document.getElementById('statUnstable').textContent = unstable;

  // Status donut
  const statuses = Object.entries(data.by_status || {});
  new Chart(document.getElementById('statusChart'), {
    type: 'doughnut',
    data: {
      labels: statuses.map(([k]) => k),
      datasets: [{ data: statuses.map(([, v]) => v), backgroundColor: statuses.map(([k]) => STATUS_COLORS[k] || '#adb5bd') }],
    },
    options: { plugins: { legend: { position: 'bottom', labels: { font: { size: 10 } } } }, cutout: '60%' },
  });

  // Job type bar
  const jobs = Object.entries(data.by_job_type || {});
  new Chart(document.getElementById('jobChart'), {
    type: 'bar',
    data: {
      labels: jobs.map(([k]) => k),
      datasets: [{ data: jobs.map(([, v]) => v), backgroundColor: '#0d6efd88', borderColor: '#0d6efd', borderWidth: 1 }],
    },
    options: { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } },
  });

  // Error categories horizontal bar
  const cats = Object.entries(data.by_error_category || {}).slice(0, 7);
  new Chart(document.getElementById('errorChart'), {
    type: 'bar',
    data: {
      labels: cats.map(([k]) => k.replace(/_/g, ' ')),
      datasets: [{ data: cats.map(([, v]) => v), backgroundColor: '#dc354566', borderColor: '#dc3545', borderWidth: 1 }],
    },
    options: {
      indexAxis: 'y',
      plugins: { legend: { display: false } },
      scales: { x: { beginAtZero: true, ticks: { precision: 0 } } },
    },
  });

  // Model CV comparison chart
  loadModelChart();
}

async function loadModelChart() {
  try {
    const m = await fetch('/api/model/metrics').then(r => r.ok ? r.json() : null);
    if (!m) return;
    const names = Object.keys(m.cv_results || {});
    const f1s   = names.map(n => +(m.cv_results[n].f1_weighted_mean * 100).toFixed(1));
    const accs  = names.map(n => +(m.cv_results[n].accuracy_mean * 100).toFixed(1));
    new Chart(document.getElementById('modelChart'), {
      type: 'bar',
      data: {
        labels: names,
        datasets: [
          { label: 'F1 Weighted (%)', data: f1s, backgroundColor: '#0d6efd88', borderColor: '#0d6efd', borderWidth: 1 },
          { label: 'Accuracy (%)',    data: accs, backgroundColor: '#19875488', borderColor: '#198754', borderWidth: 1 },
        ],
      },
      options: {
        plugins: { legend: { position: 'bottom', labels: { font: { size: 10 } } } },
        scales: { y: { beginAtZero: true, max: 100 } },
      },
    });
  } catch (e) { /* no model yet */ }
}

async function loadBuilds() {
  const jobType = document.getElementById('filterJobType').value;
  const status  = document.getElementById('filterStatus').value;
  const params  = new URLSearchParams({ limit: PAGE_SIZE, offset: currentPage * PAGE_SIZE });
  if (jobType) params.set('job_type', jobType);
  if (status)  params.set('status', status);

  const data = await fetch(`/api/builds?${params}`).then(r => r.json());
  totalBuilds = data.total;

  const tbody = document.getElementById('buildsBody');
  if (!data.builds.length) {
    tbody.innerHTML = '<tr><td colspan="11" class="text-center py-4 text-muted">No builds. Click "Ingest Logs" to load log files.</td></tr>';
    updatePagination();
    return;
  }

  // Fetch analyses for these builds
  const buildIds = data.builds.map(b => b.id);
  const analyses = {};
  await Promise.all(buildIds.map(async id => {
    try {
      const a = await fetch(`/api/analysis/${id}`).then(r => r.ok ? r.json() : null);
      if (a) analyses[id] = a;
    } catch (_) {}
  }));

  tbody.innerHTML = data.builds.map(b => {
    const a = analyses[b.id];
    const pred  = a?.predicted_category?.replace(/_/g, ' ') || '—';
    const conf  = a?.confidence_score ? `${(a.confidence_score * 100).toFixed(0)}%` : '—';
    const sev   = a?.severity || '';
    return `
    <tr onclick="location.href='/builds/${b.id}'">
      <td class="text-muted small">${b.id}</td>
      <td class="fw-medium small">${b.job_type}</td>
      <td>#${b.build_number}</td>
      <td>${statusBadge(b.status)}</td>
      <td><span class="badge badge-${sev} small">${pred}</span></td>
      <td class="small">${conf}</td>
      <td>${b.tests_run ?? 0}</td>
      <td>${b.test_failures ? `<span class="text-danger fw-semibold">${b.test_failures}</span>` : '0'}</td>
      <td class="small">${fmtDuration(b.duration_seconds)}</td>
      <td>${b.analysis_done ? '<i class="bi bi-check-circle-fill text-success"></i>' : '<i class="bi bi-clock text-muted"></i>'}</td>
      <td>
        <button class="btn btn-outline-primary py-0 px-2" style="font-size:0.75rem"
          onclick="event.stopPropagation(); analyseOne(${b.id}, this)">
          <i class="bi bi-cpu"></i>
        </button>
      </td>
    </tr>`;
  }).join('');

  updatePagination();
}

function updatePagination() {
  const start = currentPage * PAGE_SIZE + 1;
  const end   = Math.min((currentPage + 1) * PAGE_SIZE, totalBuilds);
  document.getElementById('paginationInfo').textContent =
    totalBuilds ? `Showing ${start}–${end} of ${totalBuilds}` : 'No builds';
  document.getElementById('prevPage').disabled = currentPage === 0;
  document.getElementById('nextPage').disabled = end >= totalBuilds;
}

async function analyseOne(buildId, btn) {
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
  try {
    const result = await fetch(`/api/analysis/${buildId}/sync`, { method: 'POST' }).then(r => r.json());
    const row = btn.closest('tr');
    const cells = row.cells;
    const pred = result.predicted_category?.replace(/_/g, ' ') || '—';
    const conf = result.confidence_score ? `${(result.confidence_score * 100).toFixed(0)}%` : '—';
    const sev  = result.severity || '';
    cells[4].innerHTML = `<span class="badge badge-${sev} small">${pred}</span>`;
    cells[5].textContent = conf;
    cells[9].innerHTML  = '<i class="bi bi-check-circle-fill text-success"></i>';
  } catch (_) {}
  btn.disabled = false;
  btn.innerHTML = '<i class="bi bi-cpu"></i>';
}

// Train button
document.getElementById('trainBtn').addEventListener('click', async () => {
  const btn = document.getElementById('trainBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Training…';
  document.getElementById('modelBannerText').textContent = 'Training in progress — this may take a minute…';
  try {
    await fetch('/api/model/train/sync', { method: 'POST' });
    await loadModelStatus();
    await loadModelChart();
  } catch (e) {
    alert('Training failed: ' + e);
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-play-fill me-1"></i>Train Model';
  }
});

// Analyse all unanalysed builds
document.getElementById('analyseAllBtn').addEventListener('click', async () => {
  const btn = document.getElementById('analyseAllBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Queuing…';
  const data = await fetch('/api/builds?limit=500').then(r => r.json());
  const unanalysed = data.builds.filter(b => !b.analysis_done);
  for (const b of unanalysed) {
    await fetch(`/api/analysis/${b.id}`, { method: 'POST' });
  }
  setTimeout(() => {
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-cpu me-1"></i>Analyse All';
    loadBuilds();
  }, 2000);
});

// Filters
['filterJobType', 'filterStatus'].forEach(id =>
  document.getElementById(id).addEventListener('change', () => { currentPage = 0; loadBuilds(); })
);
document.getElementById('prevPage').addEventListener('click', () => { currentPage--; loadBuilds(); });
document.getElementById('nextPage').addEventListener('click', () => { currentPage++; loadBuilds(); });

// File upload
document.getElementById('uploadInput').addEventListener('change', async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const form = new FormData();
  form.append('file', file);
  const r = await fetch('/api/upload?analyse=true', { method: 'POST', body: form });
  const data = await r.json();
  r.ok ? (alert(`Uploaded build #${data.build_id}. Analysis queued.`), loadBuilds())
       : alert('Upload failed: ' + (data.detail || 'unknown'));
  e.target.value = '';
});

// Init
loadModelStatus();
loadStats();
loadBuilds();
