
// DAILY_LIMIT is provided by inline configuration
let activeLogFilterBot = 'all';
let activeLogFilterSearch = 'all';
let allLogs = [];

// ── Toast Notifications ──────────────────────────────────────────────
function showToast(message) {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.textContent = message;
    container.appendChild(toast);
    
    setTimeout(() => { toast.classList.add('show'); }, 50);
    
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => { toast.remove(); }, 300);
    }, 3500);
}

// ── Tab Switching ────────────────────────────────────────────────────
function switchTab(tabId) {
    // Hide all panels
    document.querySelectorAll('.tab-panel').forEach(panel => {
        panel.classList.remove('active');
    });
    // Remove active class from buttons
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    
    // Show current panel & activate current tab button
    document.getElementById('tab-' + tabId).classList.add('active');
    document.getElementById('btn-tab-' + tabId).classList.add('active');
    
    if (tabId === 'analytics') {
        refreshAnalytics();
    }
}

function switchSettingsTab(tabId) {
    document.querySelectorAll('#tab-settings .settings-content').forEach(c => c.classList.remove('active'));
    document.querySelectorAll('#tab-settings .settings-tab').forEach(t => t.classList.remove('active'));
    
    document.getElementById(tabId).classList.add('active');
    document.getElementById('btn-' + tabId).classList.add('active');
}

// ── SSE Log Processing ───────────────────────────────────────────────
const evtSrc = new EventSource('/stream');

evtSrc.onmessage = e => {
    if (!e.data || e.data.trim() === "") return;
    try {
        const payload = JSON.parse(e.data);
        if (!payload.channel) payload.channel = 'bot';
        allLogs.push(payload);
        
        if (allLogs.length > 1000) {
            allLogs.shift();
        }
        renderLogs();
    } catch(err) {
        const textPayload = {type: "info", message: e.data, time: new Date().toLocaleTimeString(), channel: 'bot'};
        allLogs.push(textPayload);
        renderLogs();
    }
};

function renderLogs() {
    const consoleBoxBot = document.getElementById('console-bot');
    const consoleBoxSearch = document.getElementById('console-search');
    
    const filteredBot = allLogs.filter(log => log.channel === 'bot' && (activeLogFilterBot === 'all' || log.type === activeLogFilterBot));
    const filteredSearch = allLogs.filter(log => log.channel === 'search' && (activeLogFilterSearch === 'all' || log.type === activeLogFilterSearch));
    
    renderToBox(consoleBoxBot, filteredBot);
    renderToBox(consoleBoxSearch, filteredSearch);
}

function renderToBox(box, logs) {
    if (!box) return;
    box.innerHTML = '';
    
    if (logs.length === 0) {
        box.innerHTML = '<div class="log-line"><span class="log-time">-</span><span class="log-text" style="color:var(--text-muted)">No filtered action logs available.</span></div>';
        return;
    }
    
    logs.forEach(log => {
        const line = document.createElement('div');
        line.className = 'log-line';
        
        const timeSpan = document.createElement('span');
        timeSpan.className = 'log-time';
        timeSpan.textContent = log.time || new Date().toLocaleTimeString();
        
        const textSpan = document.createElement('span');
        textSpan.className = `log-text log-${log.type}`;
        textSpan.textContent = log.message;
        
        line.appendChild(timeSpan);
        line.appendChild(textSpan);
        box.appendChild(line);
    });
    box.scrollTop = box.scrollHeight;
}

function setFilterBot(filterType, element) {
    element.parentElement.querySelectorAll('.log-tab').forEach(tab => {
        tab.classList.remove('active', 'active-all', 'active-success', 'active-warn', 'active-error');
    });
    if (filterType === 'all') element.classList.add('active-all');
    else if (filterType === 'success') element.classList.add('active-success');
    else if (filterType === 'warn') element.classList.add('active-warn');
    else if (filterType === 'error') element.classList.add('active-error');
    
    activeLogFilterBot = filterType;
    renderLogs();
}

function setFilterSearch(filterType, element) {
    element.parentElement.querySelectorAll('.log-tab').forEach(tab => {
        tab.classList.remove('active', 'active-all', 'active-success', 'active-warn', 'active-error');
    });
    if (filterType === 'all') element.classList.add('active-all');
    else if (filterType === 'success') element.classList.add('active-success');
    else if (filterType === 'warn') element.classList.add('active-warn');
    else if (filterType === 'error') element.classList.add('active-error');
    
    activeLogFilterSearch = filterType;
    renderLogs();
}

function clearLogsBot() {
    allLogs = allLogs.filter(log => log.channel !== 'bot');
    renderLogs();
    showToast("Bot logs cleared.");
}

function clearLogsSearch() {
    allLogs = allLogs.filter(log => log.channel !== 'search');
    renderLogs();
    showToast("Search logs cleared.");
}

// ── Pin Feature Helpers ──────────────────────────────────────────────
function getPinnedUrls() {
    try {
        return JSON.parse(localStorage.getItem('pinned_jobs') || '[]');
    } catch(e) {
        return [];
    }
}

function togglePinJob(urlDecoded) {
    const url = decodeURIComponent(urlDecoded);
    let pinned = getPinnedUrls();
    if (pinned.includes(url)) {
        pinned = pinned.filter(u => u !== url);
        showToast("📌 Job unpinned");
    } else {
        pinned.push(url);
        showToast("📌 Job pinned to top");
    }
    localStorage.setItem('pinned_jobs', JSON.stringify(pinned));
    
    // Refresh both tables to update sorting and icons
    refreshTable();
    refreshTargetedResults();
}

// ── Poll Stats, History & Q&As ───────────────────────────────────────
async function refreshStats() {
    const res = await fetch('/api/stats');
    const d = await res.json();
    
    // Stats elements
    document.getElementById('cnt-applied').textContent = d.applied;
    document.getElementById('cnt-skipped').textContent = d.skipped;
    document.getElementById('cnt-manual').textContent = d.manual;
    document.getElementById('cnt-total').textContent = d.total;
    
    // Terminal badge updates
    document.getElementById('term-status').textContent = d.running ? 'RUNNING' : 'IDLE';
    document.getElementById('term-applied').textContent = d.applied;
    document.getElementById('term-skipped').textContent = d.skipped;
    
    // Auto-detect bot finished and re-enable buttons
    if (!d.running && _botRunning) {
        _botRunning = false;
        document.querySelectorAll('.mock-btn').forEach(b => {
            b.disabled = false;
            b.style.opacity = '1';
            b.style.cursor = 'pointer';
        });
        showToast("✅ Bot has finished running.");
    }
    
    // Refresh targeted search results if any are loaded
    await refreshTargetedResults();
}

async function refreshTargetedResults() {
    try {
        const res = await fetch('/api/targeted_results');
        const jobs = await res.json();
        const panel = document.getElementById('targeted-results-panel');
        const tb = document.getElementById('targeted-results-tbody');
        if (!panel || !tb) return;

        if (!jobs || !jobs.length) {
            panel.style.display = 'none';
            return;
        }

        panel.style.display = 'block';
        tb.innerHTML = '';

        // Update header badges
        const badge = document.getElementById('targeted-count-badge');
        if (badge) badge.textContent = jobs.length + ' jobs';
        const highMatch = jobs.filter(j => j.score >= 70).length;
        const hm = document.getElementById('targeted-high-match');
        if (hm) hm.textContent = highMatch > 0 ? `✅ ${highMatch} high-match (70%+)` : '';

        // Sort pinned jobs to the top
        const pinnedUrls = getPinnedUrls();
        const sortedJobs = [...jobs].sort((a, b) => {
            const aPinned = pinnedUrls.includes(a.url);
            const bPinned = pinnedUrls.includes(b.url);
            if (aPinned && !bPinned) return -1;
            if (!aPinned && bPinned) return 1;
            return 0;
        });

        sortedJobs.forEach(job => {
            const tr = document.createElement('tr');
            const isPinned = pinnedUrls.includes(job.url);
            if (isPinned) {
                tr.className = 'pinned-row';
            }

            let scoreColor = '#ff4444';
            if (job.score >= 70) scoreColor = '#22c55e';
            else if (job.score >= 55) scoreColor = '#f59e0b';
            else if (job.score >= 30) scoreColor = '#fb923c';

            // Decision badge styling
            const decisionColors = { auto: '#22c55e', review: '#f59e0b', skip: '#6b7280' };
            const decisionBg = { auto: 'rgba(34,197,94,0.12)', review: 'rgba(245,158,11,0.12)', skip: 'rgba(107,114,128,0.1)' };
            const dc = decisionColors[job.decision] || '#6b7280';
            const db = decisionBg[job.decision] || 'rgba(107,114,128,0.1)';
            const decisionLabel = { auto: '⚡ Auto', review: '👁 Review', skip: '⏭ Skip' }[job.decision] || job.decision;

            const postedText = job.posted ? job.posted.replace('Posted ', '') : '—';
            const reasonEsc = (job.reason || '').replace(/'/g, "\\'").replace(/"/g, '&quot;').substring(0, 120);

            tr.innerHTML = `
                <td><strong style="color:var(--accent2); font-size:11px;">${job.portal}</strong></td>
                <td><strong>${job.company}</strong></td>
                <td title="${reasonEsc}" style="cursor:help;">${job.title}</td>
                <td style="font-size:11px; color:var(--text-dim);">${job.location}</td>
                <td style="font-size:11px; color:var(--text-dim);">${postedText}</td>
                <td title="${reasonEsc}">
                  <span style="color:${scoreColor}; font-weight:700; font-size:13px; cursor:help;">${job.score}%</span>
                </td>
                <td>
                  <span style="color:${dc}; background:${db}; border:1px solid ${dc}33; padding:2px 8px; border-radius:10px; font-size:10px; font-weight:600; white-space:nowrap;">
                    ${decisionLabel}
                  </span>
                </td>
                <td>
                    <div style="display:flex; gap:5px; flex-wrap:wrap; align-items:center;">
                        <button onclick="togglePinJob('${encodeURIComponent(job.url)}')" class="pin-btn ${isPinned ? 'pinned' : ''}" title="${isPinned ? 'Unpin Job' : 'Pin Job'}" style="opacity:${isPinned ? '1' : '0.25'}">📌</button>
                        <a href="${job.url}" target="_blank" class="mock-btn mock-btn-outline" style="padding:3px 8px; font-size:10px; text-decoration:none; display:inline-block; margin:0;">🔗 Open</a>
                        <button class="mock-btn" onclick="assistApply('${encodeURIComponent(job.url)}', '${encodeURIComponent(job.company)}', '${encodeURIComponent(job.title)}')" style="padding:3px 8px; font-size:10px; margin:0; background:rgba(0,150,255,0.12); color:#33adff; border-color:rgba(0,150,255,0.3);">🧑‍💻 Assist</button>
                        <button class="mock-btn" onclick="autoApplySingle('${encodeURIComponent(job.url)}', '${encodeURIComponent(job.company)}', '${encodeURIComponent(job.title)}', '${encodeURIComponent(job.portal)}')" style="padding:3px 8px; font-size:10px; margin:0; background:rgba(0,102,34,0.8); color:#fff; border-color:#00802b;">🚀 Auto</button>
                    </div>
                </td>
            `;
            tb.appendChild(tr);
        });
    } catch (e) {
        console.error("Error refreshing targeted results:", e);
    }
}

