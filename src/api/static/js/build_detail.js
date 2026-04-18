// Build detail page logic

async function loadBuildDetail() {
  const root = document.getElementById('buildDetailRoot');

  const [buildRes, analysisRes] = await Promise.allSettled([
    fetch(`/api/builds/${BUILD_ID}`).then(r => r.json()),
    fetch(`/api/analysis/${BUILD_ID}`).then(r => r.ok ? r.json() : null),
  ]);

  const build    = buildRes.status === 'fulfilled' ? buildRes.value : null;
  const analysis = analysisRes.status === 'fulfilled' ? analysisRes.value : null;

  if (!build || build.detail) {
    root.innerHTML = '<div class="alert alert-danger">Build not found.</div>';
    return;
  }

  root.innerHTML = `
    <!-- Header -->
    <div class="d-flex align-items-center gap-3 mb-4 flex-wrap">
      <a href="/" class="btn btn-sm btn-outline-secondary"><i class="bi bi-arrow-left me-1"></i>Back</a>
      <h4 class="mb-0">${build.job_type} — Build #${build.build_number}</h4>
      ${statusBadge(build.status)}
      <button class="btn btn-sm btn-primary ms-auto" id="analyseBtn" onclick="triggerAnalysis()">
        <i class="bi bi-cpu me-1"></i>Run Analysis
      </button>
    </div>

    <div class="row g-3">
      <!-- Build metadata -->
      <div class="col-md-5">
        <div class="card border-0 shadow-sm mb-3">
          <div class="card-header bg-transparent fw-semibold">Build Info</div>
          <div class="card-body">
            ${metaRow('Filename', `<code>${build.filename}</code>`)}
            ${metaRow('Triggered By', build.triggered_by || '—')}
            ${metaRow('Upstream Job', build.upstream_job || '—')}
            ${metaRow('Git Branch', build.git_branch || '—')}
            ${metaRow('Git Commit', build.git_commit ? `<code class="small">${build.git_commit.slice(0,10)}</code>` : '—')}
            ${metaRow('Commit Message', build.git_commit_message ? `<em class="small">${esc(build.git_commit_message)}</em>` : '—')}
            ${metaRow('Cucumber Tags', build.cucumber_tags ? `<code>${build.cucumber_tags}</code>` : '—')}
            ${metaRow('Finished At', build.finished_at || '—')}
            ${metaRow('Duration', fmtDuration(build.duration_seconds))}
            ${metaRow('Log Lines', build.log_line_count)}
          </div>
        </div>

        <!-- Test results -->
        <div class="card border-0 shadow-sm mb-3">
          <div class="card-header bg-transparent fw-semibold">Test Results</div>
          <div class="card-body">
            <div class="row text-center g-2">
              ${statCell('Run',     build.tests_run,     'primary')}
              ${statCell('Failures',build.test_failures, 'danger')}
              ${statCell('Errors',  build.test_errors,   'warning')}
              ${statCell('Skipped', build.test_skipped,  'secondary')}
            </div>
          </div>
        </div>

        <!-- Extracted errors -->
        ${build.errors?.length ? `
        <div class="card border-0 shadow-sm">
          <div class="card-header bg-transparent fw-semibold">Extracted Errors</div>
          <div class="card-body p-2">
            ${build.errors.map(e => `
              <div class="d-flex flex-column gap-1 p-2 mb-1 rounded bg-light">
                <div class="d-flex gap-2 align-items-center">
                  <span class="badge bg-secondary small">${e.category}</span>
                  <span class="small">${esc(e.message)}</span>
                </div>
                ${e.detail ? `<div class="evidence-item">${esc(e.detail)}</div>` : ''}
              </div>
            `).join('')}
          </div>
        </div>` : ''}
      </div>

      <!-- Analysis panel -->
      <div class="col-md-7">
        <div id="analysisPanel">
          ${analysis ? renderAnalysis(analysis) : renderNoAnalysis()}
        </div>
      </div>
    </div>
  `;
}

function renderAnalysis(a) {
  const recs  = a.recommendations || [];
  const evid  = a.evidence || [];
  const cats  = a.all_categories || [];
  const sev   = a.severity || 'MEDIUM';
  return `
    <div class="card border-0 shadow-sm analysis-card ${sev} mb-3">
      <div class="card-header bg-transparent d-flex align-items-center gap-2">
        <span class="fw-semibold">Root Cause Analysis</span>
        ${severityBadge(sev)}
        <span class="badge bg-light text-dark border ms-auto">Confidence: ${a.confidence || '—'}</span>
        ${a.recurring_risk === 'YES' ? '<span class="badge bg-danger">Recurring risk</span>' : ''}
      </div>
      <div class="card-body">
        <h6 class="text-danger mb-1"><i class="bi bi-exclamation-triangle me-1"></i>Root Cause</h6>
        <p class="mb-3">${esc(a.root_cause || '—')}</p>

        <h6 class="mb-1"><i class="bi bi-file-text me-1"></i>Explanation</h6>
        <p class="text-muted small mb-3">${esc(a.explanation || '—')}</p>

        ${evid.length ? `
        <h6 class="mb-1"><i class="bi bi-code-slash me-1"></i>Evidence</h6>
        <div class="mb-3">
          ${evid.map(e => `<div class="evidence-item">${esc(e)}</div>`).join('')}
        </div>` : ''}

        ${recs.length ? `
        <h6 class="mb-1"><i class="bi bi-tools me-1"></i>Recommendations</h6>
        <div>
          ${recs.map((r, i) => `
            <div class="recommendation-item">
              <span class="badge bg-primary me-2">${i + 1}</span>${esc(r)}
            </div>`).join('')}
        </div>` : ''}

        ${cats.length > 1 ? `
        <div class="mt-3 d-flex gap-2 flex-wrap">
          <small class="text-muted">All error categories:</small>
          ${cats.map(c => `<span class="badge bg-secondary">${c}</span>`).join('')}
        </div>` : ''}
      </div>
      <div class="card-footer text-muted small">
        Analysed at ${a.analysed_at || '—'} · ${a.agent_used ? 'Claude AI' : 'Rule-based'}
      </div>
    </div>`;
}

function renderNoAnalysis() {
  return `
    <div class="card border-0 shadow-sm text-center p-5">
      <i class="bi bi-cpu fs-1 text-muted mb-3"></i>
      <p class="text-muted">No analysis yet for this build.</p>
      <button class="btn btn-primary" onclick="triggerAnalysis()">
        <i class="bi bi-play me-1"></i>Run Root Cause Analysis
      </button>
    </div>`;
}

async function triggerAnalysis() {
  const btn = document.getElementById('analyseBtn');
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Analysing…'; }
  try {
    const r = await fetch(`/api/analysis/${BUILD_ID}/sync`, { method: 'POST' });
    const data = await r.json();
    document.getElementById('analysisPanel').innerHTML = renderAnalysis(data);
  } catch(e) {
    alert('Analysis failed: ' + e);
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = '<i class="bi bi-cpu me-1"></i>Run Analysis'; }
  }
}

function metaRow(label, value) {
  return `<div class="d-flex justify-content-between border-bottom py-1">
    <span class="text-muted small">${label}</span>
    <span class="small text-end">${value}</span>
  </div>`;
}

function statCell(label, value, color) {
  return `<div class="col-3">
    <div class="border rounded p-2">
      <div class="fs-4 fw-bold text-${color}">${value ?? 0}</div>
      <div class="small text-muted">${label}</div>
    </div>
  </div>`;
}

function esc(str) {
  if (!str) return '';
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

loadBuildDetail();
