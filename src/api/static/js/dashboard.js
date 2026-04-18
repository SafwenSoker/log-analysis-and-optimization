// Dashboard page logic

const PAGE_SIZE = 50;
let currentPage = 0;
let totalBuilds = 0;

const CHART_COLORS = {
  SUCCESS:  '#198754', FAILURE: '#dc3545', UNSTABLE: '#fd7e14',
  ABORTED:  '#6c757d', UNKNOWN: '#adb5bd',
};

// Load stats + charts
async function loadStats() {
  const data = await fetch('/api/builds/stats').then(r => r.json());
  document.getElementById('statTotal').textContent   = data.total_builds ?? '—';
  document.getElementById('statSuccess').textContent = data.by_status?.SUCCESS  ?? 0;
  document.getElementById('statFailure').textContent = data.by_status?.FAILURE  ?? 0;
  const unstable = (data.by_status?.UNSTABLE ?? 0) + (data.by_status?.ABORTED ?? 0);
  document.getElementById('statUnstable').textContent = unstable;

  // Status donut
  const statuses = Object.entries(data.by_status || {});
  new Chart(document.getElementById('statusChart'), {
    type: 'doughnut',
    data: {
      labels: statuses.map(([k]) => k),
      datasets: [{ data: statuses.map(([, v]) => v), backgroundColor: statuses.map(([k]) => CHART_COLORS[k] || '#adb5bd') }],
    },
    options: { plugins: { legend: { position: 'bottom', labels: { font: { size: 11 } } } }, cutout: '65%' },
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
      datasets: [{ data: cats.map(([, v]) => v), backgroundColor: '#dc354588', borderColor: '#dc3545', borderWidth: 1 }],
    },
    options: {
      indexAxis: 'y',
      plugins: { legend: { display: false } },
      scales: { x: { beginAtZero: true, ticks: { precision: 0 } } },
    },
  });
}

// Load builds table
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
    tbody.innerHTML = '<tr><td colspan="11" class="text-center py-4 text-muted">No builds found. Click "Ingest Logs" to load your log files.</td></tr>';
    return;
  }

  tbody.innerHTML = data.builds.map(b => `
    <tr onclick="location.href='/builds/${b.id}'">
      <td class="text-muted">${b.id}</td>
      <td><span class="fw-medium">${b.job_type}</span></td>
      <td>#${b.build_number}</td>
      <td>${statusBadge(b.status)}</td>
      <td><code class="small">${b.cucumber_tags || '—'}</code></td>
      <td>${b.tests_run ?? 0}</td>
      <td>${b.test_failures ? `<span class="text-danger fw-semibold">${b.test_failures}</span>` : '0'}</td>
      <td>${fmtDuration(b.duration_seconds)}</td>
      <td class="small text-muted">${b.finished_at || '—'}</td>
      <td>${b.analysis_done ? '<i class="bi bi-check-circle-fill text-success"></i>' : '<i class="bi bi-clock text-muted"></i>'}</td>
      <td>
        <button class="btn btn-xs btn-outline-primary py-0 px-2" onclick="event.stopPropagation(); analyseOne(${b.id}, this)">
          <i class="bi bi-cpu"></i>
        </button>
      </td>
    </tr>
  `).join('');

  const start = currentPage * PAGE_SIZE + 1;
  const end   = Math.min((currentPage + 1) * PAGE_SIZE, totalBuilds);
  document.getElementById('paginationInfo').textContent = `Showing ${start}–${end} of ${totalBuilds}`;
  document.getElementById('prevPage').disabled = currentPage === 0;
  document.getElementById('nextPage').disabled = end >= totalBuilds;
}

async function analyseOne(buildId, btn) {
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
  await fetch(`/api/analysis/${buildId}`, { method: 'POST' });
  setTimeout(() => { btn.disabled = false; btn.innerHTML = '<i class="bi bi-cpu"></i>'; loadBuilds(); }, 1500);
}

// Filter change
['filterJobType', 'filterStatus'].forEach(id => {
  document.getElementById(id).addEventListener('change', () => { currentPage = 0; loadBuilds(); });
});

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
  if (r.ok) {
    alert(`Uploaded build #${data.build_id}. Analysis queued.`);
    loadBuilds();
  } else {
    alert('Upload failed: ' + (data.detail || 'unknown error'));
  }
  e.target.value = '';
});

// Init
loadStats();
loadBuilds();