async function refreshRecruiterLeads() {
    /* ISSUE13-FIX: New function to load and display recruiter leads from /api/recruiter_leads */
    try {
        const res = await fetch('/api/recruiter_leads');
        const data = await res.json();
        const panel = document.getElementById('recruiter-leads-panel');
        const tb = document.getElementById('recruiter-leads-tbody');
        if (!panel || !tb) return;

        const leads = data.leads || [];
        if (!leads.length) {
            panel.style.display = 'none';
            return;
        }

        panel.style.display = 'block';
        const badge = document.getElementById('leads-count-badge');
        if (badge) badge.textContent = leads.length + ' forms';

        tb.innerHTML = '';
        leads.forEach(lead => {
            const tr = document.createElement('tr');
            const typeColor = lead.type === 'Google Form' ? '#4285f4' : lead.type === 'MS Form' ? '#0078d4' : '#a78bfa';
            tr.innerHTML = `
                <td style="font-size:11px; color:var(--text-dim); white-space:nowrap;">${lead.date.substring(0,16) || '—'}</td>
                <td><strong>${lead.company || '—'}</strong></td>
                <td style="font-size:11px; color:var(--text-dim); max-width:200px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${lead.snippet}">${lead.snippet}</td>
                <td><span style="color:${typeColor}; font-size:11px; font-weight:600;">${lead.type}</span></td>
                <td>
                  <div style="display:flex; gap:5px; align-items:center;">
                    <a href="${lead.link}" target="_blank" class="mock-btn" style="padding:3px 8px; font-size:10px; text-decoration:none; display:inline-block; margin:0; background:rgba(167,139,250,0.15); color:#a78bfa; border:1px solid rgba(167,139,250,0.3);">
                      📝 Open
                    </a>
                    <button class="mock-btn" onclick="assistApply('${encodeURIComponent(lead.link)}', '${encodeURIComponent(lead.company)}', 'Recruiter Form')" style="padding:3px 8px; font-size:10px; margin:0; background:rgba(0,150,255,0.12); color:#33adff; border-color:rgba(0,150,255,0.3);">
                      🧑‍💻 Assist
                    </button>
                  </div>
                </td>
            `;
            tb.appendChild(tr);
        });
    } catch (e) {
        console.error("Error loading recruiter leads:", e);
    }
}

async function assistApply(urlEnc, compEnc, titleEnc) {
    const url = decodeURIComponent(urlEnc);
    const company = decodeURIComponent(compEnc);
    const role = decodeURIComponent(titleEnc);

    showToast("Launching browser for interactive manual assist session...");
    const res = await fetch('/api/assist_apply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, company, role })
    });
    const d = await res.json();
    if (d.ok) {
        showToast("✅ Browser opened! Complete the form manually — it will stay open.");
    } else {
        showToast("Error: " + (d.error || "Failed to start assist session"));
    }
}

async function autoApplySingle(urlEnc, compEnc, titleEnc, portalEnc) {
    const url = decodeURIComponent(urlEnc);
    const company = decodeURIComponent(compEnc);
    const role = decodeURIComponent(titleEnc);
    const portal = decodeURIComponent(portalEnc);

    showToast(`⏳ Starting auto-apply to ${company}...`);
    const res = await fetch('/api/approve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, company, role, portal })
    });
    const d = await res.json();
    if (d.ok) {
        showToast("✅ Auto-application scheduled in background!");
    } else {
        showToast("Error: " + (d.error || "Failed to schedule application"));
    }
}


async function refreshTable() {
    const res = await fetch('/api/applications');
    const rows = await res.json();
    const tb = document.getElementById('app-tbody');
    tb.innerHTML = '';
    
    if (!rows.length) {
        tb.innerHTML = '<tr><td colspan="8" style="text-align:center; color:var(--text-muted)">No logged application runs found.</td></tr>';
        return;
    }
    
    // Sort rows: Pinned first, then newest first (the default array order is newest first)
    const pinnedUrls = getPinnedUrls();
    const sortedRows = [...rows].sort((a, b) => {
        const aPinned = pinnedUrls.includes(a.URL);
        const bPinned = pinnedUrls.includes(b.URL);
        if (aPinned && !bPinned) return -1;
        if (!aPinned && bPinned) return 1;
        return 0;
    });

    sortedRows.slice(0, 100).forEach(row => {
        const tr = document.createElement('tr');
        const isPinned = pinnedUrls.includes(row.URL);
        if (isPinned) {
            tr.className = 'pinned-row';
        }
        
        const statusClass = row.Status === 'Applied' ? 'applied' : (row.Status === 'Skipped' ? 'skipped' : 'manual');
        
        const pinHtml = `<button onclick="togglePinJob('${encodeURIComponent(row.URL)}')" class="pin-btn ${isPinned ? 'pinned' : ''}" style="background:none; border:none; cursor:pointer; font-size:12px; margin-right:4px; padding:0; opacity:${isPinned ? '1' : '0.25'}" title="${isPinned ? 'Unpin' : 'Pin'}">📌</button>`;
        
        const companyDisplay = row.URL
            ? `${pinHtml}<a href="${row.URL}" target="_blank" style="color:#fff; text-decoration:none; font-weight:600;" title="Open job listing">${row.Company} ↗</a>`
            : `${pinHtml}<span style="font-weight:600; color:#fff">${row.Company}</span>`;
            
        const postedDisplay = row['Posted Date'] || '';
        
        tr.innerHTML = `
            <td style="font-size:0.75rem; color:var(--text-muted)">${row.Date}</td>
            <td>${companyDisplay}</td>
            <td style="color:var(--accent2); max-width:220px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${row.Role}">${row.Role}</td>
            <td><span style="font-family:var(--mono); font-size:10px; background:rgba(79,140,255,0.1); padding:2px 7px; border-radius:4px; color:var(--accent2)">${row.Portal}</span></td>
            <td><span class="pill ${statusClass}">${row.Status}</span></td>
            <td style="font-family:var(--mono); font-size:12px;">${row['Match %']}</td>
            <td style="font-size:11px; color:var(--text-muted);">${postedDisplay}</td>
            <td style="color:var(--text-muted); font-size:0.75rem; max-width:160px;">${row['Skip Reason'] || (row['Matched Skills'] ? '✓ ' + row['Matched Skills'].split(',').slice(0,3).join(', ') : '')}</td>
        `;
        tb.appendChild(tr);
    });

    // Also populate Kanban Board
    populateKanban(rows);
}

function populateKanban(rows) {
    const colDraft = document.getElementById('kb-col-draft');
    const colApplied = document.getElementById('kb-col-applied');
    const colMatch = document.getElementById('kb-col-match');
    const colInterview = document.getElementById('kb-col-interview');
    const colClosed = document.getElementById('kb-col-closed');

    colDraft.innerHTML = '';
    colApplied.innerHTML = '';
    colMatch.innerHTML = '';
    colInterview.innerHTML = '';
    colClosed.innerHTML = '';

    let draftCount = 0;
    let appliedCount = 0;
    let matchCount = 0;
    let interviewCount = 0;
    let closedCount = 0;

    rows.forEach(row => {
        const card = document.createElement('div');
        card.className = 'kan-card';
        const postedStr = row['Posted Date'] ? `<div style="font-size:10px; color:var(--text-muted); margin-top:3px;">📅 ${row['Posted Date']}</div>` : '';
        const portalBadge = row.Portal ? `<span style="font-size:9px; font-family:var(--mono); background:rgba(79,140,255,0.12); color:var(--accent2); padding:1px 5px; border-radius:3px;">${row.Portal}</span>` : '';
        const matchBadge = row['Match %'] ? `<span style="font-size:9px; font-family:var(--mono); color:var(--accent);">${row['Match %']}</span>` : '';
        card.innerHTML = `
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:3px;">
              ${portalBadge} ${matchBadge}
            </div>
            <div class="kan-co">${row.Company || 'Unknown'}</div>
            <div class="kan-role">${row.Role || 'Unknown'}</div>
            ${postedStr}
        `;
        if (row.URL) {
            card.style.cursor = 'pointer';
            card.onclick = () => window.open(row.URL, '_blank');
            card.title = 'Click to open job listing';
        }

        const status = (row.Status || '').trim().toLowerCase();
        const scoreVal = parseInt(row['Match %']) || 0;

        if (status === 'manual needed') {
            colDraft.appendChild(card);
            draftCount++;
        } else if (status === 'applied') {
            if (scoreVal >= 75) {
                colMatch.appendChild(card);
                matchCount++;
            } else {
                colApplied.appendChild(card);
                appliedCount++;
            }
        } else if (status === 'skipped') {
            colClosed.appendChild(card);
            closedCount++;
        } else if (status.includes('interview')) {
            colInterview.appendChild(card);
            interviewCount++;
        } else {
            colClosed.appendChild(card);
            closedCount++;
        }
    });

    document.getElementById('kb-count-draft').textContent = draftCount;
    document.getElementById('kb-count-applied').textContent = appliedCount;
    document.getElementById('kb-count-match').textContent = matchCount;
    document.getElementById('kb-count-interview').textContent = interviewCount;
    document.getElementById('kb-count-closed').textContent = closedCount;
    document.getElementById('kanban-total-count').textContent = rows.length + " active applications tracked";
}

// Global states for QA sub-tabs and filters
let _activeQASubTab = 'pending';
let _activeQACategory = 'all';
let _allQADataCache = [];

function switchQASubTab(subtab) {
    _activeQASubTab = subtab;
    
    // Toggle active classes on buttons
    document.getElementById('btn-qa-sub-pending').classList.toggle('active', subtab === 'pending');
    document.getElementById('btn-qa-sub-all').classList.toggle('active', subtab === 'all');
    document.getElementById('btn-qa-sub-jobs').classList.toggle('active', subtab === 'jobs');
    
    // Toggle explanation visibility
    document.getElementById('qa-pane-pending-info').style.display = subtab === 'pending' ? 'block' : 'none';
    document.getElementById('qa-pane-all-info').style.display = subtab === 'all' ? 'block' : 'none';
    document.getElementById('qa-pane-jobs-info').style.display = subtab === 'jobs' ? 'block' : 'none';
    
    // Toggle container lists
    document.getElementById('qa-list').style.display = subtab === 'pending' ? 'block' : 'none';
    document.getElementById('qa-all-list').style.display = subtab === 'all' ? 'block' : 'none';
    document.getElementById('jobs-review-list').style.display = subtab === 'jobs' ? 'block' : 'none';
    
    refreshQA();
}

