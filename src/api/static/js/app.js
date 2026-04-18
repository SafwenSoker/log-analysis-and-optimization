// Shared utilities

function statusBadge(status) {
  return `<span class="badge badge-${status}">${status}</span>`;
}

function severityBadge(severity) {
  return `<span class="badge badge-${severity}">${severity}</span>`;
}

function fmtDuration(secs) {
  if (!secs) return '—';
  if (secs < 60) return `${Math.round(secs)}s`;
  return `${Math.floor(secs / 60)}m ${Math.round(secs % 60)}s`;
}

// Ingest button
document.getElementById('ingestBtn')?.addEventListener('click', async () => {
  const btn = document.getElementById('ingestBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Ingesting…';
  try {
    const r = await fetch('/jenkins/ingest', { method: 'POST' });
    const data = await r.json();
    alert(`Ingested ${data.ingested} builds (${data.skipped} skipped).`);
    window.location.reload();
  } catch (e) {
    alert('Ingest failed: ' + e);
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-cloud-download me-1"></i>Ingest Logs';
  }
});
