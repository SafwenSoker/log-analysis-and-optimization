async function loadFlaky() {
  const [flakyRes, failingRes] = await Promise.all([
    fetch('/api/model/flaky?status=FLAKY&limit=100').then(r => r.json()),
    fetch('/api/model/flaky?status=CONSISTENTLY_FAILING&limit=50').then(r => r.json()),
  ]);

  const flaky   = flakyRes.scenarios   || [];
  const failing = failingRes.scenarios || [];

  document.getElementById('flakyCount').textContent   = flaky.length;
  document.getElementById('failingCount').textContent = failing.length;
  document.getElementById('flakyTableCount').textContent   = flaky.length;
  document.getElementById('failingTableCount').textContent = failing.length;

  const totalTracked = flaky.length + failing.length;
  const flakyRate    = totalTracked ? (flaky.length / totalTracked * 100).toFixed(1) : '0';
  document.getElementById('flakyRate').textContent   = flakyRate + '%';
  document.getElementById('stableCount').textContent = '—';

  // Flaky table
  const flakyBody = document.getElementById('flakyBody');
  if (!flaky.length) {
    flakyBody.innerHTML = '<tr><td colspan="6" class="text-center py-3 text-muted">No flaky scenarios found. Click Recompute first.</td></tr>';
  } else {
    flakyBody.innerHTML = flaky.map(s => `
      <tr>
        <td class="small" style="max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
            title="${esc(s.scenario_name)}">${esc(s.scenario_name)}</td>
        <td class="small">${s.job_type}</td>
        <td>${s.total_runs}</td>
        <td><span class="text-danger fw-semibold">${(s.fail_rate * 100).toFixed(0)}%</span></td>
        <td>${(s.alternation_rate * 100).toFixed(0)}%</td>
        <td>${runHistory(s.run_history)}</td>
      </tr>`).join('');
  }

  // Failing table
  const failBody = document.getElementById('failingBody');
  if (!failing.length) {
    failBody.innerHTML = '<tr><td colspan="4" class="text-center py-3 text-muted">None found.</td></tr>';
  } else {
    failBody.innerHTML = failing.map(s => `
      <tr>
        <td class="small" style="max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
            title="${esc(s.scenario_name)}">${esc(s.scenario_name)}</td>
        <td class="small">${s.job_type}</td>
        <td>${s.total_runs}</td>
        <td><span class="text-danger fw-semibold">${(s.fail_rate * 100).toFixed(0)}%</span></td>
      </tr>`).join('');
  }
}

function runHistory(history) {
  if (!history?.length) return '—';
  return history.slice(-10).map(r =>
    `<span style="display:inline-block;width:10px;height:10px;border-radius:2px;margin:1px;background:${r === 'PASS' ? '#198754' : '#dc3545'}" title="${r}"></span>`
  ).join('');
}

function esc(str) {
  return String(str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

document.getElementById('recomputeBtn').addEventListener('click', async () => {
  const btn = document.getElementById('recomputeBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Computing…';
  try {
    await fetch('/api/model/flaky/compute/sync', { method: 'POST' });
    await loadFlaky();
  } catch(e) {
    alert('Failed: ' + e);
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-arrow-clockwise me-1"></i>Recompute';
  }
});

loadFlaky();