function filterQACategory(cat) {
    _activeQACategory = cat;
    
    // Toggle active category classes
    const cats = ['all', 'exp', 'comp', 'time', 'legal', 'other'];
    cats.forEach(c => {
        const btn = document.getElementById(`btn-qa-cat-${c}`);
        if (btn) {
            if (c === cat) {
                btn.classList.add('active');
                btn.classList.remove('mock-btn-outline');
            } else {
                btn.classList.remove('active');
                btn.classList.add('mock-btn-outline');
            }
        }
    });
    
    renderQALibraryList();
}

function getQuestionCategory(q) {
    const text = q.toLowerCase();
    if (text.includes("experience") || text.includes("year") || text.includes("how long") || text.includes("how many") || text.includes("skill") || text.includes("tool") || text.includes("technology")) {
        return "exp";
    }
    if (text.includes("notice") || text.includes("start date") || text.includes("available to start") || text.includes("joining") || text.includes("timeline")) {
        return "time";
    }
    if (text.includes("salary") || text.includes("ctc") || text.includes("compensation") || text.includes("lpa") || text.includes("package") || text.includes("expected") || text.includes("current")) {
        return "comp";
    }
    if (text.includes("sponsor") || text.includes("work permit") || text.includes("visa") || text.includes("authorized") || text.includes("eligible") || text.includes("right to work") || text.includes("legal")) {
        return "legal";
    }
    return "other";
}

function renderQALibraryList() {
    const allList = document.getElementById('qa-all-list');
    if (!_allQADataCache || !_allQADataCache.length) {
        allList.innerHTML = '<p style="color:var(--text-muted); text-align:center; padding:1.5rem">No custom questions in memory yet.</p>';
        return;
    }
    
    // Filter by category
    let filtered = _allQADataCache;
    if (_activeQACategory !== 'all') {
        filtered = _allQADataCache.filter(item => getQuestionCategory(item.question) === _activeQACategory);
    }
    
    if (!filtered.length) {
        allList.innerHTML = `<p style="color:var(--text-muted); text-align:center; padding:1.5rem">No questions match this category.</p>`;
        return;
    }
    
    allList.innerHTML = '';
    filtered.forEach((item, index) => {
        const d = document.createElement('div');
        d.className = 'qa-item';
        d.style.marginBottom = '10px';
        
        const cat = getQuestionCategory(item.question);
        let catBadge = '';
        if (cat === 'exp') catBadge = '<span style="font-size:10px; background:#0052cc; color:#fff; padding:2px 6px; border-radius:4px; margin-right:6px;">💡 Experience</span>';
        else if (cat === 'comp') catBadge = '<span style="font-size:10px; background:#006622; color:#fff; padding:2px 6px; border-radius:4px; margin-right:6px;">💰 Salary</span>';
        else if (cat === 'time') catBadge = '<span style="font-size:10px; background:#e65c00; color:#fff; padding:2px 6px; border-radius:4px; margin-right:6px;">⏳ Notice</span>';
        else if (cat === 'legal') catBadge = '<span style="font-size:10px; background:#800080; color:#fff; padding:2px 6px; border-radius:4px; margin-right:6px;">🛡️ Visa</span>';
        else catBadge = '<span style="font-size:10px; background:#555; color:#fff; padding:2px 6px; border-radius:4px; margin-right:6px;">📂 Other</span>';
        
        const portalText = item.portal ? `<small style="color:var(--text-muted); margin-left:5px;">(${item.portal})</small>` : '';
        const encodedQ = encodeURIComponent(item.question);
        const inputId = `qa-lib-${index}`;
        const modeSelectId = `qa-mode-${index}`;
        
        d.innerHTML = `
            <div class="qa-question" style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:5px;">
                <div>${catBadge} <strong>${item.question}</strong> ${portalText}</div>
                <div style="font-size:10px; color:var(--text-muted); font-family:var(--mono);">Encountered: ${item.count}x</div>
            </div>
            <div style="display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-top:5px;">
                <div style="display:flex; align-items:center; gap:5px;">
                    <label style="font-size:11px; color:var(--text-dim);">Action:</label>
                    <select id="${modeSelectId}" class="input-control" style="padding:2px 6px; font-size:11px; margin:0; width:120px; height:auto; background:var(--surface2);">
                        <option value="auto" ${item.mode === 'auto' ? 'selected' : ''}>🤖 Auto-Answer</option>
                        <option value="manual" ${item.mode === 'manual' ? 'selected' : ''}>👤 Manual Entry</option>
                    </select>
                </div>
                <div style="flex:1; display:flex; gap:5px; align-items:center; min-width:200px;">
                    <input class="qa-input" id="${inputId}" placeholder="Stored answer..." value="${item.answer}" style="margin:0; padding:2px 8px; font-size:12px;">
                </div>
                <div style="display:flex; gap:5px;">
                    <button class="mock-btn" style="padding:2px 10px; font-size:11px; margin:0;" onclick="saveQAAll('${encodedQ}', '${inputId}', '${modeSelectId}')">Save</button>
                    <button class="mock-btn mock-btn-red" style="padding:2px 10px; font-size:11px; margin:0;" onclick="deleteQA('${encodedQ}')">Delete</button>
                </div>
            </div>
        `;
        allList.appendChild(d);
    });
}

async function aiAutoResolveQA() {
    const btn = document.getElementById('ai-auto-resolve-btn');
    if (btn) {
        btn.disabled = true;
        btn.textContent = '⏳ Resolving...';
    }
    try {
        const res = await fetch('/api/qa/auto_resolve', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        const data = await res.json();
        if (data.ok) {
            showToast(`✨ AI auto-resolved ${data.count} questions!`);
            await refreshQA();
        } else {
            showToast(`⚠️ Auto-resolve error: ${data.error}`);
        }
    } catch (e) {
        showToast("Auto-resolve failed.");
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = '✨ AI Auto-Resolve All';
        }
    }
}

async function refreshQA() {
    // 1. Fetch unanswered questions (pending tab count)
    const resPending = await fetch('/api/qa');
    const pendingItems = await resPending.json();

    // Fetch jobs review queue
    const resJobs = await fetch('/api/review_queue');
    const reviewJobs = await resJobs.json();
    
    // Update action badges
    const totalReviewActions = pendingItems.length + reviewJobs.length;
    document.getElementById('qa-tab-count').textContent = totalReviewActions;
    document.getElementById('qa-sub-pending-count').textContent = pendingItems.length;
    document.getElementById('term-qa').textContent = pendingItems.length;
    document.getElementById('jobs-review-count').textContent = reviewJobs.length;

    if (_activeQASubTab === 'pending') {
        const list = document.getElementById('qa-list');
        if (!pendingItems.length) {
            list.innerHTML = '<p style="color:var(--accent); text-align:center; padding:1.5rem">All form questions resolved! Bot is ready. 🎉</p>';
            return;
        }
        
        list.innerHTML = '';
        pendingItems.forEach((item, index) => {
            const d = document.createElement('div');
            d.className = 'qa-item';
            
            const encodedQ = encodeURIComponent(item.question);
            const inputId = `qa-pen-${index}`;
            
            d.innerHTML = `
                <div class="qa-question">${item.question} <small style="color:var(--text-muted)">(${item.portal})</small></div>
                <div class="qa-form-row">
                    <input class="qa-input" id="${inputId}" placeholder="Type your answer...">
                    <button class="mock-btn" style="padding:4px 12px;" onclick="saveQA('${encodedQ}', '${inputId}')">Save</button>
                </div>
            `;
            list.appendChild(d);
        });
    } else if (_activeQASubTab === 'jobs') {
        renderJobsReviewList(reviewJobs);
    } else {
        // 2. Fetch all questions for library tab
        const resAll = await fetch('/api/qa/all');
        _allQADataCache = await resAll.json();
        renderQALibraryList();
    }
}

async function saveQA(qEnc, inputId) {
    const answer = document.getElementById(inputId).value.trim();
    if (!answer) return alert('Please type an answer first.');
    
    await fetch('/api/qa/answer', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: decodeURIComponent(qEnc), answer })
    });
    
    showToast("Answer saved successfully!");
    refreshQA();
}

async function saveQAAll(qEnc, inputId, modeSelectId) {
    const question = decodeURIComponent(qEnc);
    const answer = document.getElementById(inputId).value.trim();
    const mode = document.getElementById(modeSelectId).value;
    
    await fetch('/api/qa/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, answer, mode })
    });
    
    showToast("Question configurations updated!");
    refreshQA();
}

async function deleteQA(qEnc) {
    if (!confirm("Are you sure you want to delete this question from memory?")) return;
    const question = decodeURIComponent(qEnc);
    
    await fetch('/api/qa/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question })
    });
    
    showToast("Question deleted from memory.");
    refreshQA();
}

function renderJobsReviewList(reviewJobs) {
    const list = document.getElementById('jobs-review-sublist');
    if (!reviewJobs || !reviewJobs.length) {
        list.innerHTML = '<p style="color:var(--accent); text-align:center; padding:1.5rem">No jobs pending review. You are all set! 🎉</p>';
        return;
    }
    
    list.innerHTML = '';
    reviewJobs.forEach((job) => {
        const d = document.createElement('div');
        d.className = 'qa-item';
        d.style.marginBottom = '12px';
        
        let scoreColor = 'var(--text-muted)';
        if (job.Score >= 70) scoreColor = '#00ff66';
        else if (job.Score >= 50) scoreColor = '#ffcc00';
        else scoreColor = '#ff3333';
        
        let missingHtml = '';
        if (job.Missing && job.Missing.length > 0) {
            missingHtml = `
                <div style="font-size:11px; margin-top:5px; color:var(--text-dim);">
                    <strong>Missing Skills:</strong> 
                    ${job.Missing.map(s => `<span style="background:rgba(255,50,50,0.15); color:#ff6666; padding:1px 5px; border-radius:3px; font-size:10px; margin-right:4px;">${s}</span>`).join('')}
                </div>
            `;
        }
        
        let matchedHtml = '';
        if (job.Matched && job.Matched.length > 0) {
            matchedHtml = `
                <div style="font-size:11px; margin-top:5px; color:var(--text-dim);">
                    <strong>Matched Skills:</strong> 
                    ${job.Matched.map(s => `<span style="background:rgba(50,255,50,0.15); color:#66ff66; padding:1px 5px; border-radius:3px; font-size:10px; margin-right:4px;">${s}</span>`).join('')}
                </div>
            `;
        }
        
        d.innerHTML = `
            <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:10px;">
                <div style="flex:1;">
                    <div style="font-size:14px; font-weight:bold; color:var(--text);">
                        ${job.Role} <span style="font-weight:normal; font-size:12px; color:var(--text-muted);">at</span> ${job.Company}
                    </div>
                    <div style="font-size:11px; color:var(--text-muted); margin-top:2px;">
                        Portal: <strong>${job.Portal}</strong> | Match Score: <strong style="color:${scoreColor}; font-size:12px;">${job.Score}%</strong>
                    </div>
                    <div style="font-size:11px; color:var(--text-dim); margin-top:3px; font-style:italic;">
                        Reason: ${job.Reason || 'Held in review queue'}
                    </div>
                    ${matchedHtml}
                    ${missingHtml}
                    <div style="font-size:11px; color:var(--text-muted); margin-top:5px;">
                        URL: <a href="${job.URL}" target="_blank" style="color:var(--primary); text-decoration:none;">Open Posting 🔗</a>
                    </div>
                </div>
                <div style="display:flex; gap:8px; align-self:center;">
                    <button class="mock-btn" style="padding:6px 14px; background:#006622; color:#fff; border-color:#00802b; font-size:12px;" onclick="approveJob('${encodeURIComponent(job.URL)}')">🚀 Approve</button>
                    <button class="mock-btn mock-btn-red" style="padding:6px 14px; font-size:12px;" onclick="rejectJob('${encodeURIComponent(job.URL)}')">❌ Reject</button>
                </div>
            </div>
        `;
        list.appendChild(d);
    });
}

async function approveJob(urlEnc) {
    const url = decodeURIComponent(urlEnc);
    showToast("Processing approval and starting auto-application...");
    const res = await fetch('/api/approve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url })
    });
    const data = await res.json();
    if (data.ok) {
        showToast("Job approved. Running background automation!");
        refreshQA();
    } else {
        showToast("Error: " + (data.error || "Failed to approve"));
    }
}

async function rejectJob(urlEnc) {
    const url = decodeURIComponent(urlEnc);
    if (!confirm("Are you sure you want to skip/reject this job?")) return;
    const res = await fetch('/api/reject', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url })
    });
    const data = await res.json();
    if (data.ok) {
        showToast("Job rejected and skipped.");
        refreshQA();
    } else {
        showToast("Error: " + (data.error || "Failed to reject"));
    }
}

async function bulkApprove(useMinScore) {
    let payload = {};
    if (useMinScore) {
        const val = parseInt(document.getElementById('bulk-min-score').value);
        if (!val || val < 50 || val > 100) {
            showToast("⚠️ Please enter a valid minimum score between 50 and 100.");
            return;
        }
        payload.min_score = val;
    }
    
    const countText = useMinScore ? `>= ${payload.min_score}%` : "all";
    if (!confirm(`Are you sure you want to approve ${countText} pending jobs and trigger background applications?`)) return;
    
    showToast("Processing bulk approval and starting background automation...");
    const res = await fetch('/api/review/bulk_approve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (data.ok) {
        showToast(`🚀 Successfully approved ${data.count} jobs. Automation started!`);
        refreshQA();
    } else {
        showToast("Error: " + (data.error || "Failed to bulk approve"));
    }
}

async function bulkReject() {
    if (!confirm("Are you sure you want to skip/reject ALL pending jobs currently in the review queue?")) return;
    
    showToast("Processing bulk reject...");
    const res = await fetch('/api/review/bulk_reject', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
    });
    const data = await res.json();
    if (data.ok) {
        showToast(`❌ Successfully skipped/rejected ${data.count} jobs.`);
        refreshQA();
    } else {
        showToast("Error: " + (data.error || "Failed to bulk reject"));
    }
}

// ── Bot Controls ─────────────────────────────────────────────────────
let _botRunning = false;

async function runBot(target) {
    if (_botRunning) {
        showToast("Bot is already running! Please wait...");
        return;
    }
    
    const headless = document.getElementById('headless-checkbox').checked;
    const maxApps = parseInt(document.getElementById('max-apps-input').value) || 15;
    
    const res = await fetch('/api/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target, headless, max_applications: maxApps })
    });
    
    const d = await res.json();
    if (d.error) {
        showToast(`Error: ${d.error}`);
    } else {
        _botRunning = true;
        showToast(`🚀 Bot started! Launching Chrome browser... this takes ~20 seconds.`);
        // Disable run buttons, enable stop
        document.querySelectorAll('.mock-btn:not(.mock-btn-red)').forEach(b => {
            if (b.onclick && b.onclick.toString().includes('runBot')) {
                b.disabled = true;
                b.style.opacity = '0.5';
                b.style.cursor = 'not-allowed';
            }
        });
    }
    
    refreshStats();
}

async function runTargetedSearch() {
    if (_botRunning) {
        showToast("Bot is already running! Please wait...");
        return;
    }
    const company  = document.getElementById('target-company-input').value.trim();
    const skills   = document.getElementById('target-skills-input').value.trim();
    const location = document.getElementById('target-location-input').value.trim()
                  || [...(_selectedCities || [])].join(', ');

    if (!skills) {
        showToast("⚠️ Please enter Skills / Role for Targeted Search!");
        return;
    }

    const headless = document.getElementById('headless-checkbox').checked;
    const maxApps  = parseInt(document.getElementById('max-apps-input').value) || 15;

    const btn = document.getElementById('targeted-search-btn');
    if (btn) { btn.disabled = true; btn.textContent = '⏳ Searching...'; }

    const res = await fetch('/api/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            target: 'targeted',
            headless,
            max_applications: maxApps,
            company,
            skills,
            location: location || 'Pune'
        })
    });

    const d = await res.json();
    if (btn) { btn.disabled = false; btn.textContent = '🚀 Search Jobs (4 Portals)'; }

    if (d.error) {
        showToast(`Error: ${d.error}`);
        return;
    }

    _botRunning = true;
    showToast(`🚀 Targeted Search started${company ? ' for ' + company : ''}!`);
    pollTargetedResults(0);
    refreshStats();
}

async function runRecruiterScraper() {
    if (_botRunning) {
        showToast("Bot is already running! Please wait...");
        return;
    }
    const company  = document.getElementById('target-company-input').value.trim();
    const skills   = document.getElementById('target-skills-input').value.trim() || 'Data Engineer';
    const location = document.getElementById('target-location-input').value.trim()
                  || [...(_selectedCities || [])].join(', ') || 'Pune';

    const btn = document.getElementById('recruiter-btn');
    if (btn) { btn.disabled = true; btn.textContent = '⏳ Scanning...'; }

    const res = await fetch('/api/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            target: 'recruiter_posts',
            company,
            skills,
            location
        })
    });

    const d = await res.json();
    if (btn) { btn.disabled = false; btn.textContent = '📬 Find Recruiter Forms'; }

    if (d.error) {
        showToast(`Error: ${d.error}`);
        return;
    }

    _botRunning = true;
    showToast('🚀 Recruiter scanner started!');
    setTimeout(() => { refreshRecruiterLeads(); refreshStats(); }, 8000);
}

function pollTargetedResults(attempt) {
    if (attempt > 36) return;  // ~3 min limit
    fetch('/api/targeted_results')
        .then(r => r.json())
        .then(jobs => {
            if (jobs && jobs.length > 0) {
                refreshTargetedResults();
            } else {
                setTimeout(() => pollTargetedResults(attempt + 1), 5000);
            }
        })
        .catch(() => setTimeout(() => pollTargetedResults(attempt + 1), 6000));
}


async function stopBot() {
    await fetch('/api/stop', { method: 'POST' });
    showToast("⏹ Stop request sent. Bot will finish current action and halt.");
    _botRunning = false;
    // Re-enable run buttons
    document.querySelectorAll('.mock-btn').forEach(b => {
        b.disabled = false;
        b.style.opacity = '1';
        b.style.cursor = 'pointer';
    });
    refreshStats();
}

function exportCSV() {
    window.location.href = '/api/export-csv';
}

let techExpData = {};

function renderTechExp() {
    const container = document.getElementById('tech-exp-container');
    if (!container) return;
    container.innerHTML = '';
    
    // Sort keys alphabetically for clean display
    const entries = Object.entries(techExpData).sort((a, b) => a[0].localeCompare(b[0]));
    
    entries.forEach(([tech, years]) => {
        const div = document.createElement('div');
        div.className = 'form-group';
        div.style = 'background:rgba(255,255,255,0.03); border: 1px solid var(--border); padding: 10px; border-radius: 8px; position: relative;';
        div.innerHTML = `
            <label style="text-transform:none; font-weight:700; font-size:12px; color:var(--text);">${tech.toUpperCase()}</label>
            <input type="number" class="tech-exp-input input-control" data-tech="${tech}" value="${years}" style="padding: 4px 8px; font-size: 13px; margin-top: 4px; width:100%; height:32px;" />
            <span onclick="removeTechExp('${tech}')" style="position: absolute; top: 8px; right: 10px; cursor: pointer; color: var(--accent3); font-size: 14px; font-weight:bold;">&#x2715;</span>
        `;
        container.appendChild(div);
    });
}

function removeTechExp(tech) {
    delete techExpData[tech];
    renderTechExp();
}

function addNewTechExp() {
    const nameInp = document.getElementById('new-tech-name');
    const yearsInp = document.getElementById('new-tech-years');
    if (!nameInp || !yearsInp) return;
    const name = nameInp.value.trim().toLowerCase();
    const years = yearsInp.value.trim();

    if (name && years !== '') {
        techExpData[name] = years;
        renderTechExp();
        nameInp.value = '';
        yearsInp.value = '';
    } else {
        showToast("Please specify tech name and years");
    }
}

// ── Profile Settings Configurations ──────────────────────────────────
async function loadProfileSettings() {
    try {
        const res = await fetch('/api/profile');
        const data = await res.json();
        
        const profileKeys = ["first_name", "last_name", "email", "phone", "city", "linkedin_email", "linkedin_password", "naukri_email", "naukri_password", "total_experience_years", "current_ctc", "expected_ctc", "notice_period", "resume_path", "corp_email", "corp_password"];
        profileKeys.forEach(k => {
            const el = document.getElementById(`cfg-${k}`);
            if (el) el.value = data.profile[k] || '';
        });
        
        // Populate tab-resume path input preview & cover letter preview
        const pathEl = document.getElementById('cfg-resume_path-tab');
        if (pathEl) pathEl.value = data.profile['resume_path'] || '';
        const coverEl = document.getElementById('cfg-cover_letter-preview');
        if (coverEl) coverEl.textContent = data.cover_letter || '[No cover letter configured]';

        document.getElementById('cfg-my_skills').value = data.skills.join(', ');
        document.getElementById('cfg-search_keywords').value = data.keywords.join(', ');
        document.getElementById('cfg-search_locations').value = data.locations.join(', ');
        document.getElementById('cfg-target_companies').value = data.companies.join(', ');
        
        document.getElementById('cfg-min_match_score').value = data.min_match_score;
        document.getElementById('cfg-daily_limit').value = data.daily_limit;
        document.getElementById('cfg-cover_letter').value = data.cover_letter;
        
        const geminiInp = document.getElementById('cfg-gemini_api_key');
        if (geminiInp) geminiInp.value = data.gemini_api_key || '';
        const autoTh = document.getElementById('cfg-auto_threshold');
        if (autoTh) autoTh.value = data.auto_threshold || 75;
        const revTh = document.getElementById('cfg-review_threshold');
        if (revTh) revTh.value = data.review_threshold || 55;
        const imapH = document.getElementById('cfg-imap_host');
        if (imapH) imapH.value = data.imap_host || 'imap.gmail.com';
        const imapE = document.getElementById('cfg-imap_email');
        if (imapE) imapE.value = data.imap_email || '';
        const imapP = document.getElementById('cfg-imap_password');
        if (imapP) imapP.value = data.imap_password || '';

        const tgToken = document.getElementById('cfg-telegram_bot_token');
        if (tgToken) tgToken.value = data.telegram_bot_token || '';
        const tgChat = document.getElementById('cfg-telegram_chat_id');
        if (tgChat) tgChat.value = data.telegram_chat_id || '';
        
        const channels = data.notification_channels || ["email"];
        const notifEmail = document.getElementById('cfg-notif-email');
        if (notifEmail) notifEmail.checked = channels.includes("email");
        const notifTelegram = document.getElementById('cfg-notif-telegram');
        if (notifTelegram) notifTelegram.checked = channels.includes("telegram");

        // Load tech experience
        techExpData = data.tech_experience || {};
        renderTechExp();

        // Render company credentials table
        renderCompanyCredentials(data.company_credentials || {});
    } catch (err) {
        showToast("Failed to load settings: " + err);
    }
}

async function saveProfileSettings() {
    const profile = {};
    const profileKeys = ["first_name", "last_name", "email", "phone", "city", "linkedin_email", "linkedin_password", "naukri_email", "naukri_password", "total_experience_years", "current_ctc", "expected_ctc", "notice_period", "resume_path", "corp_email", "corp_password"];
    profileKeys.forEach(k => {
        profile[k] = document.getElementById(`cfg-${k}`).value.trim();
    });
    
    const splitCsv = val => val.split(',').map(s => s.trim()).filter(s => s.length > 0);
    
    // Collect tech experience values
    const techExp = {};
    document.querySelectorAll('.tech-exp-input').forEach(inp => {
        techExp[inp.dataset.tech.toLowerCase()] = inp.value;
    });

    const geminiInp = document.getElementById('cfg-gemini_api_key');
    const geminiKeyVal = geminiInp ? geminiInp.value.trim() : '';

    const payload = {
        profile,
        skills: splitCsv(document.getElementById('cfg-my_skills').value),
        keywords: splitCsv(document.getElementById('cfg-search_keywords').value),
        locations: splitCsv(document.getElementById('cfg-search_locations').value),
        companies: splitCsv(document.getElementById('cfg-target_companies').value),
        min_match_score: parseInt(document.getElementById('cfg-min_match_score').value) || 30,
        daily_limit: parseInt(document.getElementById('cfg-daily_limit').value) || 50,
        auto_threshold: parseInt(document.getElementById('cfg-auto_threshold').value) || 75,
        review_threshold: parseInt(document.getElementById('cfg-review_threshold').value) || 55,
        cover_letter: document.getElementById('cfg-cover_letter').value,
        tech_experience: techExp,
        gemini_api_key: geminiKeyVal,
        imap_host: document.getElementById('cfg-imap_host').value.trim(),
        imap_email: document.getElementById('cfg-imap_email').value.trim(),
        imap_password: document.getElementById('cfg-imap_password').value.trim(),
        telegram_bot_token: document.getElementById('cfg-telegram_bot_token').value.trim(),
        telegram_chat_id: document.getElementById('cfg-telegram_chat_id').value.trim(),
        notification_channels: (() => {
            const list = [];
            const emailBox = document.getElementById('cfg-notif-email');
            const tgBox = document.getElementById('cfg-notif-telegram');
            if (emailBox && emailBox.checked) list.push("email");
            if (tgBox && tgBox.checked) list.push("telegram");
            return list;
        })()
    };
    
    try {
        const res = await fetch('/api/profile', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const d = await res.json();
        if (d.ok) {
            showToast("Configurations saved successfully!");
            loadProfileSettings();
        } else {
            showToast("Failed to save configs: " + d.error);
        }
    } catch (err) {
        showToast("Error saving configs: " + err);
    }
}

function renderCompanyCredentials(creds) {
    const tbody = document.getElementById("company-creds-tbody");
    if (!tbody) return;
    tbody.innerHTML = "";
    const entries = Object.entries(creds);
    if (entries.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; color:var(--text-muted); padding:1rem;">No custom company credentials added yet.</td></tr>';
        return;
    }
    entries.forEach(([comp, val]) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
            <td style="font-weight:600; color:var(--accent);">${comp}</td>
            <td>${val.email}</td>
            <td>••••••••</td>
            <td>
                <button class="mock-btn mock-btn-red" style="padding:2px 8px; font-size:11px; margin:0;" onclick="deleteCompanyCredential('${comp}')">Delete</button>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

async function addCompanyCredential() {
    const company = document.getElementById("add-company-name").value.trim();
    const email = document.getElementById("add-company-email").value.trim();
    const password = document.getElementById("add-company-password").value.trim();
    
    if (!company || !email || !password) {
        return alert("Please fill out Company Name, Email/Username, and Password.");
    }
    
    try {
        const res = await fetch("/api/company-credentials", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ company, email, password })
        });
        const d = await res.json();
        if (d.ok) {
            showToast(`Credentials added for ${company}! Retrying skipped jobs...`);
            document.getElementById("add-company-name").value = "";
            document.getElementById("add-company-email").value = "";
            document.getElementById("add-company-password").value = "";
            loadProfileSettings();
            checkNotifications();
            
            // Switch to feed tab to watch console output live
            switchTab('feed');
        } else {
            showToast("Failed to add credentials: " + d.error);
        }
    } catch (err) {
        showToast("Error adding credentials: " + err);
    }
}

async function deleteCompanyCredential(company) {
    if (!confirm(`Are you sure you want to delete credentials for ${company}?`)) return;
    
    try {
        const res = await fetch("/api/company-credentials/delete", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ company })
        });
        const d = await res.json();
        if (d.ok) {
            showToast("Credentials deleted successfully.");
            loadProfileSettings();
            checkNotifications();
        } else {
            showToast("Failed to delete credentials: " + d.error);
        }
    } catch (err) {
        showToast("Error deleting credentials: " + err);
    }
}

function openCompanyCredTab() {
    switchTab('settings');
    switchSettingsTab('settings-company-creds');
}

function dismissNotification() {
    document.getElementById('notification-banner').style.display = 'none';
}

async function checkNotifications() {
    try {
        const res = await fetch('/api/notifications');
        const data = await res.json();
        const settingsBadge = document.getElementById('settings-alert-badge');
        const companyCredsBadge = document.getElementById('company-creds-alert-badge');
        
        if (data.notifications && data.notifications.length > 0) {
            if (settingsBadge) settingsBadge.style.display = 'inline-block';
            if (companyCredsBadge) companyCredsBadge.style.display = 'inline-block';
        } else {
            if (settingsBadge) settingsBadge.style.display = 'none';
            if (companyCredsBadge) companyCredsBadge.style.display = 'none';
        }
    } catch (err) {
        console.error("Failed to check notifications:", err);
    }
}

let funnelChartInstance = null;

function renderFunnelChart(data) {
    const ctx = document.getElementById('funnelChart').getContext('2d');
    
    if (funnelChartInstance) {
        funnelChartInstance.destroy();
    }
    
    const labels = ['Jobs Seen', 'AI Filter Passed', 'Applied', 'Viewed', 'Interview Invited', 'Offers'];
    const values = [
        data.Scanned || 0,
        data.AI_Passed || 0,
        data.Applied || 0,
        data.Viewed || 0,
        data.Interview || 0,
        data.Offer || 0
    ];
    
    funnelChartInstance = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Applications',
                data: values,
                backgroundColor: [
                    'rgba(142, 142, 147, 0.45)', // Jobs Seen
                    'rgba(79, 140, 255, 0.6)',   // AI Filter Passed
                    'rgba(255, 179, 0, 0.65)',   // Applied
                    'rgba(59, 130, 246, 0.65)',  // Viewed
                    'rgba(139, 92, 246, 0.65)',  // Interview Invited
                    'rgba(74, 222, 128, 0.75)'   // Offers
                ],
                borderColor: [
                    'rgba(142, 142, 147, 1)',
                    'rgba(79, 140, 255, 1)',
                    'rgba(255, 179, 0, 1)',
                    'rgba(59, 130, 246, 1)',
                    'rgba(139, 92, 246, 1)',
                    'rgba(74, 222, 128, 1)'
                ],
                borderWidth: 1,
                borderRadius: 4,
                barPercentage: 0.6
            }]
        },
        options: {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: false
                },
                tooltip: {
                    backgroundColor: 'rgba(13, 15, 20, 0.95)',
                    titleColor: '#fff',
                    bodyColor: '#ccc',
                    borderColor: 'rgba(255, 255, 255, 0.1)',
                    borderWidth: 1
                }
            },
            scales: {
                x: {
                    grid: {
                        color: 'rgba(255, 255, 255, 0.05)'
                    },
                    ticks: {
                        color: '#8e8e93',
                        stepSize: 1,
                        beginAtZero: true
                    }
                },
                y: {
                    grid: {
                        display: false
                    },
                    ticks: {
                        color: '#fff',
                        font: {
                            family: 'Inter',
                            size: 12,
                            weight: '600'
                        }
                    }
                }
            }
        }
    });
}

async function refreshAnalytics() {
    try {
        const res = await fetch('/api/analytics');
        const data = await res.json();
        
        document.getElementById('metrics-scanned').textContent = data.Scanned || 0;
        document.getElementById('metrics-applied').textContent = data.Applied || 0;
        document.getElementById('metrics-interviews').textContent = data.Interview || 0;
        document.getElementById('metrics-offers').textContent = data.Offer || 0;
        
        const scanned = data.Scanned || 0;
        const applied = data.Applied || 0;
        const interviews = data.Interview || 0;
        const offers = data.Offer || 0;
        
        const appRate = scanned > 0 ? ((applied / scanned) * 100).toFixed(1) : '0.0';
        const callbackRate = applied > 0 ? ((interviews / applied) * 100).toFixed(1) : '0.0';
        const offerRate = interviews > 0 ? ((offers / interviews) * 100).toFixed(1) : '0.0';
        
        document.getElementById('metrics-app-rate').textContent = `${appRate}%`;
        document.getElementById('metrics-callback-rate').textContent = `${callbackRate}%`;
        document.getElementById('metrics-offer-rate').textContent = `${offerRate}%`;
        
        renderFunnelChart(data);
        
        const appsRes = await fetch('/api/applications');
        const rows = await appsRes.json();
        const tbody = document.getElementById('analytics-tbody');
        tbody.innerHTML = '';
        
        if (rows.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; color:var(--text-muted); padding:12px;">No job applications tracked yet.</td></tr>';
            return;
        }
        
        rows.forEach(row => {
            const tr = document.createElement('tr');
            tr.style.borderBottom = '1px solid var(--border)';
            
            const companyDisplay = row.URL
                ? `<a href="${row.URL}" target="_blank" style="color:#fff; text-decoration:none; font-weight:600;" title="Open job listing">${row.Company} ↗</a>`
                : `<span style="font-weight:600; color:#fff">${row.Company}</span>`;
            
            const selectHtml = `
                <select class="input-control" style="padding:2px 6px; font-size:11px; margin:0; width:130px; height:auto; background:var(--surface2);" onchange="updateRowStatus('${row.URL || ''}', this.value, '${row.Company.replace(/'/g, "\\'")}')">
                    <option value="Applied" ${row.Status === 'Applied' ? 'selected' : ''}>Applied</option>
                    <option value="Viewed" ${row.Status === 'Viewed' ? 'selected' : ''}>Viewed</option>
                    <option value="Shortlisted" ${row.Status === 'Shortlisted' ? 'selected' : ''}>Shortlisted</option>
                    <option value="Interview" ${row.Status === 'Interview' ? 'selected' : ''}>Interview</option>
                    <option value="Offer" ${row.Status === 'Offer' ? 'selected' : ''}>Offer</option>
                    <option value="Rejected" ${row.Status === 'Rejected' ? 'selected' : ''}>Rejected</option>
                    <option value="Ghosted" ${row.Status === 'Ghosted' ? 'selected' : ''}>Ghosted</option>
                    <option value="Skipped" ${row.Status === 'Skipped' ? 'selected' : ''}>Skipped</option>
                    <option value="Manual Needed" ${row.Status === 'Manual Needed' ? 'selected' : ''}>Manual Needed</option>
                </select>
            `;
            
            const escapedCompany = (row.Company || '').replace(/'/g, "\\'").replace(/"/g, '&quot;');
            const escapedRole = (row.Role || '').replace(/'/g, "\\'").replace(/"/g, '&quot;');
            tr.innerHTML = `
                <td style="padding:8px; font-weight:600;">${companyDisplay}</td>
                <td style="padding:8px; color:var(--accent2); max-width:200px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${row.Role || ''}</td>
                <td style="padding:8px;"><span style="font-family:var(--mono); font-size:10px; background:rgba(79,140,255,0.1); padding:2px 7px; border-radius:4px; color:var(--accent2)">${row.Portal || ''}</span></td>
                <td style="padding:8px; font-family:var(--mono); font-size:12px;">${row['Match %'] || ''}</td>
                <td style="padding:8px; font-size:0.75rem; color:var(--text-muted);">${row.Date || ''}</td>
                <td style="padding:8px;">${selectHtml}</td>
                <td style="padding:8px;">
                    <button class="btn btn-primary" style="padding:3px 8px; font-size:10px; border-radius:4px;" onclick="draftOutreach('${escapedCompany}', '${escapedRole}', '${row.URL || ''}')">✨ Draft</button>
                </td>
            `;
            tbody.appendChild(tr);
        });
        
    } catch (err) {
        console.error("Failed to load analytics:", err);
    }
}

async function updateRowStatus(url, newStatus, companyName) {
    if (!url) {
        showToast("Cannot update application status without a URL");
        return;
    }
    try {
        const res = await fetch('/api/applications/status', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: url, new_status: newStatus })
        });
        const data = await res.json();
        if (data.success) {
            showToast(`Status updated to ${newStatus} for ${companyName}`);
            refreshAnalytics();
            refreshTable();
        } else {
            showToast(`Failed to update status: ${data.error}`);
        }
    } catch (err) {
        showToast(`Error updating status: ${err}`);
    }
}

// ── Initial Boot ─────────────────────────────────────────────────────
loadProfileSettings();
refreshStats();
refreshTable();
refreshQA();
checkNotifications();
refreshAnalytics();

setInterval(() => {
    refreshStats();
    refreshTable();
    refreshQA();
    checkNotifications();
    refreshAnalytics();
}, 5000);

// ── Phase 4: Resume & Cover Lab ───────────────────────────────────────

function loadMasterResume() {
    fetch('/api/master_resume')
        .then(r => r.json())
        .then(data => {
            document.getElementById('master-resume-text').value = data.text || '';
            const st = document.getElementById('master-resume-status');
            if (data.exists) {
                const wc = (data.text || '').trim().split(/\s+/).length;
                st.style.color = '#22c55e';
                st.textContent = '\u2705 Loaded (' + wc + ' words)';
            } else {
                st.style.color = 'var(--text-muted)';
                st.textContent = 'No master resume saved yet \u2014 paste yours above and click Save';
            }
        })
        .catch(e => {
            document.getElementById('master-resume-status').textContent = '\u26a0\ufe0f Load error: ' + e;
        });
}

function saveMasterResume() {
    const text = document.getElementById('master-resume-text').value.trim();
    if (!text) { alert('Please paste your resume text first.'); return; }
    const st = document.getElementById('master-resume-status');
    st.style.color = '#a78bfa';
    st.textContent = 'Saving...';
    fetch('/api/master_resume', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({text: text})
    })
    .then(r => r.json())
    .then(data => {
        if (data.ok) {
            st.style.color = '#22c55e';
            st.textContent = '\u2705 ' + data.message;
        } else {
            st.style.color = '#f87171';
            st.textContent = '\u274c ' + (data.error || 'Save failed');
        }
    })
    .catch(e => {
        st.style.color = '#f87171';
        st.textContent = '\u26a0\ufe0f Save error: ' + e;
    });
}

function fetchJdFromUrl() {
    const url = document.getElementById('tailor-job-url').value.trim();
    if (!url) { alert('Please enter a job URL first.'); return; }
    showTailorSpinner('Fetching JD from URL...');
    const jdArea = document.getElementById('tailor-jd-text');
    jdArea.value = 'Fetching...';
    fetch('/api/tailor', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({job_url: url})
    })
    .then(r => r.json())
    .then(data => {
        hideTailorSpinner();
        if (data.error) {
            jdArea.value = '';
            showTailorError('Fetch failed: ' + data.error);
        } else {
            renderTailorResults(data);
        }
    })
    .catch(e => {
        hideTailorSpinner();
        jdArea.value = '';
        showTailorError('Network error: ' + e);
    });
}

function tailorResume() {
    const jd  = document.getElementById('tailor-jd-text').value.trim();
    const url = document.getElementById('tailor-job-url').value.trim();
    if (!jd && !url) { alert('Paste a Job Description or enter a Job URL first.'); return; }
    hideTailorError();
    showTailorSpinner('Calling Gemini \u2014 tailoring resume...');
    document.getElementById('tailor-btn').disabled = true;
    const payload = {};
    if (jd)  payload.job_description = jd;
    if (url) payload.job_url = url;
    fetch('/api/tailor', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
    })
    .then(r => r.json())
    .then(data => {
        hideTailorSpinner();
        document.getElementById('tailor-btn').disabled = false;
        if (data.error) { showTailorError(data.error); }
        else { renderTailorResults(data); }
    })
    .catch(e => {
        hideTailorSpinner();
        document.getElementById('tailor-btn').disabled = false;
        showTailorError('Network error: ' + e);
    });
}

function renderTailorResults(data) {
    renderKeywordAnalysis(data.keyword_matches || [], data.keyword_gaps || [], data.match_score || 0);
    document.getElementById('tailored-summary').textContent = data.tailored_summary || '';
    document.getElementById('tailored-skills').textContent  = data.tailored_skills  || '';
    const bulletsEl = document.getElementById('tailored-bullets');
    bulletsEl.innerHTML = '';
    (data.tailored_bullets || []).forEach(function(b) {
        const line = document.createElement('div');
        line.style.cssText = 'padding:3px 0; border-bottom:1px solid rgba(255,255,255,0.05); display:flex; gap:8px;';
        line.innerHTML = '<span style="color:#a78bfa;flex-shrink:0;">\u25b8</span><span>' + escapeHtml(b) + '</span>';
        bulletsEl.appendChild(line);
    });
    const compiled = [
        'PROFESSIONAL SUMMARY', data.tailored_summary || '', '',
        'SKILLS', data.tailored_skills || '', '',
        'EXPERIENCE HIGHLIGHTS',
        ...(data.tailored_bullets || []).map(function(b) { return '\u2022 ' + b; })
    ].join('\n');
    document.getElementById('tailored-resume-compiled').value = compiled;
    document.getElementById('cover-letter-text').value = data.cover_letter || '';
    document.getElementById('keyword-analysis-row').style.display = 'block';
    document.getElementById('tailored-resume-row').style.display   = 'block';
    document.getElementById('cover-letter-row').style.display      = 'block';
}

function renderKeywordAnalysis(matches, gaps, score) {
    const scoreEl = document.getElementById('match-score-num');
    const ringEl  = document.getElementById('match-score-ring');
    scoreEl.textContent = score + '%';
    const color = score >= 70 ? '#22c55e' : score >= 50 ? '#f59e0b' : '#f87171';
    scoreEl.style.color = color;
    ringEl.style.borderColor = color;
    const matchChips = document.getElementById('keyword-matches-chips');
    matchChips.innerHTML = '';
    matches.forEach(function(kw) {
        const c = document.createElement('span');
        c.style.cssText = 'background:rgba(34,197,94,0.15);color:#22c55e;border:1px solid rgba(34,197,94,0.3);border-radius:12px;padding:2px 10px;font-size:11px;font-weight:600;';
        c.textContent = kw; matchChips.appendChild(c);
    });
    const gapChips = document.getElementById('keyword-gaps-chips');
    gapChips.innerHTML = '';
    gaps.forEach(function(kw) {
        const c = document.createElement('span');
        c.style.cssText = 'background:rgba(245,158,11,0.15);color:#f59e0b;border:1px solid rgba(245,158,11,0.3);border-radius:12px;padding:2px 10px;font-size:11px;font-weight:600;';
        c.textContent = kw; gapChips.appendChild(c);
    });
}

function copyTailoredResume() {
    const text = document.getElementById('tailored-resume-compiled').value;
    if (!text) { alert('No tailored resume to copy yet.'); return; }
    navigator.clipboard.writeText(text).then(function() { showCopyFlash('Tailored resume copied!'); });
}

function copyCoverLetter() {
    const text = document.getElementById('cover-letter-text').value;
    if (!text) { alert('No cover letter to copy yet.'); return; }
    navigator.clipboard.writeText(text).then(function() { showCopyFlash('Cover letter copied!'); });
}

function showCopyFlash(msg) {
    const el = document.createElement('div');
    el.textContent = msg;
    el.style.cssText = 'position:fixed;bottom:28px;left:50%;transform:translateX(-50%);background:#22c55e;color:#000;padding:10px 22px;border-radius:8px;font-size:13px;font-weight:700;z-index:9999;';
    document.body.appendChild(el);
    setTimeout(function() { el.remove(); }, 2200);
}

function showTailorSpinner(msg) {
    const sp = document.getElementById('tailor-spinner');
    sp.style.display = 'flex';
    document.getElementById('tailor-spinner-text').textContent = msg || 'Calling Gemini...';
}
function hideTailorSpinner() { document.getElementById('tailor-spinner').style.display = 'none'; }
function showTailorError(msg) {
    const el = document.getElementById('tailor-error');
    el.textContent = '\u274c ' + msg;
    el.style.display = 'block';
}
function hideTailorError() { document.getElementById('tailor-error').style.display = 'none'; }
function escapeHtml(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}


// ── Phase 6: Workday Auto-Register ───────────────────────────────────────────

let _wdPolling = null;

function wdAutoRegister() {
    const url  = document.getElementById('wd-portal-url').value.trim();
    const name = document.getElementById('wd-portal-name').value.trim();
    const email = document.getElementById('wd-email').value.trim();
    const pw   = document.getElementById('wd-password').value.trim();
    if (!url)  { alert('Please enter the Workday portal URL.'); return; }
    if (!name) { alert('Please enter a portal name (e.g. Accenture).'); return; }

    document.getElementById('wd-status-panel').style.display = 'block';
    document.getElementById('wd-register-btn').disabled = true;
    _wdSetPhase('launching', '#f59e0b');

    // Save credentials first if provided
    const savePayload = {portal_name: name, email: email || '', password: pw || ''};
    fetch('/api/workday/save_portal', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(savePayload)
    }).catch(() => {});

    fetch('/api/workday/register', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({portal_url: url, portal_name: name})
    })
    .then(r => r.json())
    .then(data => {
        if (data.error) {
            _wdSetPhase('error: ' + data.error, '#f87171');
            document.getElementById('wd-register-btn').disabled = false;
            return;
        }
        // Start polling status
        _wdPolling = setInterval(wdPollStatus, 2000);
    })
    .catch(e => {
        _wdSetPhase('Network error: ' + e, '#f87171');
        document.getElementById('wd-register-btn').disabled = false;
    });
}

function wdPollStatus() {
    fetch('/api/workday/status')
    .then(r => r.json())
    .then(data => {
        const phase = data.phase || 'unknown';
        const color = data.success ? '#22c55e' : data.error ? '#f87171' : '#f59e0b';
        _wdSetPhase(phase, color);

        // Update log
        const logBox = document.getElementById('wd-log-box');
        logBox.innerHTML = (data.log || []).map(l => '<div>' + escapeHtml(l) + '</div>').join('');
        logBox.scrollTop = logBox.scrollHeight;

        if (!data.running) {
            clearInterval(_wdPolling);
            _wdPolling = null;
            document.getElementById('wd-register-btn').disabled = false;
            if (data.success) {
                _wdSetPhase('✅ Done — credentials saved!', '#22c55e');
                setTimeout(wdLoadPortals, 1000);
            } else if (data.error) {
                _wdSetPhase('❌ ' + data.error, '#f87171');
            }
        }
    })
    .catch(() => {});
}

function _wdSetPhase(phase, color) {
    document.getElementById('wd-status-phase').textContent = phase;
    document.getElementById('wd-status-dot').style.background = color;
}

function wdSaveManual() {
    const name  = document.getElementById('wd-portal-name').value.trim();
    const email = document.getElementById('wd-email').value.trim();
    const pw    = document.getElementById('wd-password').value.trim();
    if (!name || !email) { alert('Portal name and email are required.'); return; }
    fetch('/api/workday/save_portal', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({portal_name: name, email: email, password: pw})
    })
    .then(r => r.json())
    .then(data => {
        if (data.ok) {
            showCopyFlash('Credentials saved for ' + name + '!');
            wdLoadPortals();
        } else {
            alert('Save failed: ' + (data.error || 'Unknown error'));
        }
    });
}

function wdLoadPortals() {
    fetch('/api/workday/saved_portals')
    .then(r => r.json())
    .then(data => {
        const list = document.getElementById('wd-portals-list');
        const portals = data.portals || [];
        if (!portals.length) {
            list.innerHTML = '<div style="color:var(--text-muted);font-size:12px;">No portals saved yet. Add one using the form.</div>';
            return;
        }
        list.innerHTML = portals.map(p => `
            <div style="background:var(--surface1); border:1px solid var(--border); border-radius:8px; padding:10px 14px; display:flex; align-items:center; justify-content:space-between;">
              <div>
                <div style="font-size:13px; font-weight:600; color:var(--text);">${escapeHtml(p.name)}</div>
                <div style="font-size:11px; color:var(--text-muted); margin-top:2px;">${escapeHtml(p.email)} &nbsp;&#8226;&nbsp; ${p.has_pass ? '<span style="color:#22c55e;">&#128274; Secured</span>' : '<span style="color:#f59e0b;">No password</span>'}</div>
              </div>
              <div style="display:flex; gap:6px;">
                <button class="action-btn" style="font-size:10px; padding:3px 8px;" onclick="wdPrefill('${escapeHtml(p.name)}','${escapeHtml(p.email)}')">&#9998; Edit</button>
              </div>
            </div>`).join('');
    })
    .catch(() => {});
}

function wdPrefill(name, email) {
    document.getElementById('wd-portal-name').value = name;
    document.getElementById('wd-email').value = email;
}

// Auto-load portals when Workday sub-tab is clicked
document.addEventListener('DOMContentLoaded', function() {
    const wdBtn = document.getElementById('btn-settings-workday');
    if (wdBtn) { wdBtn.addEventListener('click', function() { setTimeout(wdLoadPortals, 150); }); }
});


// ── City Chip Multi-Select ────────────────────────────────────────────────────
const _selectedCities = new Set(['Pune']);  // Pune selected by default

function toggleCity(city) {
    const key = city.toLowerCase().replace(/\s/g, '-');
    const chipId = 'city-chip-' + key;
    const chip = document.getElementById(chipId) ||
        document.getElementById('city-chip-' + city.toLowerCase().replace(/\s/g, ''));
    // Also try matching by button text
    if (_selectedCities.has(city)) {
        _selectedCities.delete(city);
        if (chip) chip.classList.remove('active');
    } else {
        _selectedCities.add(city);
        if (chip) chip.classList.add('active');
    }
    const locInput = document.getElementById('target-location-input');
    if (locInput) locInput.value = [..._selectedCities].join(', ');
}

// ── Skill Quick-Add ────────────────────────────────────────────────────────────
function addSkillChip(skill) {
    const el = document.getElementById('target-skills-input');
    if (!el) return;
    const current = el.value.trim();
    if (!current) { el.value = skill; return; }
    if (!current.toLowerCase().includes(skill.toLowerCase())) {
        el.value = current + ', ' + skill;
    }
}

// ── Company Autocomplete Dropdown ─────────────────────────────────────────────
const _knownCompanies = [
    'PwC','Accenture','Deloitte','TCS','Wipro','Infosys','Cognizant','Capgemini',
    'Microsoft','Google','Amazon','IBM','Cisco','Oracle','SAP','HCL','Tech Mahindra',
    'Mphasis','Hexaware','LTIMindtree','Persistent','Birlasoft','UST','NIIT Technologies'
];

function filterCompanyDropdown(val) {
    const drop = document.getElementById('company-dropdown');
    if (!drop) return;
    if (!val || val.length < 1) { drop.style.display = 'none'; return; }
    const filtered = _knownCompanies.filter(c => c.toLowerCase().includes(val.toLowerCase()));
    if (!filtered.length) { drop.style.display = 'none'; return; }
    drop.innerHTML = filtered.map(c =>
        `<div class="company-drop-item" onclick="selectCompany('${c}')">${c}</div>`
    ).join('');
    drop.style.display = 'block';
}

function selectCompany(name) {
    const inp = document.getElementById('target-company-input');
    if (inp) inp.value = name;
    hideCompanyDrop();
}

function showCompanyDrop() {
    const val = document.getElementById('target-company-input').value;
    if (val) filterCompanyDropdown(val);
}
function hideCompanyDrop() {
    const drop = document.getElementById('company-dropdown');
    if (drop) drop.style.display = 'none';
}
// Initialize search profiles and city chips on load
document.addEventListener('DOMContentLoaded', function() {
    // Set Pune as default active
    const puneChip = document.getElementById('city-chip-pune');
    if (puneChip) puneChip.classList.add('active');
    const locInput = document.getElementById('target-location-input');
    if (locInput) locInput.value = 'Pune';
    
    // Load search profiles dropdown
    loadSearchProfiles();
});

// ── Search Profiles ───────────────────────────────────────────────────────────
async function loadSearchProfiles() {
    try {
        const res = await fetch('/api/search_profiles');
        const profiles = await res.json();
        const select = document.getElementById('search-profile-select');
        if (!select) return;
        
        const currentSelected = select.value;
        select.innerHTML = '<option value="">-- Select Profile --</option>';
        for (const name in profiles) {
            const opt = document.createElement('option');
            opt.value = name;
            opt.textContent = name;
            select.appendChild(opt);
        }
        if (currentSelected && profiles[currentSelected]) {
            select.value = currentSelected;
        }
    } catch (e) {
        console.error("Error loading search profiles:", e);
    }
}

async function loadSearchProfile(name) {
    if (!name) {
        document.getElementById('target-company-input').value = '';
        document.getElementById('target-skills-input').value = '';
        _selectedCities.clear();
        _selectedCities.add('Pune');
        document.querySelectorAll('.city-chip').forEach(c => {
            if (c.id === 'city-chip-pune') c.classList.add('active');
            else c.classList.remove('active');
        });
        document.getElementById('target-location-input').value = 'Pune';
        return;
    }
    
    try {
        const res = await fetch('/api/search_profiles');
        const profiles = await res.json();
        const prof = profiles[name];
        if (!prof) return;
        
        document.getElementById('target-company-input').value = prof.company || '';
        document.getElementById('target-skills-input').value = prof.skills || '';
        
        _selectedCities.clear();
        const locations = prof.location ? prof.location.split(',').map(s => s.trim()) : [];
        locations.forEach(loc => _selectedCities.add(loc));
        
        document.querySelectorAll('.city-chip').forEach(chip => {
            const chipText = chip.textContent.replace(/^[\uD800-\uDBFF][\uDC00-\uDFFF]\s*/, '').trim();
            const match = [..._selectedCities].some(c => c.toLowerCase() === chipText.toLowerCase());
            if (match) chip.classList.add('active');
            else chip.classList.remove('active');
        });
        
        document.getElementById('target-location-input').value = [..._selectedCities].join(', ');
        showToast(`Loaded search profile: ${name}`);
    } catch (e) {
        showToast("Error loading search profile!");
    }
}

async function saveCurrentSearchProfile() {
    const name = prompt("Enter a name for this search profile:");
    if (!name || !name.trim()) return;
    
    const company = document.getElementById('target-company-input').value.trim();
    const skills = document.getElementById('target-skills-input').value.trim();
    const location = document.getElementById('target-location-input').value.trim();
    
    if (!skills) {
        showToast("⚠️ Skills / Role field is required to save a profile!");
        return;
    }
    
    try {
        const res = await fetch('/api/search_profiles', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                action: 'save',
                name: name.trim(),
                profile: { company, skills, location }
            })
        });
        const data = await res.json();
        if (data.ok) {
            showToast(`Profile "${name}" saved!`);
            await loadSearchProfiles();
            document.getElementById('search-profile-select').value = name.trim();
        } else {
            showToast(`Error: ${data.error}`);
        }
    } catch (e) {
        showToast("Failed to save profile.");
    }
}

async function deleteCurrentSearchProfile() {
    const select = document.getElementById('search-profile-select');
    const name = select.value;
    if (!name) {
        showToast("⚠️ Select a profile to delete first!");
        return;
    }
    
    if (!confirm(`Are you sure you want to delete profile "${name}"?`)) return;
    
    try {
        const res = await fetch('/api/search_profiles', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                action: 'delete',
                name: name
            })
        });
        const data = await res.json();
        if (data.ok) {
            showToast(`Profile "${name}" deleted.`);
            await loadSearchProfiles();
            loadSearchProfile('');
        } else {
            showToast(`Error: ${data.error}`);
        }
    } catch (e) {
        showToast("Failed to delete profile.");
    }
}

// ── Slide-Over Settings & Filter ─────────────────────────────────────────────
function toggleSettings(open) {
    const backdrop = document.getElementById('settings-backdrop');
    const slideover = document.getElementById('settings-slideover');
    if (!backdrop || !slideover) return;
    if (open) {
        backdrop.classList.add('active');
        slideover.classList.add('open');
        // Pre-load settings on open
        loadProfileSettings();
    } else {
        backdrop.classList.remove('active');
        slideover.classList.remove('open');
    }
}

function filterSettings(query) {
    const q = query.toLowerCase().trim();
    
    // Find all settings contents (e.g. personal grid, workday grid, etc.)
    const contentPanes = document.querySelectorAll('.settings-content');
    
    contentPanes.forEach(pane => {
        // Find input groups inside this pane
        const groups = pane.querySelectorAll('.input-group, .config-grid > div');
        let paneHasMatch = false;
        
        groups.forEach(group => {
            const label = group.querySelector('label');
            const labelText = label ? label.textContent.toLowerCase() : '';
            
            if (!q) {
                group.classList.remove('settings-section-hidden');
                if (label) label.classList.remove('settings-highlight');
                paneHasMatch = true;
                return;
            }
            
            if (labelText.includes(q)) {
                group.classList.remove('settings-section-hidden');
                if (label) label.classList.add('settings-highlight');
                paneHasMatch = true;
            } else {
                group.classList.add('settings-section-hidden');
                if (label) label.classList.remove('settings-highlight');
            }
        });
        
        // If a settings content pane is currently active, we want to see it.
        // We can also switch tabs dynamically if we type a keyword from another tab!
        if (q) {
            const tabId = pane.id;
            const btnId = 'btn-' + tabId;
            const btn = document.getElementById(btnId);
            if (paneHasMatch && btn) {
                // If it contains matches, make the tab button stand out!
                btn.style.borderColor = 'var(--accent)';
                btn.style.color = '#fff';
            } else if (btn) {
                btn.style.borderColor = '';
                btn.style.color = '';
            }
        } else {
            // Restore tab buttons style
            const tabId = pane.id;
            const btnId = 'btn-' + tabId;
            const btn = document.getElementById(btnId);
            if (btn) {
                btn.style.borderColor = '';
                btn.style.color = '';
            }
        }
    });
}


// ── Recruiter Outreach Draft Generator ─────────────────────────────────────────
function toggleOutreach(open) {
    const backdrop = document.getElementById('outreach-backdrop');
    const slideover = document.getElementById('outreach-slideover');
    if (!backdrop || !slideover) return;
    if (open) {
        backdrop.classList.add('active');
        slideover.classList.add('open');
    } else {
        backdrop.classList.remove('active');
        slideover.classList.remove('open');
    }
}

async function draftOutreach(company, role, url) {
    document.getElementById('outreach-subtitle').textContent = `${company} — ${role}`;
    document.getElementById('outreach-subject').value = '';
    document.getElementById('outreach-message').value = '';
    
    document.getElementById('outreach-loader').style.display = 'block';
    document.getElementById('outreach-content').style.display = 'none';
    
    toggleOutreach(true);
    
    try {
        const res = await fetch('/api/generate_outreach', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ company, role, snippet: url })
        });
        const data = await res.json();
        
        document.getElementById('outreach-loader').style.display = 'none';
        document.getElementById('outreach-content').style.display = 'flex';
        
        if (data.ok) {
            document.getElementById('outreach-subject').value = data.subject || '';
            document.getElementById('outreach-message').value = data.message || '';
        } else {
            showToast("Gemini Error: " + (data.error || "Failed to generate outreach"));
            toggleOutreach(false);
        }
    } catch (e) {
        document.getElementById('outreach-loader').style.display = 'none';
        showToast("Outreach generation request failed.");
        toggleOutreach(false);
    }
}

function copyOutreachText() {
    const msgEl = document.getElementById('outreach-message');
    if (!msgEl || !msgEl.value) {
        showToast("No outreach text to copy.");
        return;
    }
    msgEl.select();
    navigator.clipboard.writeText(msgEl.value)
        .then(() => showToast("Outreach message copied to clipboard!"))
        .catch(() => showToast("Failed to copy text."));
}


// ── AI Resume Upload & Parser Event Handlers ────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    const dropzoneInput = document.getElementById('resume-parse-input');
    const container = document.getElementById('resume-parse-container');
    const loader = document.getElementById('resume-parse-loader');
    
    if (dropzoneInput && container && loader) {
        // Drag over effects
        ['dragenter', 'dragover'].forEach(eventName => {
            container.addEventListener(eventName, (e) => {
                e.preventDefault();
                e.stopPropagation();
                container.style.borderColor = 'var(--accent2)';
                container.style.background = 'rgba(255,255,255,0.08)';
            }, false);
        });
        
        ['dragleave', 'drop'].forEach(eventName => {
            container.addEventListener(eventName, (e) => {
                e.preventDefault();
                e.stopPropagation();
                container.style.borderColor = 'rgba(255,255,255,0.15)';
                container.style.background = 'rgba(255,255,255,0.03)';
            }, false);
        });
        
        // Handle dropped file or selected file
        dropzoneInput.addEventListener('change', async (e) => {
            const files = e.target.files;
            if (!files || files.length === 0) return;
            
            const file = files[0];
            if (!file.name.endsWith('.pdf')) {
                showToast("Only PDF files are supported");
                return;
            }
            
            // Show loader
            loader.style.display = 'flex';
            
            const formData = new FormData();
            formData.append('file', file);
            
            try {
                const res = await fetch('/api/parse_resume', {
                    method: 'POST',
                    body: formData
                });
                const data = await res.json();
                
                loader.style.display = 'none';
                
                if (data.ok && data.parsed) {
                    const profile = data.parsed;
                    
                    // Auto-fill values
                    if (profile.first_name) document.getElementById('cfg-first_name').value = profile.first_name;
                    if (profile.last_name) document.getElementById('cfg-last_name').value = profile.last_name;
                    if (profile.email) document.getElementById('cfg-email').value = profile.email;
                    if (profile.phone) document.getElementById('cfg-phone').value = profile.phone;
                    if (profile.city) document.getElementById('cfg-city').value = profile.city;
                    if (profile.total_experience_years) document.getElementById('cfg-total_experience_years').value = profile.total_experience_years;
                    
                    if (profile.skills && Array.isArray(profile.skills)) {
                        document.getElementById('cfg-my_skills').value = profile.skills.join(', ');
                    }
                    
                    if (profile.tech_experience && typeof profile.tech_experience === 'object') {
                        // Merge or replace tech experience
                        techExpData = {};
                        for (const [k, v] of Object.entries(profile.tech_experience)) {
                            techExpData[k.toLowerCase()] = String(v);
                        }
                        renderTechExp();
                    }
                    
                    showToast("✨ Resume successfully parsed & loaded! Save to store.");
                    
                    // Highlight the settings inputs temporarily
                    document.querySelectorAll('#settings-personal input, #cfg-my_skills').forEach(el => {
                        el.style.borderColor = 'var(--accent2)';
                        setTimeout(() => { el.style.borderColor = ''; }, 3000);
                    });
                } else {
                    showToast("Failed to parse resume: " + (data.error || "Unknown error"));
                }
            } catch (err) {
                loader.style.display = 'none';
                showToast("Upload request failed.");
                console.error(err);
            }
        });
    }
});
