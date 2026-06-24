"""
app.py  —  Job Bot Web Dashboard (Upgraded Stable v2.0)
Run:  python app.py
Open: http://localhost:5000
"""
import os
import threading
import queue
import datetime
import json
import csv
from flask import Flask, render_template_string, jsonify, request, Response, stream_with_context, send_file

# Force path reference to directory context
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from tracker import get_all_rows, get_today_count, TRACKER_FILE
from qa_store import get_all as qa_get_all, save_answer, get_unanswered, save_question_settings, delete_entry
from config.profile import DAILY_LIMIT, SCHEDULED_RUNS, HEADLESS_DEFAULT

app = Flask(__name__)
_log_q = queue.Queue(maxsize=1000)
_bot_thread = None
STOP_EVENT = threading.Event()
TARGETED_SEARCH_RESULTS = []

def bot_log(msg: str):
    try:
        print(msg)
    except UnicodeEncodeError:
        try:
            print(msg.encode('ascii', errors='replace').decode('ascii'))
        except Exception:
            pass
    try:
        # We classify messages by type for frontend console log tab filtering
        log_type = "info"
        if "[SUCCESS]" in msg or "[OK]" in msg:
            log_type = "success"
        elif "[WARN]" in msg or "[WARNING]" in msg:
            log_type = "warn"
        elif "[ERROR]" in msg or "[FAIL]" in msg or "[STOP]" in msg:
            log_type = "error"
            
        data_payload = {"type": log_type, "message": msg, "time": datetime.datetime.now().strftime("%H:%M:%S")}
        _log_q.put_nowait(f"data: {json.dumps(data_payload)}\n\n")
    except queue.Full:
        pass

# ── Modern HTML/CSS/JS Template (Glassmorphism & Chart.js) ───────────
TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Job Search Bot — Senior Engineer Control Center</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=Inter:wght@300;400;500;600;700&family=Fraunces:ital,opsz,wght@0,9..144,300;0,9..144,700;1,9..144,400&display=swap');

  :root {
    --bg: #0a0c10;
    --surface: #111318;
    --surface2: #181c24;
    --border: #1f2430;
    --accent: #00e5a0;
    --accent2: #4f8cff;
    --accent3: #ff6b6b;
    --accent4: #ffd166;
    --text: #e8eaf0;
    --text-muted: #6b7280;
    --text-dim: #9ca3af;
    --mono: 'IBM Plex Mono', monospace;
    --sans: 'Inter', sans-serif;
    --display: 'Fraunces', serif;
  }
  @keyframes pulse {
    0% { transform: scale(0.9); opacity: 0.5; box-shadow: 0 0 0 0 rgba(255, 59, 48, 0.7); }
    70% { transform: scale(1.1); opacity: 1; box-shadow: 0 0 0 6px rgba(255, 59, 48, 0); }
    100% { transform: scale(0.9); opacity: 0.5; box-shadow: 0 0 0 0 rgba(255, 59, 48, 0); }
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: var(--sans);
    font-size: 15px;
    line-height: 1.7;
    overflow-x: hidden;
  }

  /* ── HERO ── */
  .hero {
    min-height: 90vh;
    display: flex;
    flex-direction: column;
    justify-content: center;
    padding: 80px 60px;
    position: relative;
    overflow: hidden;
    border-bottom: 1px solid var(--border);
  }
  .hero::before {
    content: '';
    position: absolute;
    top: -200px; right: -200px;
    width: 700px; height: 700px;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(0,229,160,0.07) 0%, transparent 70%);
    pointer-events: none;
  }
  .hero::after {
    content: '';
    position: absolute;
    bottom: -100px; left: 200px;
    width: 500px; height: 500px;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(79,140,255,0.05) 0%, transparent 70%);
    pointer-events: none;
  }
  .eyebrow {
    font-family: var(--mono);
    font-size: 11px;
    letter-spacing: 0.2em;
    color: var(--accent);
    text-transform: uppercase;
    margin-bottom: 24px;
  }
  .hero h1 {
    font-family: var(--display);
    font-size: clamp(42px, 6vw, 88px);
    font-weight: 700;
    line-height: 1.05;
    max-width: 800px;
    color: #fff;
    margin-bottom: 24px;
  }
  .hero h1 em {
    font-style: italic;
    color: var(--accent);
  }
  .hero-sub {
    font-size: 18px;
    color: var(--text-dim);
    max-width: 560px;
    margin-bottom: 48px;
    font-weight: 300;
  }
  .stat-row {
    display: flex;
    gap: 48px;
    flex-wrap: wrap;
  }
  .stat {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .stat-num {
    font-family: var(--display);
    font-size: 42px;
    font-weight: 700;
    color: var(--accent);
    line-height: 1;
  }
  .stat-label {
    font-family: var(--mono);
    font-size: 11px;
    color: var(--text-muted);
    letter-spacing: 0.1em;
    text-transform: uppercase;
  }
  .terminal-badge {
    position: absolute;
    top: 40px; right: 60px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px 20px;
    font-family: var(--mono);
    font-size: 12px;
    color: var(--text-dim);
    max-width: 380px;
    z-index: 10;
  }
  .terminal-badge .tline { margin: 2px 0; }
  .terminal-badge .t-g { color: var(--accent); }
  .terminal-badge .t-b { color: var(--accent2); }
  .terminal-badge .t-y { color: var(--accent4); }

  /* ── SECTIONS ── */
  section {
    padding: 80px 60px;
    border-bottom: 1px solid var(--border);
  }
  .section-label {
    font-family: var(--mono);
    font-size: 10px;
    letter-spacing: 0.25em;
    color: var(--text-muted);
    text-transform: uppercase;
    margin-bottom: 12px;
  }
  h2 {
    font-family: var(--display);
    font-size: clamp(28px, 4vw, 48px);
    font-weight: 700;
    color: #fff;
    margin-bottom: 40px;
    line-height: 1.15;
  }
  h3 {
    font-family: var(--sans);
    font-size: 16px;
    font-weight: 600;
    color: #fff;
    margin-bottom: 8px;
  }
  p { color: var(--text-dim); margin-bottom: 12px; }

  /* ── PIPELINE ── */
  .pipeline {
    display: flex;
    align-items: stretch;
    gap: 0;
    overflow-x: auto;
    padding-bottom: 16px;
    margin-bottom: 48px;
  }
  .pipe-step {
    flex: 1;
    min-width: 160px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-right: none;
    padding: 24px 20px;
    position: relative;
  }
  .pipe-step:last-child { border-right: 1px solid var(--border); border-radius: 0 8px 8px 0; }
  .pipe-step:first-child { border-radius: 8px 0 0 8px; }
  .pipe-arrow {
    position: absolute;
    right: -13px; top: 50%;
    transform: translateY(-50%);
    width: 26px; height: 26px;
    background: var(--accent);
    clip-path: polygon(0 20%, 60% 20%, 60% 0, 100% 50%, 60% 100%, 60% 80%, 0 80%);
    z-index: 2;
  }
  .pipe-num {
    font-family: var(--mono);
    font-size: 28px;
    font-weight: 600;
    color: var(--border);
    margin-bottom: 8px;
  }
  .pipe-title {
    font-size: 13px;
    font-weight: 600;
    color: #fff;
    margin-bottom: 4px;
  }
  .pipe-desc {
    font-size: 11px;
    color: var(--text-muted);
    line-height: 1.5;
    margin: 0;
  }

  /* ── SCORE ENGINE ── */
  .score-diagram {
    display: grid;
    grid-template-columns: 1fr 60px 1fr;
    gap: 0;
    align-items: center;
    margin: 40px 0;
  }
  .score-box {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 28px;
  }
  .score-connector {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    font-family: var(--mono);
    font-size: 10px;
    color: var(--text-muted);
  }
  .score-connector .arr { font-size: 20px; color: var(--accent); }
  .threshold-row {
    display: flex;
    flex-direction: column;
    gap: 12px;
    margin-top: 16px;
  }
  .threshold-item {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 16px;
    border-radius: 8px;
    border: 1px solid var(--border);
  }
  .t-green { border-color: rgba(0,229,160,0.3); background: rgba(0,229,160,0.05); }
  .t-yellow { border-color: rgba(255,209,102,0.3); background: rgba(255,209,102,0.05); }
  .t-red { border-color: rgba(255,107,107,0.3); background: rgba(255,107,107,0.05); }
  .t-badge {
    font-family: var(--mono);
    font-size: 18px;
    font-weight: 600;
    min-width: 60px;
  }
  .t-green .t-badge { color: var(--accent); }
  .t-yellow .t-badge { color: var(--accent4); }
  .t-red .t-badge { color: var(--accent3); }
  .t-action {
    font-size: 13px;
    font-weight: 600;
    color: #fff;
  }
  .t-sub {
    font-size: 11px;
    color: var(--text-muted);
    margin: 0;
  }

  /* ── PORTAL GRID ── */
  .portal-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 16px;
  }
  .portal-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 24px;
    position: relative;
    overflow: hidden;
  }
  .portal-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 3px;
  }
  .pc-linkedin::before { background: #0a66c2; }
  .pc-naukri::before { background: #ff7555; }
  .pc-indeed::before { background: #003a9b; }
  .pc-glass::before { background: #0caa41; }
  .pc-ats::before { background: var(--accent); }
  .portal-name {
    font-weight: 600;
    color: #fff;
    margin-bottom: 4px;
  }
  .portal-method {
    font-family: var(--mono);
    font-size: 10px;
    letter-spacing: 0.1em;
    margin-bottom: 12px;
    padding: 3px 8px;
    border-radius: 4px;
    display: inline-block;
  }
  .method-api { background: rgba(79,140,255,0.15); color: var(--accent2); }
  .method-playwright { background: rgba(0,229,160,0.1); color: var(--accent); }
  .method-partner { background: rgba(255,209,102,0.1); color: var(--accent4); }
  .method-scrape { background: rgba(255,107,107,0.1); color: var(--accent3); }
  .portal-note { font-size: 12px; color: var(--text-muted); margin: 0; }

  /* ── FSM ── */
  .fsm {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    margin: 32px 0;
  }
  .fsm-state {
    padding: 10px 18px;
    border-radius: 24px;
    font-size: 13px;
    font-weight: 600;
    border: 1px solid;
  }
  .fsm-arrow { color: var(--text-muted); font-size: 18px; }
  .s-applied { border-color: var(--accent2); color: var(--accent2); background: rgba(79,140,255,0.08); }
  .s-viewed { border-color: var(--accent4); color: var(--accent4); background: rgba(255,209,102,0.08); }
  .s-short { border-color: var(--accent); color: var(--accent); background: rgba(0,229,160,0.08); }
  .s-interview { border-color: #a78bfa; color: #a78bfa; background: rgba(167,139,250,0.08); }
  .s-offer { border-color: var(--accent); color: var(--accent); background: rgba(0,229,160,0.12); }
  .s-rej { border-color: var(--accent3); color: var(--accent3); background: rgba(255,107,107,0.08); }
  .s-ghost { border-color: var(--border); color: var(--text-muted); background: transparent; }

  /* ── UI TABS ── */
  .tabs-container {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    overflow: hidden;
    margin-bottom: 48px;
  }
  .tab-bar {
    display: flex;
    border-bottom: 1px solid var(--border);
    overflow-x: auto;
  }
  .tab-btn {
    padding: 14px 22px;
    font-size: 13px;
    font-weight: 500;
    color: var(--text-muted);
    border: none;
    background: transparent;
    cursor: pointer;
    white-space: nowrap;
    transition: all 0.2s;
    border-bottom: 2px solid transparent;
    font-family: var(--sans);
  }
  .tab-btn:hover { color: var(--text); }
  .tab-btn.active {
    color: var(--accent);
    border-bottom-color: var(--accent);
    background: rgba(0,229,160,0.03);
  }
  .tab-panel { display: none; padding: 32px; }
  .tab-panel.active { display: block; }

  /* mock UI elements / Functional items */
  .mock-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 20px;
    flex-wrap: wrap;
    gap: 12px;
  }
  .mock-title { font-size: 18px; font-weight: 600; color: #fff; }
  .mock-btn {
    background: var(--accent);
    color: #000;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    font-size: 12px;
    font-weight: 700;
    cursor: pointer;
    font-family: var(--sans);
    transition: all 0.2s;
  }
  .mock-btn:hover {
    transform: translateY(-1px);
    opacity: 0.9;
  }
  .mock-btn-red {
    background: var(--accent3);
    color: #fff;
  }
  .mock-btn-outline {
    background: transparent;
    border: 1px solid var(--border);
    color: var(--text-dim);
  }
  .mock-btn-outline:hover {
    border-color: var(--accent);
    color: #fff;
  }

  .job-card {
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 18px;
    margin-bottom: 10px;
    display: flex;
    align-items: center;
    gap: 16px;
    transition: border-color 0.2s;
  }
  .job-card:hover {
    border-color: rgba(0, 229, 160, 0.25);
  }
  .score-ring {
    width: 52px; height: 52px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: var(--mono);
    font-size: 14px;
    font-weight: 600;
    flex-shrink: 0;
    border: 2px solid;
  }
  .ring-high { border-color: var(--accent); color: var(--accent); background: rgba(0,229,160,0.08); }
  .ring-mid { border-color: var(--accent4); color: var(--accent4); background: rgba(255,209,102,0.08); }
  .ring-low { border-color: var(--accent3); color: var(--accent3); background: rgba(255,107,107,0.08); }
  .jc-info { flex: 1; min-width: 0; }
  .jc-title { font-weight: 600; color: #fff; font-size: 14px; text-overflow: ellipsis; overflow: hidden; white-space: nowrap; }
  .jc-company { font-size: 12px; color: var(--text-muted); text-overflow: ellipsis; overflow: hidden; white-space: nowrap; }
  .jc-badge {
    font-family: var(--mono);
    font-size: 10px;
    padding: 3px 8px;
    border-radius: 4px;
    text-transform: uppercase;
    font-weight: 600;
  }
  .b-auto { background: rgba(0,229,160,0.15); color: var(--accent); }
  .b-review { background: rgba(255,209,102,0.15); color: var(--accent4); }
  .b-skip { background: rgba(100,100,100,0.15); color: var(--text-muted); }

  /* kanban */
  .kanban {
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 12px;
    overflow-x: auto;
  }
  .kan-col {
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 12px;
    min-width: 180px;
  }
  .kan-head {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: 10px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--border);
  }
  .kan-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 10px;
    margin-bottom: 8px;
    font-size: 11px;
    transition: transform 0.2s, border-color 0.2s;
  }
  .kan-card:hover {
    transform: translateY(-2px);
    border-color: rgba(255, 255, 255, 0.15);
  }
  .kan-co { font-weight: 600; color: #fff; }
  .kan-role { color: var(--text-muted); margin-top: 2px; text-overflow: ellipsis; overflow: hidden; white-space: nowrap; }

  /* resume tailoring */
  .diff-view {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
  }
  .diff-pane {
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 20px;
  }
  .diff-label {
    font-family: var(--mono);
    font-size: 10px;
    letter-spacing: 0.15em;
    margin-bottom: 12px;
    text-transform: uppercase;
  }
  .diff-label.before { color: var(--accent3); }
  .diff-label.after { color: var(--accent); }
  .diff-text { font-size: 12px; color: var(--text-dim); line-height: 1.7; }
  .diff-text .hl { background: rgba(0,229,160,0.15); color: var(--accent); border-radius: 3px; padding: 0 3px; }
  .diff-text .removed { background: rgba(255,107,107,0.1); color: var(--accent3); border-radius: 3px; padding: 0 3px; text-decoration: line-through; }

  /* ── IMPLEMENTATION TIMELINE ── */
  .timeline {
    position: relative;
    padding-left: 32px;
  }
  .timeline::before {
    content: '';
    position: absolute;
    left: 7px; top: 0; bottom: 0;
    width: 2px;
    background: var(--border);
  }
  .tl-phase {
    position: relative;
    margin-bottom: 40px;
  }
  .tl-dot {
    position: absolute;
    left: -29px; top: 4px;
    width: 14px; height: 14px;
    border-radius: 50%;
    border: 2px solid var(--bg);
  }
  .tl-p1 .tl-dot { background: var(--accent2); }
  .tl-p2 .tl-dot { background: var(--accent4); }
  .tl-p3 .tl-dot { background: var(--accent); }
  .tl-p4 .tl-dot { background: #a78bfa; }
  .tl-weeks {
    font-family: var(--mono);
    font-size: 10px;
    letter-spacing: 0.1em;
    color: var(--text-muted);
    text-transform: uppercase;
    margin-bottom: 4px;
  }
  .tl-title { font-size: 16px; font-weight: 600; color: #fff; margin-bottom: 8px; }
  .tl-items {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 10px;
  }
  .tl-item {
    font-size: 12px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 5px 12px;
    color: var(--text-dim);
  }
  .tl-p1 .tl-item { border-color: rgba(79,140,255,0.2); }
  .tl-p2 .tl-item { border-color: rgba(255,209,102,0.2); }
  .tl-p3 .tl-item { border-color: rgba(0,229,160,0.2); }
  .tl-p4 .tl-item { border-color: rgba(167,139,250,0.2); }

  /* ── HARD PROBLEMS ── */
  .problems-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
    gap: 16px;
  }
  .prob-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 24px;
    border-top: 3px solid;
    position: relative;
  }
  .prob-rank {
    font-family: var(--display);
    font-size: 48px;
    font-weight: 700;
    opacity: 0.08;
    position: absolute;
    top: 12px; right: 20px;
    line-height: 1;
  }
  .prob-card:nth-child(1) { border-top-color: var(--accent3); }
  .prob-card:nth-child(2) { border-top-color: var(--accent4); }
  .prob-card:nth-child(3) { border-top-color: var(--accent2); }
  .prob-card h3 { margin-bottom: 8px; }
  .prob-solve {
    margin-top: 12px;
    background: var(--surface2);
    border-radius: 6px;
    padding: 12px;
    font-size: 12px;
    color: var(--text-dim);
    font-family: var(--mono);
  }
  .prob-solve .s-label {
    color: var(--accent);
    font-size: 10px;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    margin-bottom: 4px;
    display: block;
  }

  /* ── TECH STACK ── */
  .stack-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 12px;
  }
  .stack-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
  }
  .stack-layer {
    font-family: var(--mono);
    font-size: 10px;
    letter-spacing: 0.1em;
    color: var(--text-muted);
    text-transform: uppercase;
    margin-bottom: 6px;
  }
  .stack-items { display: flex; flex-wrap: wrap; gap: 6px; }
  .stack-tag {
    font-size: 12px;
    padding: 3px 10px;
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 4px;
    color: var(--text-dim);
  }

  /* ── FOOTER ── */
  .footer {
    padding: 40px 60px;
    text-align: center;
    font-family: var(--mono);
    font-size: 11px;
    color: var(--text-muted);
    letter-spacing: 0.1em;
  }

  /* Settings config page sub-layout */
  .settings-tabs {
    display: flex;
    gap: 0.5rem;
    margin-bottom: 1.25rem;
    border-bottom: 1px solid var(--border);
    padding-bottom: 0.5rem;
  }
  .settings-tab {
    background: none;
    border: none;
    color: var(--text-muted);
    padding: 0.5rem 1rem;
    font-size: 0.85rem;
    font-weight: 600;
    cursor: pointer;
    border-radius: 6px;
    transition: all 0.2s ease;
  }
  .settings-tab:hover {
    color: var(--text);
    background: rgba(255, 255, 255, 0.03);
  }
  .settings-tab.active {
    color: var(--accent);
    background: rgba(0, 229, 160, 0.1);
  }
  .settings-content {
    display: none;
  }
  .settings-content.active {
    display: block;
  }
  .config-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 1.25rem;
  }
  .input-group {
    display: flex;
    flex-direction: column;
    gap: 0.45rem;
  }
  .input-group label {
    font-size: 0.75rem;
    font-weight: 600;
    color: var(--text-dim);
  }
  .input-group.full-width {
    grid-column: 1 / -1;
  }
  .input-control {
    width: 100%;
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid var(--border);
    border-radius: 8px;
    color: var(--text);
    padding: 0.6rem 0.85rem;
    font-size: 0.85rem;
    transition: all 0.2s ease;
    margin-top: 0.25rem;
    font-family: var(--sans);
    outline: none;
  }
  .input-control:focus {
    border-color: var(--accent);
    background: rgba(0, 229, 160, 0.03);
  }
  .switch-group {
    display: flex;
    align-items: center;
    gap: 0.65rem;
    cursor: pointer;
    user-select: none;
    margin-top: 1.5rem;
    font-size: 13px;
  }
  .switch-group input {
    cursor: pointer;
    accent-color: var(--accent);
    width: 16px;
    height: 16px;
  }

  /* Live actions logger */
  .log-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 0.85rem;
    border-bottom: 1px solid var(--border);
    padding-bottom: 0.5rem;
  }
  .log-tabs {
    display: flex;
    gap: 0.4rem;
  }
  .log-tab {
    background: transparent;
    border: none;
    color: var(--text-muted);
    font-size: 0.75rem;
    font-weight: 600;
    padding: 0.3rem 0.75rem;
    border-radius: 6px;
    cursor: pointer;
    transition: all 0.2s;
  }
  .log-tab:hover {
    color: var(--text);
    background: rgba(255, 255, 255, 0.05);
  }
  .log-tab.active-all { color: #000; background: var(--accent2); }
  .log-tab.active-success { color: #000; background: var(--accent); }
  .log-tab.active-warn { color: #000; background: var(--accent4); }
  .log-tab.active-error { color: #fff; background: var(--accent3); }
  .console-box {
    background: #08090d;
    border: 1px solid var(--border);
    border-radius: 8px;
    height: 300px;
    overflow-y: auto;
    padding: 1rem;
    font-family: var(--mono);
    font-size: 0.8rem;
    line-height: 1.5;
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
  }
  .log-line {
    display: flex;
    gap: 0.75rem;
    border-bottom: 1px dashed rgba(255, 255, 255, 0.03);
    padding-bottom: 0.2rem;
  }
  .log-time {
    color: var(--text-muted);
    flex-shrink: 0;
  }
  .log-text {
    word-break: break-all;
  }
  .log-success { color: var(--accent); }
  .log-warn { color: var(--accent4); }
  .log-error { color: var(--accent3); }
  .log-info { color: var(--accent2); }

  /* Q&A Store resolver styles */
  .qa-card {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    max-height: 350px;
    overflow-y: auto;
  }
  .qa-item {
    background: rgba(0,0,0,0.15);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 0.85rem;
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
  }
  .qa-question {
    font-weight: 600;
    font-size: 0.85rem;
    color: var(--text);
  }
  .qa-form-row {
    display: flex;
    gap: 0.5rem;
  }
  .qa-input {
    flex: 1;
    background: rgba(0,0,0,0.3);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 0.45rem 0.75rem;
    color: var(--text);
    font-size: 0.85rem;
    outline: none;
  }
  .qa-input:focus {
    border-color: var(--accent);
  }

  /* Toast notification system */
  #toast-container {
    position: fixed;
    bottom: 20px;
    right: 20px;
    z-index: 1000;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .toast {
    background: var(--surface2);
    border: 1px solid var(--accent);
    color: var(--text);
    padding: 0.75rem 1.25rem;
    border-radius: 8px;
    box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.3);
    font-size: 0.85rem;
    font-weight: 500;
    transform: translateY(100px);
    opacity: 0;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  }
  .toast.show {
    transform: translateY(0);
    opacity: 1;
  }

  /* stats diagram styles matching blueprint design */
  .stats-grid-horizontal {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px;
    margin-bottom: 24px;
  }

  /* database table styles */
  .table-wrap {
    overflow-x: auto;
    max-height: 400px;
    border-radius: 8px;
    border: 1px solid var(--border);
    margin-top: 16px;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    text-align: left;
    font-size: 13px;
  }
  th {
    background: var(--surface2);
    color: var(--text-dim);
    font-weight: 600;
    padding: 0.75rem 1rem;
    border-bottom: 1px solid var(--border);
    position: sticky;
    top: 0;
    z-index: 10;
  }
  td {
    padding: 0.75rem 1rem;
    border-bottom: 1px solid var(--border);
    vertical-align: top;
    background: rgba(17, 19, 24, 0.4);
    color: var(--text-dim);
  }
  tr:hover td {
    background: rgba(0, 229, 160, 0.03);
  }
  .pill {
    display: inline-block;
    border-radius: 99px;
    padding: 0.15rem 0.55rem;
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    font-family: var(--mono);
  }
  .pill.applied { background: rgba(0, 229, 160, 0.15); color: var(--accent); }
  .pill.skipped { background: rgba(255, 107, 107, 0.15); color: var(--accent3); }
  .pill.manual { background: rgba(255, 209, 102, 0.15); color: var(--accent4); }

  /* responsive */
  @media (max-width: 1024px) {
    .hero, section { padding: 60px 24px; }
    .terminal-badge { position: relative; top: 0; right: 0; margin-bottom: 30px; max-width: 100%; }
    .score-diagram { grid-template-columns: 1fr; }
    .diff-view { grid-template-columns: 1fr; }
    .kanban { grid-template-columns: repeat(3, 1fr); }
    .footer { padding: 40px 24px; }
  }
</style>
</head>
<body>

<!-- HERO -->
<div class="hero">
  <div class="terminal-badge" id="terminal-stats-badge">
    <div class="tline"><span class="t-g">▶</span> bot.status() == <span id="term-status" class="t-g">IDLE</span></div>
    <div class="tline"><span class="t-b">✓</span> active daily limit: <span id="term-limit">{{ daily_limit }}</span></div>
    <div class="tline"><span class="t-b">✓</span> applied today: <span id="term-applied" class="t-g">0</span></div>
    <div class="tline"><span class="t-y">⚡</span> skipped today: <span id="term-skipped" class="t-y">0</span></div>
    <div class="tline"><span class="t-b">→</span> unresolved Q&As: <span id="term-qa" class="t-b">0</span></div>
  </div>

  <div class="eyebrow">Senior Engineer Blueprint — 30 Years Distilled</div>
  <h1>The Job Search Bot<br>that <em>actually</em> works</h1>
  <p class="hero-sub">Full architecture, logic, UI, portals, tracking, and a 16-week implementation plan — built the right way, not the fast way.</p>

  <div class="stat-row">
    <div class="stat">
      <div class="stat-num">8–10×</div>
      <div class="stat-label">more applications/week</div>
    </div>
    <div class="stat">
      <div class="stat-num">~20%</div>
      <div class="stat-label">higher response rate</div>
    </div>
    <div class="stat">
      <div class="stat-num">2-stage</div>
      <div class="stat-label">AI scoring engine</div>
    </div>
    <div class="stat">
      <div class="stat-num">FSM</div>
      <div class="stat-label">per-application tracking</div>
    </div>
  </div>
</div>

<!-- DASHBOARD SECTION -->
<section style="background: #0d0f14; border-top: 1px solid var(--border);">
  <div class="section-label">Interactive Console</div>
  <h2 style="margin-bottom: 20px;">Control Center & Application Hub</h2>
  <p style="margin-bottom: 40px; max-width: 700px;">Trigger new automation runs, modify candidate profiles, manage incoming self-learning Q&A forms, and visualize historical submissions directly from the live control tabs below.</p>

  <div class="tabs-container">
    <div class="tab-bar">
      <button class="tab-btn active" id="btn-tab-feed" onclick="switchTab('feed')">📋 Job Feed / Database</button>
      <button class="tab-btn" id="btn-tab-tracker" onclick="switchTab('tracker')">📊 Tracker (Kanban)</button>
      <button class="tab-btn" id="btn-tab-review" onclick="switchTab('review')">⚠️ Review Queue / Resolver (<span id="qa-tab-count">0</span>)</button>
      <button class="tab-btn" id="btn-tab-resume" onclick="switchTab('resume')">📄 Resume & Cover</button>
      <button class="tab-btn" id="btn-tab-prep" onclick="switchTab('prep')">🎯 Interview Prep</button>
      <button class="tab-btn" id="btn-tab-analytics" onclick="switchTab('analytics')">📈 Funnel Analytics</button>
      <button class="tab-btn" id="btn-tab-settings" onclick="switchTab('settings')">
        ⚙️ Settings Configurations 
        <span id="settings-alert-badge" style="display:none; width: 8px; height: 8px; background-color: #ff3b30; border-radius: 50%; margin-left: 6px; box-shadow: 0 0 8px #ff3b30; display: inline-block; animation: pulse 1.5s infinite;"></span>
      </button>
    </div>

    <!-- JOB FEED / DATABASE -->
    <div class="tab-panel active" id="tab-feed">
      <!-- Notification Center -->
      <div id="notification-banner" style="display:none !important; margin-bottom: 20px; background: linear-gradient(135deg, rgba(255, 179, 0, 0.1) 0%, rgba(239, 68, 68, 0.1) 100%); border: 1px solid rgba(255, 179, 0, 0.25); border-radius: 8px; padding: 16px;">
         <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;">
            <div style="flex:1; min-width:300px;">
               <h4 style="margin:0; color:#ffb300; font-size:14px; font-weight:600; display:flex; align-items:center; gap:6px;">
                  ⚠️ Company Credentials Recommended
               </h4>
               <p id="notification-msg" style="margin:6px 0 0 0; font-size:12px; color:var(--text-dim); line-height:1.5;"></p>
            </div>
            <div style="display:flex; gap:10px;">
               <button class="mock-btn" style="padding:6px 14px; font-size:11px; margin:0; background:#ffb300; color:#000;" onclick="openCompanyCredTab()">🔑 Setup Credentials</button>
               <button class="mock-btn mock-btn-outline" style="padding:6px 14px; font-size:11px; margin:0;" onclick="dismissNotification()">Dismiss</button>
            </div>
         </div>
      </div>
      <div class="mock-header">
        <div class="mock-title">Active Database Control</div>
        <div style="display:flex; gap:10px; align-items:center; flex-wrap:wrap;">
          <label style="font-size:12px; color:var(--text-dim);">Run limit: </label>
          <input type="number" id="max-apps-input" class="input-control" value="15" min="1" max="100" style="width: 70px; padding:4px 8px; margin:0;">
          <label class="switch-group" style="margin:0;">
            <input type="checkbox" id="headless-checkbox" {% if headless_default %}checked{% endif %}> Headless Mode
          </label>
          <button class="mock-btn" onclick="runBot('all')">▶ Run All</button>
          <button class="mock-btn mock-btn-outline" onclick="runBot('linkedin')">LinkedIn Only</button>
          <button class="mock-btn mock-btn-outline" onclick="runBot('naukri')">Naukri Only</button>
          <button class="mock-btn mock-btn-red" onclick="stopBot()">Stop Bots</button>
        </div>
      </div>

      <!-- Real-Time Metrics Summary Block -->
      <div class="stats-grid-horizontal">
        <div style="background:var(--surface2); border:1px solid var(--border); padding:16px; border-radius:8px; display:flex; flex-direction:column; align-items:center;">
          <div style="font-size: 24px; font-weight:700; color:var(--accent);" id="cnt-applied">0</div>
          <div style="font-size:10px; font-family:var(--mono); color:var(--text-muted); text-transform:uppercase; margin-top:4px;">Applied Today</div>
        </div>
        <div style="background:var(--surface2); border:1px solid var(--border); padding:16px; border-radius:8px; display:flex; flex-direction:column; align-items:center;">
          <div style="font-size: 24px; font-weight:700; color:var(--accent3);" id="cnt-skipped">0</div>
          <div style="font-size:10px; font-family:var(--mono); color:var(--text-muted); text-transform:uppercase; margin-top:4px;">Skipped Today</div>
        </div>
        <div style="background:var(--surface2); border:1px solid var(--border); padding:16px; border-radius:8px; display:flex; flex-direction:column; align-items:center;">
          <div style="font-size: 24px; font-weight:700; color:var(--accent4);" id="cnt-manual">0</div>
          <div style="font-size:10px; font-family:var(--mono); color:var(--text-muted); text-transform:uppercase; margin-top:4px;">Manual Needed</div>
        </div>
        <div style="background:var(--surface2); border:1px solid var(--border); padding:16px; border-radius:8px; display:flex; flex-direction:column; align-items:center;">
          <div style="font-size: 24px; font-weight:700; color:var(--accent2);" id="cnt-total">0</div>
          <div style="font-size:10px; font-family:var(--mono); color:var(--text-muted); text-transform:uppercase; margin-top:4px;">Total Logs</div>
        </div>
      </div>

      <!-- Targeted Unified Search & Recruiter Lead Scraper card -->
      <div style="background:var(--surface1); border:1px solid var(--border); padding:20px; border-radius:12px; margin-top:20px; box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.2); backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px);">
        <h3 style="margin-top:0; color:var(--accent); font-size:16px; font-weight:700; display:flex; align-items:center; gap:8px;">
          🎯 Targeted Search & Recruiter Lead Scraper
        </h3>
        <p style="margin:4px 0 16px 0; font-size:12px; color:var(--text-dim);">
          Scan custom target companies (e.g. PwC via direct API), run targeted portal queries (LinkedIn/Naukri), and harvest Google Forms from HR recruiter posts.
        </p>
        
        <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap:16px; margin-bottom:16px;">
          <div>
            <label style="display:block; font-size:11px; font-family:var(--mono); color:var(--text-muted); text-transform:uppercase; margin-bottom:6px;">Company Name</label>
            <input type="text" id="target-company-input" class="input-control" placeholder="e.g. PwC" style="width:100%; margin:0;">
          </div>
          <div>
            <label style="display:block; font-size:11px; font-family:var(--mono); color:var(--text-muted); text-transform:uppercase; margin-bottom:6px;">Skillset / Designation</label>
            <input type="text" id="target-skills-input" class="input-control" placeholder="e.g. AWS/Snowflake/PySpark/SQL" style="width:100%; margin:0;">
          </div>
          <div>
            <label style="display:block; font-size:11px; font-family:var(--mono); color:var(--text-muted); text-transform:uppercase; margin-bottom:6px;">Location</label>
            <input type="text" id="target-location-input" class="input-control" placeholder="e.g. Pune/Mumbai/Bangalore" style="width:100%; margin:0;">
          </div>
        </div>
        
        <div style="display:flex; gap:12px; justify-content:flex-end; flex-wrap:wrap;">
          <button class="mock-btn" onclick="runTargetedSearch()" style="background: linear-gradient(135deg, var(--accent) 0%, #009933 100%); border:none; color:#fff;">
            🚀 Run Targeted Search
          </button>
          <button class="mock-btn mock-btn-outline" onclick="runRecruiterScraper()">
            🔍 Scrape Recruiter Posts & Forms
          </button>
        </div>
      </div>

      <!-- Targeted Search Results Panel -->
      <div id="targeted-results-panel" style="display:none; background:var(--surface1); border:1px solid var(--border); padding:20px; border-radius:12px; margin-top:20px; box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.2); backdrop-filter: blur(10px);">
        <h3 style="margin-top:0; color:var(--accent2); font-size:16px; font-weight:700; display:flex; align-items:center; gap:8px;">
          📋 Collated Targeted Search Results
        </h3>
        <p style="margin:4px 0 16px 0; font-size:12px; color:var(--text-dim);">
          Discovered jobs matching your criteria from direct company sites, LinkedIn, and Naukri. Duplicate jobs have been removed.
        </p>
        
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Portal</th>
                <th>Company</th>
                <th>Role</th>
                <th>Location</th>
                <th>Match Score</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody id="targeted-results-tbody">
              <!-- Dynamically rendered -->
            </tbody>
          </table>
        </div>
      </div>

      <div class="log-header" style="margin-top:24px;">
        <h2>📜 Live Action Stream</h2>
        <div class="log-tabs">
          <button class="log-tab active-all" onclick="setFilter('all')">All</button>
          <button class="log-tab" onclick="setFilter('success')">Success</button>
          <button class="log-tab" onclick="setFilter('warn')">Warnings</button>
          <button class="log-tab" onclick="setFilter('error')">Errors</button>
          <button class="log-tab" style="margin-left: 0.5rem; background:rgba(255,255,255,0.05)" onclick="clearLogs()">Clear</button>
        </div>
      </div>
      <div class="console-box" id="console" style="margin-bottom:28px;">
        <!-- Dynamic logs stream -->
      </div>

      <div style="display:flex; justify-content:space-between; align-items:center; margin-top:20px;">
        <h2>📋 Job Application Database History</h2>
        <button class="mock-btn mock-btn-outline" onclick="exportCSV()">📥 Export CSV Tracker</button>
      </div>
      
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Date Applied</th>
              <th>Company</th>
              <th>Role</th>
              <th>Portal</th>
              <th>Status</th>
              <th>Match</th>
              <th>Posted</th>
              <th>Reason / Skills</th>
            </tr>
          </thead>
          <tbody id="app-tbody">
            <!-- Dynamic Database Applications -->
          </tbody>
        </table>
      </div>
    </div>

    <!-- TRACKER (KANBAN) -->
    <div class="tab-panel" id="tab-tracker">
      <div class="mock-header">
        <div class="mock-title">Interactive Kanban Tracking Board</div>
        <div style="font-size:12px; color:var(--text-muted);" id="kanban-total-count">0 active applications tracked</div>
      </div>
      <div class="kanban" id="kanban-columns">
        <div class="kan-col">
          <div class="kan-head" style="color:var(--accent4);">Review / Drafts (<span id="kb-count-draft">0</span>)</div>
          <div id="kb-col-draft"></div>
        </div>
        <div class="kan-col">
          <div class="kan-head" style="color:var(--accent2);">Applied (<span id="kb-count-applied">0</span>)</div>
          <div id="kb-col-applied"></div>
        </div>
        <div class="kan-col">
          <div class="kan-head" style="color:var(--accent);">Shortlisted / Match (<span id="kb-count-match">0</span>)</div>
          <div id="kb-col-match"></div>
        </div>
        <div class="kan-col">
          <div class="kan-head" style="color:#a78bfa;">Interview (<span id="kb-count-interview">0</span>)</div>
          <div id="kb-col-interview"></div>
        </div>
        <div class="kan-col">
          <div class="kan-head" style="color:var(--text-muted);">Closed / Skip (<span id="kb-count-closed">0</span>)</div>
          <div id="kb-col-closed"></div>
        </div>
      </div>
    </div>

    <!-- REVIEW QUEUE / RESOLVER -->
    <div class="tab-panel" id="tab-review">
      <div class="mock-header" style="justify-content: space-between; align-items: center; margin-bottom: 15px; flex-wrap: wrap; gap:10px;">
        <div class="mock-title">Self-Learning Form Resolver Queue</div>
        <div style="display:flex; gap:10px;">
          <button class="tab-btn active" id="btn-qa-sub-pending" onclick="switchQASubTab('pending')" style="padding: 6px 14px; font-size:11px; margin:0;">⚠️ Pending Review (<span id="qa-sub-pending-count">0</span>)</button>
          <button class="tab-btn" id="btn-qa-sub-jobs" onclick="switchQASubTab('jobs')" style="padding: 6px 14px; font-size:11px; margin:0;">📋 Jobs Pending Review (<span id="jobs-review-count">0</span>)</button>
          <button class="tab-btn" id="btn-qa-sub-all" onclick="switchQASubTab('all')" style="padding: 6px 14px; font-size:11px; margin:0;">📚 Memory Bank Library</button>
        </div>
      </div>
      
      <!-- Pending subtab explanation -->
      <div id="qa-pane-pending-info">
        <p style="font-size:13px; color:var(--text-dim); margin-bottom:20px;">When a browser automation bot hits a form questionnaire field it doesn't recognize (like specific cultural values, sponsorship details, or custom text prompts), it caches the question here. Type the answer and save it to programmatically build the bot's custom Q&A memory store so it never skips this question again!</p>
      </div>

      <!-- Jobs Pending Review subtab explanation -->
      <div id="qa-pane-jobs-info" style="display:none; margin-bottom: 20px;">
        <p style="font-size:13px; color:var(--text-dim); margin-bottom:20px;">Review borderline job matches (scores between 55% and 74%) before the bot submits your application. You can view missing skills to make an informed decision to approve (triggers background application) or reject (skips the job).</p>
      </div>

      <!-- Memory bank subtab explanation & category selector -->
      <div id="qa-pane-all-info" style="display:none; margin-bottom: 20px;">
        <p style="font-size:13px; color:var(--text-dim); margin-bottom:15px;">Manage your bot's custom knowledge library. Categorize questions and toggle between <strong>Auto-Answer</strong> (automatic filling using your saved answer) and <strong>Manual Entry</strong> (bot skips filling this field and lets you do it manually).</p>
        
        <div style="display:flex; gap:8px; flex-wrap:wrap; background: var(--surface2); padding: 8px; border-radius: 8px; border: 1px solid var(--border);">
          <button class="mock-btn active" id="btn-qa-cat-all" onclick="filterQACategory('all')" style="padding: 4px 10px; font-size:10px; margin:0; font-family:var(--mono);">ALL</button>
          <button class="mock-btn mock-btn-outline" id="btn-qa-cat-exp" onclick="filterQACategory('exp')" style="padding: 4px 10px; font-size:10px; margin:0; font-family:var(--mono);">💡 Experience & Skills</button>
          <button class="mock-btn mock-btn-outline" id="btn-qa-cat-comp" onclick="filterQACategory('comp')" style="padding: 4px 10px; font-size:10px; margin:0; font-family:var(--mono);">💰 Salary & CTC</button>
          <button class="mock-btn mock-btn-outline" id="btn-qa-cat-time" onclick="filterQACategory('time')" style="padding: 4px 10px; font-size:10px; margin:0; font-family:var(--mono);">⏳ Notice & Timeline</button>
          <button class="mock-btn mock-btn-outline" id="btn-qa-cat-legal" onclick="filterQACategory('legal')" style="padding: 4px 10px; font-size:10px; margin:0; font-family:var(--mono);">🛡️ Legal & Visa</button>
          <button class="mock-btn mock-btn-outline" id="btn-qa-cat-other" onclick="filterQACategory('other')" style="padding: 4px 10px; font-size:10px; margin:0; font-family:var(--mono);">📂 Others</button>
        </div>
      </div>

      <!-- Pending List -->
      <div class="qa-card" id="qa-list">
        <p style="color:var(--text-muted)">Checking for unresolved portal questions...</p>
      </div>

      <!-- Jobs Review List Container -->
      <div id="jobs-review-list" style="display:none;">
        <!-- Bulk Controls Panel -->
        <div style="background:var(--surface2); border:1px solid var(--border); padding:16px; border-radius:8px; margin-bottom:16px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:16px;">
          <div>
            <h4 style="margin:0; font-size:13px; color:var(--text); font-weight:700;">⚡ Smart Bulk Operations</h4>
            <p style="margin:2px 0 0 0; font-size:11px; color:var(--text-dim);">Perform bulk actions on all currently queued borderline matches.</p>
          </div>
          <div style="display:flex; align-items:center; gap:12px; flex-wrap:wrap;">
            <div style="display:flex; align-items:center; gap:6px;">
              <span style="font-size:11px; color:var(--text-muted); font-family:var(--mono);">Min Score:</span>
              <input type="number" id="bulk-min-score" class="input-control" value="65" min="50" max="100" style="width:60px; padding:3px 6px; font-size:11px; margin:0;">
              <button class="mock-btn" onclick="bulkApprove(true)" style="padding:4px 10px; font-size:11px; margin:0; background:#006622; color:#fff; border-color:#00802b;">🚀 Approve All >= Min Score</button>
            </div>
            <div style="height:20px; width:1px; background:var(--border);"></div>
            <button class="mock-btn" onclick="bulkApprove(false)" style="padding:4px 10px; font-size:11px; margin:0;">⚡ Approve All</button>
            <button class="mock-btn mock-btn-red" onclick="bulkReject()" style="padding:4px 10px; font-size:11px; margin:0;">❌ Reject All</button>
          </div>
        </div>
        
        <!-- The actual scrollable list of jobs -->
        <div class="qa-card" id="jobs-review-sublist" style="max-height: 450px; overflow-y: auto;">
          <p style="color:var(--text-muted)">Checking for job applications pending review...</p>
        </div>
      </div>

      <!-- Library List (All) -->
      <div class="qa-card" id="qa-all-list" style="display:none; max-height: 450px;">
        <p style="color:var(--text-muted)">Loading custom knowledge database...</p>
      </div>
    </div>

    <!-- RESUME & COVER -->
    <div class="tab-panel" id="tab-resume">
      <div class="mock-header">
        <div class="mock-title">ATS Resume Customization Panel</div>
      </div>
      <p style="font-size:13px; color:var(--text-dim); margin-bottom:16px;">The dashboard monitors candidate master PDFs. The bot uses matching algorithms to structure and format summaries. You can inspect the resume path configuration below.</p>
      
      <div style="background: var(--surface2); padding:24px; border:1px solid var(--border); border-radius:10px; margin-bottom:20px;">
        <div class="input-group full-width">
          <label>Active Resume Absolute Path</label>
          <input type="text" id="cfg-resume_path-tab" class="input-control" readonly style="opacity:0.8; font-family:var(--mono);">
          <small style="color:var(--text-muted); margin-top:6px; display:block;">To modify the resume path location, head over to the Settings Configurations tab and edit the values.</small>
        </div>
      </div>

      <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px;">
        <div style="background:var(--surface2); border:1px solid var(--border); border-radius:8px; padding:16px;">
          <div style="font-family:var(--mono); font-size:10px; color:var(--text-muted); margin-bottom:8px; text-transform:uppercase;">Master sections</div>
          <div style="font-size:12px; color:var(--text-dim); line-height:2;">
            ✓ Summary (Rewritten dynamically)<br>
            ✓ Skills (Parsed & categorised)<br>
            ✓ Experience (Ranked by keyword matching)<br>
            ✓ Machine-readable single column<br>
            ✓ Passes Sovren & Affinda ATS systems
          </div>
        </div>
        <div style="background:var(--surface2); border:1px solid var(--border); border-radius:8px; padding:16px;">
          <div style="font-family:var(--mono); font-size:10px; color:var(--text-muted); margin-bottom:8px; text-transform:uppercase;">Target Cover Letter Template</div>
          <div style="font-size:12px; color:var(--text-dim); line-height:1.6;" id="cfg-cover_letter-preview">
            [No cover letter loaded]
          </div>
        </div>
      </div>
    </div>

    <!-- INTERVIEW PREP -->
    <div class="tab-panel" id="tab-prep">
      <div class="mock-header">
        <div class="mock-title">Interview Prep Generator</div>
      </div>
      <p style="font-size:13px; color:var(--text-dim); margin-bottom:16px;">Likely target behavioral and technical questions, formatted to help you frame responses using the STAR method.</p>
      
      <div style="display:flex; flex-direction:column; gap:10px;">
        <div style="background:var(--surface2); border:1px solid var(--border); border-radius:8px; padding:16px;">
          <div style="font-size:13px; font-weight:600; color:var(--accent4); margin-bottom:6px;">Q: "Walk me through a time you improved software performance significantly."</div>
          <div style="font-size:12px; color:var(--text-dim);">→ Suggested STAR approach: Situation (Legacy microservice scaling bottleneck), Task (Optimise SQL/queries & introduce caching), Action (Created indexing indexes, Redis store integration, API payload trimming), Result (40% response reduction, handled 2x traffic load).</div>
        </div>
        <div style="background:var(--surface2); border:1px solid var(--border); border-radius:8px; padding:16px;">
          <div style="font-size:13px; font-weight:600; color:var(--accent4); margin-bottom:6px;">Q: "How do you handle real-time messaging or queues at scale?"</div>
          <div style="font-size:12px; color:var(--text-dim);">→ Suggested STAR approach: Reference Redis Bull Queue or Kafka queues, describe backpressure management, decoupling processes, and exponential backoff retry algorithms.</div>
        </div>
      </div>
    </div>

    <!-- SETTINGS CONFIGURATIONS -->
    <div class="tab-panel" id="tab-settings">
      <div class="mock-title" style="margin-bottom:20px;">Portal settings configuration</div>
      
      <div class="settings-tabs" style="margin-top:0.75rem;">
        <button class="settings-tab active" id="btn-settings-personal" onclick="switchSettingsTab('settings-personal')">Credentials</button>
        <button class="settings-tab" id="btn-settings-skills" onclick="switchSettingsTab('settings-skills')">Skills & Exp</button>
        <button class="settings-tab" id="btn-settings-targets" onclick="switchSettingsTab('settings-targets')">Keywords & Targets</button>
        <button class="settings-tab" id="btn-settings-company-creds" onclick="switchSettingsTab('settings-company-creds')">
          Company Credentials
          <span id="company-creds-alert-badge" style="display:none; width: 6px; height: 6px; background-color: #ff3b30; border-radius: 50%; margin-left: 4px; box-shadow: 0 0 6px #ff3b30; display: inline-block; animation: pulse 1.5s infinite;"></span>
        </button>
        <button class="settings-tab" id="btn-settings-cover" onclick="switchSettingsTab('settings-cover')">Cover Letter</button>
      </div>
      
      <div id="settings-personal" class="settings-content active">
        <div class="config-grid">
          <div class="input-group">
            <label>First Name</label>
            <input type="text" id="cfg-first_name" class="input-control">
          </div>
          <div class="input-group">
            <label>Last Name</label>
            <input type="text" id="cfg-last_name" class="input-control">
          </div>
          <div class="input-group">
            <label>Email</label>
            <input type="email" id="cfg-email" class="input-control">
          </div>
          <div class="input-group">
            <label>Phone</label>
            <input type="text" id="cfg-phone" class="input-control">
          </div>
          <div class="input-group">
            <label>City</label>
            <input type="text" id="cfg-city" class="input-control">
          </div>
          <div class="input-group">
            <label>LinkedIn Email</label>
            <input type="email" id="cfg-linkedin_email" class="input-control">
          </div>
          <div class="input-group">
            <label>LinkedIn Password</label>
            <input type="password" id="cfg-linkedin_password" class="input-control">
          </div>
          <div class="input-group">
            <label>Naukri Email</label>
            <input type="email" id="cfg-naukri_email" class="input-control">
          </div>
          <div class="input-group">
            <label>Naukri Password</label>
            <input type="password" id="cfg-naukri_password" class="input-control">
          </div>
          <div class="input-group">
            <label>Corporate/Workday Email</label>
            <input type="email" id="cfg-corp_email" class="input-control">
          </div>
          <div class="input-group">
            <label>Corporate/Workday Password</label>
            <input type="password" id="cfg-corp_password" class="input-control">
          </div>
          <div class="input-group full-width" style="margin-top:15px;">
            <label style="color:var(--accent); font-weight:700;">Google Gemini API Key (Optional - Enables Smart AI Q&A Solver)</label>
            <input type="text" id="cfg-gemini_api_key" class="input-control" placeholder="Enter your free Gemini API Key (AIzaSy...)">
          </div>
          <div class="input-group">
            <label style="color:var(--accent2); font-weight:700;">IMAP Email Host</label>
            <input type="text" id="cfg-imap_host" class="input-control" placeholder="imap.gmail.com">
          </div>
          <div class="input-group">
            <label style="color:var(--accent2); font-weight:700;">IMAP Email Address</label>
            <input type="email" id="cfg-imap_email" class="input-control" placeholder="yourname@gmail.com">
          </div>
          <div class="input-group">
            <label style="color:var(--accent2); font-weight:700;">IMAP App Password</label>
            <input type="password" id="cfg-imap_password" class="input-control" placeholder="App password from Google settings">
          </div>
        </div>
      </div>
      
      <div id="settings-skills" class="settings-content">
        <div class="config-grid">
          <div class="input-group">
            <label>Total Experience (Years)</label>
            <input type="number" id="cfg-total_experience_years" class="input-control">
          </div>
          <div class="input-group">
            <label>Current CTC (LPA)</label>
            <input type="number" id="cfg-current_ctc" class="input-control">
          </div>
          <div class="input-group">
            <label>Expected CTC (LPA)</label>
            <input type="number" id="cfg-expected_ctc" class="input-control">
          </div>
          <div class="input-group">
            <label>Notice Period (Days)</label>
            <input type="number" id="cfg-notice_period" class="input-control">
          </div>
          <div class="input-group full-width">
            <label>Resume Path (PDF file path on your PC)</label>
            <input type="text" id="cfg-resume_path" class="input-control">
          </div>
          <div class="input-group full-width">
            <label>Skills (comma separated, e.g. SQL, Python, Spark)</label>
            <input type="text" id="cfg-my_skills" class="input-control">
          </div>
          <div class="input-group full-width" style="margin-top: 1.5rem;">
            <label style="font-weight: 700; color: var(--accent2);">Tech-Specific Experience (Years)</label>
            <div id="tech-exp-container" style="display:grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap:12px; margin-top:10px; margin-bottom:16px;">
              <!-- Loaded via JS -->
            </div>
            <div style="display:flex; gap:10px; max-width:480px; align-items:center;">
              <input type="text" id="new-tech-name" placeholder="Tech Name (e.g. Snowflake)" class="input-control" style="flex:2; padding:6px 10px; font-size:13px; margin:0;" />
              <input type="number" id="new-tech-years" placeholder="Years" class="input-control" style="flex:1; padding:6px 10px; font-size:13px; margin:0;" min="0" />
              <button class="mock-btn" type="button" onclick="addNewTechExp()" style="padding:6px 12px; font-size:13px; margin:0; background:var(--accent2); color:white; border:none; border-radius:4px; cursor:pointer;">Add</button>
            </div>
          </div>
        </div>
      </div>
      
      <div id="settings-targets" class="settings-content">
        <div class="config-grid">
          <div class="input-group full-width">
            <label>Search Job Keywords (comma separated)</label>
            <input type="text" id="cfg-search_keywords" class="input-control">
          </div>
          <div class="input-group full-width">
            <label>Search Job Locations (comma separated)</label>
            <input type="text" id="cfg-search_locations" class="input-control">
          </div>
          <div class="input-group full-width">
            <label>Target Companies Filter (comma separated)</label>
            <input type="text" id="cfg-target_companies" class="input-control">
          </div>
          <div class="input-group">
            <label>Minimum Match Score Floor</label>
            <input type="number" id="cfg-min_match_score" class="input-control">
          </div>
          <div class="input-group">
            <label>Daily Application Limit</label>
            <input type="number" id="cfg-daily_limit" class="input-control">
          </div>
          <div class="input-group">
            <label>Auto-Apply Score Threshold (e.g. 75)</label>
            <input type="number" id="cfg-auto_threshold" class="input-control">
          </div>
          <div class="input-group">
            <label>Review Queue Score Threshold (e.g. 55)</label>
            <input type="number" id="cfg-review_threshold" class="input-control">
          </div>
        </div>
      </div>
      
      <div id="settings-company-creds" class="settings-content">
        <p style="font-size:12px; color:var(--text-dim); margin-bottom:15px;">Configure custom login details for specific target companies. The bot will automatically retrieve and apply these credentials on external portals.</p>
        
        <div style="background:var(--surface2); padding:24px; border:1px solid var(--border); border-radius:10px; margin-bottom:20px;">
          <h4 style="margin:0 0 12px 0; color:var(--accent); font-size:13px;">Add New Company Credential</h4>
          <div style="display:grid; grid-template-columns:1fr 1fr 1fr auto; gap:12px; align-items:flex-end; flex-wrap:wrap;">
            <div class="input-group" style="margin:0; flex:1; min-width:150px;">
              <label style="font-size:11px; margin-bottom:4px;">Company Name (e.g. Accenture)</label>
              <input type="text" id="add-company-name" class="input-control" placeholder="Accenture" style="padding:6px 10px; font-size:12px; margin:0; height:auto;">
            </div>
            <div class="input-group" style="margin:0; flex:1; min-width:150px;">
              <label style="font-size:11px; margin-bottom:4px;">Email / Username</label>
              <input type="email" id="add-company-email" class="input-control" placeholder="yourname@corp.com" style="padding:6px 10px; font-size:12px; margin:0; height:auto;">
            </div>
            <div class="input-group" style="margin:0; flex:1; min-width:150px;">
              <label style="font-size:11px; margin-bottom:4px;">Password</label>
              <input type="password" id="add-company-password" class="input-control" placeholder="••••••••" style="padding:6px 10px; font-size:12px; margin:0; height:auto;">
            </div>
            <button class="mock-btn" style="padding:7px 18px; font-size:12px; margin:0; height:auto;" onclick="addCompanyCredential()">Add</button>
          </div>
        </div>

        <div class="table-wrap" style="max-height: 250px;">
          <table>
            <thead>
              <tr>
                <th>Company</th>
                <th>Username/Email</th>
                <th>Password</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody id="company-creds-tbody">
              <!-- Dynamically rendered custom company credentials -->
            </tbody>
          </table>
        </div>
      </div>
      
      <div id="settings-cover" class="settings-content">
        <div class="input-group full-width">
          <label>Cover Letter Template</label>
          <textarea id="cfg-cover_letter" class="input-control" style="min-height:150px; font-family:var(--mono);"></textarea>
        </div>
      </div>
      
      <div style="margin-top: 1.25rem; display: flex; justify-content: flex-end;">
        <button class="mock-btn" onclick="saveProfileSettings()">💾 Save Configurations</button>
      </div>
    </div>

    <!-- FUNNEL ANALYTICS & CALLBACK TRACKER -->
    <div class="tab-panel" id="tab-analytics">
      <div class="mock-header">
        <div class="mock-title">Application Funnel & Callback Tracker</div>
      </div>
      <p style="font-size:13px; color:var(--text-dim); margin-bottom:20px;">
        Monitor the real-time application conversion funnel and manually update callback progression stages to keep your job search metrics accurate.
      </p>

      <div style="display:grid; grid-template-columns: 1fr 1fr; gap:24px; margin-bottom:32px;">
        <!-- Funnel Visualization Card -->
        <div style="background:var(--surface2); border:1px solid var(--border); border-radius:8px; padding:20px;">
          <h3 style="margin-top:0; margin-bottom:16px; font-size:16px; color:var(--accent);">Conversion Funnel</h3>
          <div style="height:280px; position:relative;">
            <canvas id="funnelChart"></canvas>
          </div>
        </div>

        <!-- Conversion Metrics Card -->
        <div style="background:var(--surface2); border:1px solid var(--border); border-radius:8px; padding:20px; display:flex; flex-direction:column; justify-content:space-between;">
          <div>
            <h3 style="margin-top:0; margin-bottom:16px; font-size:16px; color:var(--accent3);">Key Funnel Metrics</h3>
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:16px;">
              <div style="background:var(--surface); border:1px solid var(--border); padding:12px; border-radius:6px; text-align:center;">
                <div style="font-size:20px; font-weight:700; color:#fff;" id="metrics-scanned">0</div>
                <div style="font-size:10px; color:var(--text-muted); text-transform:uppercase; margin-top:4px;">Total Scanned</div>
              </div>
              <div style="background:var(--surface); border:1px solid var(--border); padding:12px; border-radius:6px; text-align:center;">
                <div style="font-size:20px; font-weight:700; color:var(--accent);" id="metrics-applied">0</div>
                <div style="font-size:10px; color:var(--text-muted); text-transform:uppercase; margin-top:4px;">Applied</div>
              </div>
              <div style="background:var(--surface); border:1px solid var(--border); padding:12px; border-radius:6px; text-align:center;">
                <div style="font-size:20px; font-weight:700; color:var(--accent4);" id="metrics-interviews">0</div>
                <div style="font-size:10px; color:var(--text-muted); text-transform:uppercase; margin-top:4px;">Interviews</div>
              </div>
              <div style="background:var(--surface); border:1px solid var(--border); padding:12px; border-radius:6px; text-align:center;">
                <div style="font-size:20px; font-weight:700; color:#4ade80;" id="metrics-offers">0</div>
                <div style="font-size:10px; color:var(--text-muted); text-transform:uppercase; margin-top:4px;">Offers Received</div>
              </div>
            </div>
          </div>
          <div style="border-top:1px solid var(--border); padding-top:16px; margin-top:16px;">
            <div style="display:flex; justify-content:space-between; margin-bottom:8px; font-size:12px;">
              <span style="color:var(--text-dim);">Application Rate (Applied / Scanned):</span>
              <span style="font-weight:600; color:var(--accent);" id="metrics-app-rate">0%</span>
            </div>
            <div style="display:flex; justify-content:space-between; margin-bottom:8px; font-size:12px;">
              <span style="color:var(--text-dim);">Interview Callback Rate (Interview / Applied):</span>
              <span style="font-weight:600; color:var(--accent4);" id="metrics-callback-rate">0%</span>
            </div>
            <div style="display:flex; justify-content:space-between; font-size:12px;">
              <span style="color:var(--text-dim);">Offer Success Rate (Offer / Interview):</span>
              <span style="font-weight:600; color:#4ade80;" id="metrics-offer-rate">0%</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Interactive Callback Tracker Table -->
      <div style="background:var(--surface2); border:1px solid var(--border); border-radius:8px; padding:20px;">
        <h3 style="margin-top:0; margin-bottom:16px; font-size:16px; color:var(--accent2);">Callback Tracker & Stage Editor</h3>
        <div style="overflow-x:auto;">
          <table style="width:100%; border-collapse:collapse; font-size:12px;">
            <thead>
              <tr style="border-bottom:2px solid var(--border); text-align:left;">
                <th style="padding:10px 8px; color:var(--text-muted);">Company</th>
                <th style="padding:10px 8px; color:var(--text-muted);">Role</th>
                <th style="padding:10px 8px; color:var(--text-muted);">Portal</th>
                <th style="padding:10px 8px; color:var(--text-muted);">Match %</th>
                <th style="padding:10px 8px; color:var(--text-muted);">Date Logged</th>
                <th style="padding:10px 8px; color:var(--text-muted);">Current Stage</th>
              </tr>
            </thead>
            <tbody id="analytics-tbody">
              <!-- Dynamically populated rows -->
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</section>

<!-- WHAT IT DOES -->
<section>
  <div class="section-label">Core Concept</div>
  <h2>What the bot actually does —<br>the honest picture</h2>

  <div class="pipeline">
    <div class="pipe-step">
      <div class="pipe-arrow"></div>
      <div class="pipe-num">01</div>
      <div class="pipe-title">Watch Portals 24/7</div>
      <p class="pipe-desc">Continuously polls LinkedIn, Naukri, Indeed, Glassdoor and company ATS via API or Playwright.</p>
    </div>
    <div class="pipe-step">
      <div class="pipe-arrow"></div>
      <div class="pipe-num">02</div>
      <div class="pipe-title">Score & Filter</div>
      <p class="pipe-desc">Two-stage AI engine: fast embedding similarity → deep LLM score (0–100) with justification.</p>
    </div>
    <div class="pipe-step">
      <div class="pipe-arrow"></div>
      <div class="pipe-num">03</div>
      <div class="pipe-title">Decide: Auto / Review / Skip</div>
      <p class="pipe-desc">Score ≥75 → auto-apply. 55–75 → human queue. &lt;55 → silently skipped.</p>
    </div>
    <div class="pipe-step">
      <div class="pipe-arrow"></div>
      <div class="pipe-num">04</div>
      <div class="pipe-title">Tailor Resume + Cover</div>
      <p class="pipe-desc">AI rewrites summary, reorders bullets, injects keywords, writes 3-para cover letter per role.</p>
    </div>
    <div class="pipe-step">
      <div class="pipe-arrow"></div>
      <div class="pipe-num">05</div>
      <div class="pipe-title">Submit Application</div>
      <p class="pipe-desc">API submit or Playwright-driven form fill. Bespoke parsers per ATS (Workday, Greenhouse, etc).</p>
    </div>
    <div class="pipe-step">
      <div class="pipe-num">06</div>
      <div class="pipe-title">Track & Advance FSM</div>
      <p class="pipe-desc">Monitors email (IMAP) + portal APIs. Automatically moves state: Applied → Viewed → Interview…</p>
    </div>
  </div>

  <p style="font-size:14px; color: var(--text-dim); max-width: 720px;">The candidate wakes up to a prioritised to-do list instead of a firehose of listings. The cognitive load collapses from "spend evenings scrolling Naukri" to "review 8 flagged jobs and prepare for the 3 interviews the bot already booked."</p>
</section>

<!-- SCORING ENGINE -->
<section>
  <div class="section-label">Intelligence Layer</div>
  <h2>The AI Scoring Engine —<br>how the bot decides</h2>

  <div class="score-diagram">
    <div class="score-box">
      <h3 style="color: var(--accent2); margin-bottom: 16px;">Stage 1 — Fast Filter</h3>
      <p style="font-size:13px;">Embedding cosine similarity using <strong style="color:#fff">OpenAI ada-002</strong> or equivalent. Processes hundreds of listings in milliseconds. Drops obvious mismatches before the expensive LLM call.</p>
      <div style="margin-top:16px; font-family: var(--mono); font-size:11px; color: var(--text-muted); background: var(--surface2); padding:12px; border-radius:6px;">
        score = cosine(embed(JD), embed(resume))<br>
        threshold: &gt; 0.65 → proceed to Stage 2
      </div>
    </div>
    <div class="score-connector">
      <span class="arr">→</span>
      <span>then</span>
    </div>
    <div class="score-box">
      <h3 style="color: var(--accent4); margin-bottom: 16px;">Stage 2 — Deep Score</h3>
      <p style="font-size:13px;">Full LLM prompt reads the complete JD + candidate profile. Returns structured JSON: <strong style="color:#fff">0–100 score</strong>, missing skills, matched skills, and a human-readable justification shown in the dashboard.</p>
      <div style="margin-top:16px; font-family: var(--mono); font-size:11px; color: var(--text-muted); background: var(--surface2); padding:12px; border-radius:6px;">
        {"score": 82, "match": ["React","Node"],<br>
        "gap": ["Kubernetes"],<br>
        "reason": "Strong fit, missing infra exp"}
      </div>
    </div>
  </div>

  <h3 style="color:#fff; margin-bottom: 16px;">Threshold Logic — tuneable per candidate</h3>
  <div class="threshold-row">
    <div class="threshold-item t-green">
      <div class="t-badge">≥ 75</div>
      <div>
        <div class="t-action">Auto-Apply immediately</div>
        <p class="t-sub">Bot submits, tailors resume, writes cover letter — no human needed</p>
      </div>
    </div>
    <div class="threshold-item t-yellow">
      <div class="t-badge">55–74</div>
      <div>
        <div class="t-action">Send to Human Review Queue</div>
        <p class="t-sub">Candidate sees it in dashboard with score + justification — 1-click approve</p>
      </div>
    </div>
    <div class="threshold-item t-red">
      <div class="t-badge">&lt; 55</div>
      <div>
        <div class="t-action">Silently Skip</div>
        <p class="t-sub">Not shown to candidate. Logged only. Can be reviewed in archive tab.</p>
      </div>
    </div>
  </div>
  <p style="font-size:12px; color: var(--text-muted); margin-top:16px;">⚙ A recently laid-off candidate set at 60 threshold. A passive job seeker still employed — raise to 85. Thresholds are per-profile settings.</p>
</section>

<!-- PORTAL CONNECTIONS -->
<section>
  <div class="section-label">Portal Layer</div>
  <h2>How portal connections work</h2>
  <p style="max-width:640px; margin-bottom:32px;">Every portal connector exposes exactly two methods: <code style="font-family:var(--mono); color:var(--accent); font-size:12px;">search(keywords, filters) → [JobListing]</code> and <code style="font-family:var(--mono); color:var(--accent); font-size:12px;">apply(job_id, profile) → ApplicationResult</code>. The scoring engine above never sees Playwright or API keys. This abstraction is what makes the system maintainable.</p>

  <div class="portal-grid">
    <div class="portal-card pc-linkedin">
      <div class="portal-name">LinkedIn</div>
      <span class="portal-method method-api">Official API</span> <span class="portal-method method-playwright">Playwright (Easy Apply)</span>
      <p class="portal-note">Job search via official API. Easy Apply requires browser automation — LinkedIn deliberately blocks this. Needs realistic timing + per-candidate proxy IPs.</p>
    </div>
    <div class="portal-card pc-naukri">
      <div class="portal-name">Naukri</div>
      <span class="portal-method method-partner">Partner API</span>
      <p class="portal-note">Has a partner API for job search. Apply flow is partially API-driven. More predictable than LinkedIn. Good for Indian market targeting.</p>
    </div>
    <div class="portal-card pc-indeed">
      <div class="portal-name">Indeed</div>
      <span class="portal-method method-api">Publisher API</span> <span class="portal-method method-api">Apply API</span>
      <p class="portal-note">Separate publisher (search) and Apply APIs. Most reliable portal to integrate. Rate limits are generous for registered publishers.</p>
    </div>
    <div class="portal-card pc-glass">
      <div class="portal-name">Glassdoor</div>
      <span class="portal-method method-scrape">Scraping Only</span>
      <p class="portal-note">No public API. Requires Playwright. Glassdoor has aggressive bot detection — use stealth plugins, human-delay randomisation, and session cookie reuse.</p>
    </div>
    <div class="portal-card pc-ats">
      <div class="portal-name">Company ATS — Workday, Greenhouse, Lever, iCIMS, Taleo, SuccessFactors, SmartRecruiters</div>
      <span class="portal-method method-playwright">Selenium + AI</span>
      <p class="portal-note">7 ATS platforms supported. Universal multi-page form filler handles login/register walls, OTP email verification, dropdowns, radio buttons, checkboxes, cover letters, and unknown fields via Gemini AI resolver. Self-healing on validation errors.</p>
    </div>
  </div>
</section>

<!-- RESUME TAILORING -->
<section>
  <div class="section-label">AI Resume Engine</div>
  <h2>Resume tailoring — the feature<br>candidates love most</h2>
  <p style="max-width:640px; margin-bottom: 28px;">The bot never fires the same PDF twice. For every auto-apply, the AI generates a tailored version of the resume tuned to that specific job description — typically raising response rates by 15–25% over a static resume blast.</p>

  <div class="diff-view">
    <div class="diff-pane">
      <div class="diff-label before">❌ Before — Static Resume</div>
      <div class="diff-text">
        "Experienced software developer with <span class="removed">5+ years</span> of experience in various technologies. Worked on multiple projects involving <span class="removed">frontend and backend development</span>. Familiar with agile methodologies."
        <br><br>
        <strong style="color:#fff; font-size:11px;">Bullet order:</strong><br>
        <span class="removed">• Built internal CMS tool</span><br>
        • Led React migration<br>
        • Optimized Node.js APIs<br>
        • Managed AWS infra
      </div>
    </div>
    <div class="diff-pane">
      <div class="diff-label after">✓ After — AI Tailored for "Senior React Engineer at Fintech"</div>
      <div class="diff-text">
        "Senior frontend engineer specializing in <span class="hl">React</span> and <span class="hl">TypeScript</span> for <span class="hl">fintech</span> products. Built high-performance UIs handling <span class="hl">real-time data</span> and <span class="hl">regulatory compliance</span> constraints."
        <br><br>
        <strong style="color:#fff; font-size:11px;">Bullet order (reranked):</strong><br>
        <span class="hl">• Led React migration → 40% perf gain</span><br>
        <span class="hl">• Optimized Node.js APIs for 99.9% SLA</span><br>
        • Managed AWS infra<br>
        <span style="color: var(--text-muted); font-size:11px;">↑ CMS bullet suppressed — irrelevant</span>
      </div>
    </div>
  </div>

  <div style="margin-top:24px; display:flex; gap:16px; flex-wrap:wrap;">
    <div style="background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:16px 20px; flex:1; min-width:200px;">
      <div style="font-family:var(--mono); font-size:10px; color:var(--text-muted); text-transform:uppercase; margin-bottom:6px;">What AI rewrites</div>
      <div style="font-size:12px; color:var(--text-dim); line-height:1.8;">
        ✓ Resume summary / headline<br>
        ✓ Bullet point order (top 3 most relevant first)<br>
        ✓ ATS keyword injection from JD<br>
        ✓ 3-paragraph cover letter with company name + role context<br>
        ✓ Output: ATS-safe single-column PDF (no tables, no columns)
      </div>
    </div>
    <div style="background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:16px 20px; flex:1; min-width:200px;">
      <div style="font-family:var(--mono); font-size:10px; color:var(--text-muted); text-transform:uppercase; margin-bottom:6px;">ATS-safe output rules</div>
      <div style="font-size:12px; color:var(--text-dim); line-height:1.8;">
        ✓ Single-column layout only<br>
        ✓ No tables, no text boxes<br>
        ✓ Standard section headers<br>
        ✓ Machine-readable fonts (Arial, Calibri)<br>
        ✓ Passes Affinda + Sovren parsers
      </div>
    </div>
  </div>
</section>

<!-- APPLICATION TRACKING -->
<section>
  <div class="section-label">Tracking Layer</div>
  <h2>Application state machine —<br>where most bots fail</h2>
  <p style="max-width:640px; margin-bottom:24px;">Status tracking is what separates a toy from a tool. Every application has its own finite state machine. The bot advances state automatically using email triggers (IMAP regex on subject lines) and portal status APIs where available.</p>

  <div class="fsm">
    <div class="fsm-state s-applied">Applied</div>
    <div class="fsm-arrow">→</div>
    <div class="fsm-state s-viewed">Viewed</div>
    <div class="fsm-arrow">→</div>
    <div class="fsm-state s-short">Shortlisted</div>
    <div class="fsm-arrow">→</div>
    <div class="fsm-state s-interview">Interview</div>
    <div class="fsm-arrow">→</div>
    <div class="fsm-state s-offer">Offer 🎉</div>
    <div class="fsm-arrow">/</div>
    <div class="fsm-state s-rej">Rejected</div>
    <div class="fsm-arrow">/</div>
    <div class="fsm-state s-ghost">Ghosted</div>
  </div>

  <p style="font-size:13px; color:var(--text-dim); max-width:640px;">Email monitoring watches for subject line patterns like "interview invitation," "application viewed," "regret to inform" using regex. "Ghosted" state triggers automatically after 21 days with no response — no manual cleanup needed.</p>
</section>

<!-- HARD PROBLEMS -->
<section>
  <div class="section-label">Engineering Challenges</div>
  <h2>The hardest problems, ranked</h2>

  <div class="problems-grid">
    <div class="prob-card">
      <div class="prob-rank">1</div>
      <h3 style="color:var(--accent3);">Portal Anti-Scraping</h3>
      <p style="font-size:13px;">LinkedIn, Naukri, and Indeed all have bot detection. Standard Playwright fingerprints get blocked within hours.</p>
      <div class="prob-solve">
        <span class="s-label">How to solve</span>
        Realistic human timing randomisation in Playwright. Session cookie reuse (don't re-login every run). Per-candidate proxy IPs (not shared). Rate limiter that respects each portal's implicit limits. Use stealth plugins (puppeteer-extra-plugin-stealth).
      </div>
    </div>
    <div class="prob-card">
      <div class="prob-rank">2</div>
      <h3 style="color:var(--accent4);">ATS Form Parsing</h3>
      <p style="font-size:13px;">Workday alone has 12+ layout variants in the wild. Greenhouse, Lever, iCIMS all differ. These forms break without warning on portal updates.</p>
      <div class="prob-solve">
        <span class="s-label">How to solve</span>
        Build a parser per ATS variant. Store selectors in config (not hardcoded). Run a daily smoke-test job that tries a known form and alerts on failure. Accept that this will need ongoing maintenance — budget 20% of dev time for it.
      </div>
    </div>
    <div class="prob-card">
      <div class="prob-rank">3</div>
      <h3 style="color:var(--accent2);">ATS-safe PDF Generation</h3>
      <p style="font-size:13px;">Fancy two-column resumes with tables and text boxes fail Affinda and Sovren parsers. Skills get scrambled, name gets placed wrong.</p>
      <div class="prob-solve">
        <span class="s-label">How to solve</span>
        Single-column layout only. No tables, no text boxes. Standard section headers only. Machine-readable fonts (Arial, Calibri). Use a PDF library that produces clean linearised output — test every template against Affinda before shipping.
      </div>
    </div>
  </div>
</section>

<!-- TECH STACK -->
<section>
  <div class="section-label">Tech Stack</div>
  <h2>What you actually build with</h2>

  <div class="stack-grid">
    <div class="stack-card">
      <div class="stack-layer">Backend / Core</div>
      <div class="stack-items">
        <span class="stack-tag">Node.js</span>
        <span class="stack-tag">Python (FastAPI)</span>
        <span class="stack-tag">Bull (job queue)</span>
        <span class="stack-tag">Redis</span>
      </div>
    </div>
    <div class="stack-card">
      <div class="stack-layer">AI / Scoring</div>
      <div class="stack-items">
        <span class="stack-tag">OpenAI ada-002</span>
        <span class="stack-tag">GPT-4o / Claude</span>
        <span class="stack-tag">Pinecone / pgvector</span>
      </div>
    </div>
    <div class="stack-card">
      <div class="stack-layer">Browser Automation</div>
      <div class="stack-items">
        <span class="stack-tag">Playwright</span>
        <span class="stack-tag">stealth plugin</span>
        <span class="stack-tag">BrowserBase / Proxies</span>
      </div>
    </div>
    <div class="stack-card">
      <div class="stack-layer">Database</div>
      <div class="stack-items">
        <span class="stack-tag">PostgreSQL</span>
        <span class="stack-tag">Supabase</span>
        <span class="stack-tag">pgvector</span>
      </div>
    </div>
    <div class="stack-card">
      <div class="stack-layer">Email Monitoring</div>
      <div class="stack-items">
        <span class="stack-tag">IMAP (node-imap)</span>
        <span class="stack-tag">Gmail API</span>
        <span class="stack-tag">Regex FSM triggers</span>
      </div>
    </div>
    <div class="stack-card">
      <div class="stack-layer">PDF Generation</div>
      <div class="stack-items">
        <span class="stack-tag">Puppeteer PDF</span>
        <span class="stack-tag">PDFKit</span>
        <span class="stack-tag">Affinda (ATS test)</span>
      </div>
    </div>
    <div class="stack-card">
      <div class="stack-layer">Frontend Dashboard</div>
      <div class="stack-items">
        <span class="stack-tag">React</span>
        <span class="stack-tag">Tailwind</span>
        <span class="stack-tag">React Query</span>
        <span class="stack-tag">Recharts</span>
      </div>
    </div>
    <div class="stack-card">
      <div class="stack-layer">Auth / Licensing</div>
      <div class="stack-items">
        <span class="stack-tag">Supabase Auth</span>
        <span class="stack-tag">Edge Functions</span>
        <span class="stack-tag">License keys</span>
      </div>
    </div>
  </div>
</section>

<!-- IMPLEMENTATION PLAN -->
<section>
  <div class="section-label">16-Week Implementation Plan</div>
  <h2>Build order — the right way,<br>not the fast way</h2>
  <p style="max-width:640px; margin-bottom:40px; font-size:14px; color:var(--text-dim);">Do <strong style="color:#fff">not</strong> start with the auto-apply engine. Start with the tracking dashboard and manual apply flow. Automation built on a broken UX buries problems. Get 5 beta users applying manually first, watch where they struggle, fix it, then turn on automation.</p>

  <div class="timeline">
    <div class="tl-phase tl-p1">
      <div class="tl-dot"></div>
      <div class="tl-weeks">Weeks 1–4</div>
      <div class="tl-title">Foundation — Data Model + Manual Flow</div>
      <p style="font-size:13px; color:var(--text-dim); max-width:600px;">Build the dashboard and manual apply flow first. Validate the data model before automating anything. This is what 30 years teaches you — automation built on wrong data model = months of rework.</p>
      <div class="tl-items">
        <span class="tl-item">DB schema (applications, jobs, candidates, FSM)</span>
        <span class="tl-item">Candidate profile + resume parser</span>
        <span class="tl-item">Job Feed UI (manual search)</span>
        <span class="tl-item">Kanban tracker (manual state)</span>
        <span class="tl-item">Email connection (IMAP)</span>
        <span class="tl-item">5 beta users, manual apply</span>
      </div>
    </div>

    <div class="tl-phase tl-p2">
      <div class="tl-dot"></div>
      <div class="tl-weeks">Weeks 5–9</div>
      <div class="tl-title">Intelligence Layer — AI Scoring + Resume Engine</div>
      <p style="font-size:13px; color:var(--text-dim); max-width:600px;">Add AI only after the UI is validated. Build the two-stage scorer, resume tailoring, and cover letter generator. Tune threshold</p>
      <div class="tl-items">
        <span class="tl-item">Embedding cosine matching</span>
        <span class="tl-item">LLM detailed match report</span>
        <span class="tl-item">ATS profile keyword injection</span>
        <span class="tl-item">Linear PDF format exporter</span>
        <span class="tl-item">STAR question mock builder</span>
      </div>
    </div>
  </div>
</section>

<!-- FOOTER -->
<div class="footer">
  🤖 SENIOR ENGINEER BLUEPRINT DASHBOARD © 2026. RUNNING WITH MAXIMUM EFFICIENCY.
</div>

<div id="toast-container"></div>

<script>
const DAILY_LIMIT = {{ daily_limit }};
let activeLogFilter = 'all';
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
const consoleBox = document.getElementById('console');
const evtSrc = new EventSource('/stream');

evtSrc.onmessage = e => {
    if (!e.data || e.data.trim() === "") return;
    try {
        const payload = JSON.parse(e.data);
        allLogs.push(payload);
        
        if (allLogs.length > 500) {
            allLogs.shift();
        }
        renderLogs();
    } catch(err) {
        const textPayload = {type: "info", message: e.data, time: new Date().toLocaleTimeString()};
        allLogs.push(textPayload);
        renderLogs();
    }
};

function renderLogs() {
    consoleBox.innerHTML = '';
    const filtered = allLogs.filter(log => {
        if (activeLogFilter === 'all') return true;
        return log.type === activeLogFilter;
    });
    
    if (filtered.length === 0) {
        consoleBox.innerHTML = '<div class="log-line"><span class="log-time">-</span><span class="log-text" style="color:var(--text-muted)">No filtered action logs available.</span></div>';
        return;
    }
    
    filtered.forEach(log => {
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
        consoleBox.appendChild(line);
    });
    consoleBox.scrollTop = consoleBox.scrollHeight;
}

function setFilter(filterType) {
    document.querySelectorAll('.log-tab').forEach(tab => {
        tab.classList.remove('active', 'active-all', 'active-success', 'active-warn', 'active-error');
        const text = tab.textContent.toLowerCase().trim();
        if (text === filterType || (filterType === 'warn' && text === 'warnings') || (filterType === 'error' && text === 'errors')) {
            if (filterType === 'all') tab.classList.add('active-all');
            else if (filterType === 'success') tab.classList.add('active-success');
            else if (filterType === 'warn') tab.classList.add('active-warn');
            else if (filterType === 'error') tab.classList.add('active-error');
        }
    });
    activeLogFilter = filterType;
    renderLogs();
}

function clearLogs() {
    allLogs = [];
    renderLogs();
    showToast("Console cleared.");
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
        
        jobs.forEach(job => {
            const tr = document.createElement('tr');
            
            let scoreColor = 'var(--text-muted)';
            if (job.score >= 70) scoreColor = '#00ff66';
            else if (job.score >= 50) scoreColor = '#ffcc00';
            else scoreColor = '#ff3333';
            
            tr.innerHTML = `
                <td><strong style="color:var(--accent2);">${job.portal}</strong></td>
                <td><strong>${job.company}</strong></td>
                <td>${job.title}</td>
                <td>${job.location}</td>
                <td style="color:${scoreColor}; font-weight:bold;">${job.score}%</td>
                <td>
                    <div style="display:flex; gap:6px;">
                        <a href="${job.url}" target="_blank" class="mock-btn mock-btn-outline" style="padding:4px 8px; font-size:11px; text-decoration:none; display:inline-block;">🔗 Open</a>
                        <button class="mock-btn" onclick="assistApply('${encodeURIComponent(job.url)}', '${encodeURIComponent(job.company)}', '${encodeURIComponent(job.title)}')" style="padding:4px 8px; font-size:11px; margin:0; background:rgba(0, 150, 255, 0.15); color:#33adff; border-color:rgba(0, 150, 255, 0.3);">🧑‍💻 Assist</button>
                        <button class="mock-btn" onclick="autoApplySingle('${encodeURIComponent(job.url)}', '${encodeURIComponent(job.company)}', '${encodeURIComponent(job.title)}', '${encodeURIComponent(job.portal)}')" style="padding:4px 8px; font-size:11px; margin:0; background:#006622; color:#fff; border-color:#00802b;">🚀 Auto Apply</button>
                    </div>
                </td>
            `;
            tb.appendChild(tr);
        });
    } catch (e) {
        console.error("Error refreshing targeted results:", e);
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
        showToast("Opened application page in browser! Complete the steps manually.");
    } else {
        showToast("Error: " + (d.error || "Failed to start assist session"));
    }
}

async function autoApplySingle(urlEnc, compEnc, titleEnc, portalEnc) {
    const url = decodeURIComponent(urlEnc);
    const company = decodeURIComponent(compEnc);
    const role = decodeURIComponent(titleEnc);
    const portal = decodeURIComponent(portalEnc);
    
    showToast(`Starting background auto-apply to ${company}...`);
    const res = await fetch('/api/approve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, company, role, portal })
    });
    const d = await res.json();
    if (d.ok) {
        showToast("Application scheduled successfully!");
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
        tb.innerHTML = '<tr><td colspan="7" style="text-align:center; color:var(--text-muted)">No logged application runs found.</td></tr>';
        return;
    }
    
    // Sort rows: newest first
    rows.slice(0, 100).forEach(row => {
        const tr = document.createElement('tr');
        const statusClass = row.Status === 'Applied' ? 'applied' : (row.Status === 'Skipped' ? 'skipped' : 'manual');
        const companyDisplay = row.URL
            ? `<a href="${row.URL}" target="_blank" style="color:#fff; text-decoration:none; font-weight:600;" title="Open job listing">${row.Company} ↗</a>`
            : `<span style="font-weight:600; color:#fff">${row.Company}</span>`;
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
    const company = document.getElementById('target-company-input').value.trim();
    const skills = document.getElementById('target-skills-input').value.trim();
    const location = document.getElementById('target-location-input').value.trim();
    
    if (!company || !skills || !location) {
        showToast("⚠️ Please fill in all fields (Company, Skills, and Location) for Targeted Search!");
        return;
    }
    
    const headless = document.getElementById('headless-checkbox').checked;
    const maxApps = parseInt(document.getElementById('max-apps-input').value) || 15;
    
    const res = await fetch('/api/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
            target: 'targeted', 
            headless, 
            max_applications: maxApps,
            company,
            skills,
            location
        })
    });
    
    const d = await res.json();
    if (d.error) {
        showToast(`Error: ${d.error}`);
    } else {
        _botRunning = true;
        showToast(`🚀 Targeted Search started for ${company}! Launching Chrome...`);
    }
    refreshStats();
}

async function runRecruiterScraper() {
    if (_botRunning) {
        showToast("Bot is already running! Please wait...");
        return;
    }
    const company = document.getElementById('target-company-input').value.trim();
    const skills = document.getElementById('target-skills-input').value.trim();
    const location = document.getElementById('target-location-input').value.trim();
    
    if (!company || !skills || !location) {
        showToast("⚠️ Please fill in all fields (Company, Skills, and Location) for Recruiter Post Scraper!");
        return;
    }
    
    const headless = document.getElementById('headless-checkbox').checked;
    
    const res = await fetch('/api/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
            target: 'recruiter_posts', 
            headless,
            company,
            skills,
            location
        })
    });
    
    const d = await res.json();
    if (d.error) {
        showToast(`Error: ${d.error}`);
    } else {
        _botRunning = true;
        showToast(`🔍 Recruiter Post & Form Scraper started! Check console logs below.`);
    }
    refreshStats();
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
        imap_password: document.getElementById('cfg-imap_password').value.trim()
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
    
    const labels = ['Scanned', 'Applied', 'Interview Invite', 'Offers Received'];
    const values = [
        data.Scanned || 0,
        data.Applied || 0,
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
                    'rgba(142, 142, 147, 0.45)',
                    'rgba(79, 140, 255, 0.6)',
                    'rgba(255, 179, 0, 0.65)',
                    'rgba(74, 222, 128, 0.75)'
                ],
                borderColor: [
                    'rgba(142, 142, 147, 1)',
                    'rgba(79, 140, 255, 1)',
                    'rgba(255, 179, 0, 1)',
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
            tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; color:var(--text-muted); padding:12px;">No job applications tracked yet.</td></tr>';
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
            
            tr.innerHTML = `
                <td style="padding:8px; font-weight:600;">${companyDisplay}</td>
                <td style="padding:8px; color:var(--accent2); max-width:200px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${row.Role || ''}</td>
                <td style="padding:8px;"><span style="font-family:var(--mono); font-size:10px; background:rgba(79,140,255,0.1); padding:2px 7px; border-radius:4px; color:var(--accent2)">${row.Portal || ''}</span></td>
                <td style="padding:8px; font-family:var(--mono); font-size:12px;">${row['Match %'] || ''}</td>
                <td style="padding:8px; font-size:0.75rem; color:var(--text-muted);">${row.Date || ''}</td>
                <td style="padding:8px;">${selectHtml}</td>
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
</script>
</body>
</html>
"""

# ── Flask routes ────────────────────────────────────────────────────
@app.route("/")
def index():
    import importlib
    import config.profile
    try:
        importlib.reload(config.profile)
        from config.profile import DAILY_LIMIT, SCHEDULED_RUNS, HEADLESS_DEFAULT
    except Exception:
        from config.profile import DAILY_LIMIT, SCHEDULED_RUNS
        HEADLESS_DEFAULT = True
    return render_template_string(TEMPLATE,
                                  daily_limit=DAILY_LIMIT,
                                  sched_runs=SCHEDULED_RUNS,
                                  headless_default=HEADLESS_DEFAULT)

@app.route("/stream")
def stream():
    def generate():
        while True:
            msg = _log_q.get()      # blocks until new log line
            yield msg
    return Response(stream_with_context(generate()), mimetype="text/event-stream")

@app.route("/api/stats")
def api_stats():
    return jsonify({
        "applied": get_today_count("Applied"),
        "skipped": get_today_count("Skipped"),
        "manual":  get_today_count("Manual Needed"),
        "total":   get_today_count(),
        "running": _bot_thread is not None and _bot_thread.is_alive(),
    })

@app.route("/api/applications")
def api_applications():
    return jsonify(get_all_rows())

@app.route("/api/analytics")
def api_analytics():
    from tracker import get_fsm_summary, get_all_rows
    summary = get_fsm_summary()
    all_rows = get_all_rows()
    total_scanned = len(all_rows)
    
    return jsonify({
        "Scanned": total_scanned,
        "Skipped": summary.get("Skipped", 0),
        "Manual": summary.get("Manual Needed", 0),
        "Applied": summary.get("Applied", 0),
        "Viewed": summary.get("Viewed", 0),
        "Shortlisted": summary.get("Shortlisted", 0),
        "Interview": summary.get("Interview", 0),
        "Offer": summary.get("Offer", 0),
        "Rejected": summary.get("Rejected", 0),
        "Ghosted": summary.get("Ghosted", 0)
    })

@app.route("/api/applications/status", methods=["POST"])
def api_applications_status():
    from tracker import update_status, VALID_STATUSES
    data = request.get_json()
    if not data or "url" not in data or "new_status" not in data:
        return jsonify({"success": False, "error": "Missing url or new_status"}), 400
    
    url = data["url"]
    new_status = data["new_status"]
    
    if new_status not in VALID_STATUSES:
        return jsonify({"success": False, "error": f"Invalid status: {new_status}"}), 400
        
    updated = update_status(url, new_status)
    if updated:
        return jsonify({"success": True})
    else:
        return jsonify({"success": False, "error": "Application not found or status not changed"}), 404

@app.route("/api/qa")
def api_qa():
    return jsonify(get_unanswered())

@app.route("/api/qa/all")
def api_qa_all():
    return jsonify(qa_get_all())

@app.route("/api/qa/update", methods=["POST"])
def api_qa_update():
    data = request.get_json()
    save_question_settings(data["question"], data.get("answer", ""), data.get("mode", "auto"))
    return jsonify({"ok": True})

@app.route("/api/qa/delete", methods=["POST"])
def api_qa_delete():
    data = request.get_json()
    delete_entry(data["question"])
    return jsonify({"ok": True})

@app.route("/api/qa/answer", methods=["POST"])
def api_qa_answer():
    data = request.get_json()
    save_answer(data["question"], data["answer"])
    return jsonify({"ok": True})

def run_targeted_search_flow(company, skills, location, max_apps, headless, log_fn, stop_event):
    global TARGETED_SEARCH_RESULTS
    TARGETED_SEARCH_RESULTS.clear()
    
    log_fn(f"\n[TARGETED SEARCH] Starting unified targeted search for Company: {company}, Skills: {skills}, Location: {location}")
    log_fn("[TARGETED SEARCH] Searching across all networks (Direct API, LinkedIn, Naukri)...")
    
    discovered_raw = []
    
    # 1. PwC API Search
    if company.lower() == "pwc":
        log_fn("  - Querying PwC Workday API directly...")
        SITE_IDS = ["Global_Experienced_Careers", "Catalyst"]
        search_terms = [s.strip() for s in skills.replace("/", ",").split(",") if s.strip()]
        search_text = search_terms[0] if search_terms else "AWS"
        payload = {"appliedFacets": {}, "limit": 30, "offset": 0, "searchText": search_text}
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Referer": "https://pwc.wd3.myworkdayjobs.com/",
        }
        for site in SITE_IDS:
            if stop_event.is_set(): break
            url = f"https://pwc.wd3.myworkdayjobs.com/wday/cxs/pwc/{site}/jobs"
            try:
                import requests
                r = requests.post(url, json=payload, headers=headers, timeout=10)
                if r.status_code == 200:
                    jobs = r.json().get("jobPostings", [])
                    for j in jobs:
                        title = j.get("title", "")
                        path = j.get("externalPath", "")
                        locs = j.get("locationsText", "")
                        if isinstance(locs, list) and locs:
                            if isinstance(locs[0], dict):
                                loc_str = ", ".join([l.get("descriptor", "") for l in locs])
                            else:
                                loc_str = ", ".join([str(l) for l in locs])
                        else:
                            loc_str = str(locs)
                        full_url = f"https://pwc.wd3.myworkdayjobs.com/en-US/{site}{path}"
                        discovered_raw.append({
                            "company": "PwC",
                            "title": title,
                            "url": full_url,
                            "location": loc_str,
                            "portal": "PwC Workday"
                        })
            except Exception as e:
                log_fn(f"    [WARN] PwC API error for {site}: {e}")
                
    # 2. LinkedIn Job Search
    if not stop_event.is_set():
        log_fn("  - Scanning LinkedIn Job Listings...")
        try:
            from browser import create_browser
            from selenium.webdriver.common.by import By
            driver = create_browser(headless=headless, profile_name="linkedin")
            from linkedin_bot import login as linkedin_login, search_jobs, get_job_cards
            if linkedin_login(driver, log_fn=log_fn):
                keyword_query = f"{company} {skills}".strip()
                search_jobs(driver, keyword_query, location, log_fn=log_fn)
                cards = get_job_cards(driver)
                log_fn(f"    Discovered {len(cards)} listings on LinkedIn.")
                for card in cards[:12]:
                    if stop_event.is_set(): break
                    try:
                        link_el = card.find_element(By.CSS_SELECTOR, ".job-card-list__title, a.job-card-container__link")
                        href = link_el.get_attribute("href").split("?")[0]
                        title = link_el.text.strip()
                        comp_el = card.find_element(By.CSS_SELECTOR, ".job-card-container__primary-description, .job-card-container__company-name, .artdeco-entity-lockup__subtitle")
                        comp = comp_el.text.strip()
                        loc_el = card.find_element(By.CSS_SELECTOR, ".job-card-container__metadata-item")
                        loc = loc_el.text.strip()
                        discovered_raw.append({
                            "company": comp,
                            "title": title,
                            "url": href,
                            "location": loc,
                            "portal": "LinkedIn"
                        })
                    except Exception:
                        pass
        except Exception as e:
            log_fn(f"    [WARN] LinkedIn scan error: {e}")
        finally:
            try: driver.quit()
            except Exception: pass

    # 3. Naukri Job Search
    if not stop_event.is_set():
        log_fn("  - Scanning Naukri Job Listings...")
        try:
            from browser import create_browser
            driver = create_browser(headless=headless, profile_name="naukri")
            from naukri_bot import login as naukri_login, search_jobs, get_job_listings, extract_card_metadata_naukri
            if naukri_login(driver, log_fn=log_fn):
                keyword_query = f"{company} {skills}".strip()
                search_jobs(driver, keyword_query, location, log_fn=log_fn)
                cards = get_job_listings(driver)
                log_fn(f"    Discovered {len(cards)} listings on Naukri.")
                for card in cards[:12]:
                    if stop_event.is_set(): break
                    try:
                        job_id, title, comp, href, posted = extract_card_metadata_naukri(card)
                        if href:
                            discovered_raw.append({
                                "company": comp,
                                "title": title,
                                "url": href,
                                "location": location,
                                "portal": "Naukri"
                            })
                    except Exception:
                        pass
        except Exception as e:
            log_fn(f"    [WARN] Naukri scan error: {e}")
        finally:
            try: driver.quit()
            except Exception: pass

    # Filter duplicates and evaluate with Gemini Suitability
    log_fn(f"\n[TARGETED SEARCH] Collating and filtering {len(discovered_raw)} total raw job posts...")
    seen_urls = set()
    target_locations = [l.strip().lower() for l in location.replace("/", ",").split(",") if l.strip()]
    
    from filter import should_apply
    for job in discovered_raw:
        if stop_event.is_set(): break
        url = job["url"]
        if url in seen_urls: continue
        seen_urls.add(url)
        
        # Location filter check
        if target_locations:
            loc_lower = job["location"].lower()
            if not any(t in loc_lower for t in target_locations):
                continue
                
        # AI evaluation
        apply, score, matched, reason, decision, missing = should_apply(job["title"], job["title"], job["company"])
        
        TARGETED_SEARCH_RESULTS.append({
            "company": job["company"],
            "title": job["title"],
            "url": job["url"],
            "location": job["location"],
            "portal": job["portal"],
            "score": score,
            "decision": decision,
            "reason": reason,
            "matched": matched,
            "missing": missing
        })
        
    log_fn(f"[OK] Discovered and scored {len(TARGETED_SEARCH_RESULTS)} unique matching jobs. Review them in the new 'Targeted Results' panel on the page!")


def run_recruiter_scraper_flow(company, skills, location, log_fn, stop_event):
    log_fn(f"\n[RECRUITER SCANNER] Starting recruiter post scan for Company: {company}, Skills: {skills}, Location: {location}")
    from browser import create_browser
    from selenium.webdriver.common.by import By
    import requests.utils
    import time
    
    log_fn("[RECRUITER SCANNER] Launching Chrome browser with LinkedIn session...")
    try:
        driver = create_browser(headless=False, profile_name="linkedin")
    except Exception as e:
        log_fn(f"[ERROR] Failed to launch Chrome: {e}")
        return
        
    try:
        log_fn("[RECRUITER SCANNER] Checking session status on LinkedIn...")
        driver.get("https://www.linkedin.com")
        time.sleep(5)
        
        if "feed" not in driver.current_url and "mynetwork" not in driver.current_url:
            log_fn("[RECRUITER SCANNER] Not logged in. Logging in via credentials...")
            driver.get("https://www.linkedin.com/login")
            time.sleep(5)
            
            from config.profile import PROFILE
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            
            username_el = WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.ID, "username"))
            )
            username_el.send_keys(PROFILE["linkedin_email"])
            driver.find_element(By.ID, "password").send_keys(PROFILE["linkedin_password"])
            driver.find_element(By.XPATH, "//button[@type='submit']").click()
            
            for _ in range(12):
                if stop_event.is_set(): break
                if "feed" in driver.current_url or "mynetwork" in driver.current_url:
                    log_fn("[OK] Logged in successfully!")
                    break
                time.sleep(5)
        else:
            log_fn("[OK] Already logged in via persistent session!")
            
        if stop_event.is_set(): return
        
        query = f'"{company}" "{skills}" "hiring" "{location}"'
        log_fn(f"[RECRUITER SCANNER] Searching posts for query: {query}")
        search_url = f"https://www.linkedin.com/search/results/content/?keywords={requests.utils.quote(query)}&origin=GLOBAL_SEARCH_HEADER&sortBy=date_posted"
        driver.get(search_url)
        time.sleep(6)
        
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(3)
        
        posts = driver.find_elements(By.CSS_SELECTOR, ".update-components-text, .feed-shared-update-v2")
        log_fn(f"[RECRUITER SCANNER] Found {len(posts)} posts. Scanning for form links...")
        
        found_any = False
        for idx, post in enumerate(posts[:10]):
            if stop_event.is_set(): break
            try:
                text = post.text
                log_fn(f"\n--- Post #{idx+1} ---")
                log_fn(text[:150] + "...")
                
                links = post.find_elements(By.TAG_NAME, "a")
                found_links = []
                for link in links:
                    href = link.get_attribute("href") or ""
                    if "docs.google.com/forms" in href or "forms.gle" in href or "forms.office.com" in href:
                        log_fn(f"🎯 🎯 🎯 FOUND RECRUITER FORM: {href}")
                        found_links.append(href)
                        found_any = True
                        
                if found_links:
                    os.makedirs("logs", exist_ok=True)
                    with open("logs/recruiter_leads.txt", "a", encoding="utf-8") as f:
                        f.write(f"Date: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Company: {company} | Post Text Snippet: {text[:100]} | Links: {found_links}\n")
            except Exception as e:
                pass
                
        if not found_any:
            log_fn("[RECRUITER SCANNER] No recruiter google forms found in the matching posts.")
            
    except Exception as e:
        log_fn(f"[ERROR] Error during recruiter post scan: {e}")
    finally:
        log_fn("[RECRUITER SCANNER] Recruiter scanner completed.")
        try:
            driver.quit()
        except Exception:
            pass


@app.route("/api/run", methods=["POST"])
def api_run():
    global _bot_thread
    if _bot_thread and _bot_thread.is_alive():
        return jsonify({"error": "Bot already running"}), 409
    
    # Reload profile variables before running so settings are dynamically updated
    try:
        import importlib
        import config.profile
        import filter
        import linkedin_bot
        import naukri_bot
        import indeed_bot
        importlib.reload(config.profile)
        importlib.reload(filter)
        importlib.reload(linkedin_bot)
        importlib.reload(naukri_bot)
        importlib.reload(indeed_bot)
    except Exception as re:
        bot_log(f"[WARN] Module reload warning: {re}")
        
    STOP_EVENT.clear()
    data = request.get_json() or {}
    target = data.get("target", "all")
    headless = data.get("headless", False)
    max_apps = data.get("max_applications", 15)
    
    # Targeted search parameters
    company = data.get("company", "").strip()
    skills = data.get("skills", "").strip()
    location = data.get("location", "").strip()

    def _run():
        try:
            if target == "targeted":
                run_targeted_search_flow(company, skills, location, max_apps, headless, log_fn=bot_log, stop_event=STOP_EVENT)
            elif target == "recruiter_posts":
                run_recruiter_scraper_flow(company, skills, location, log_fn=bot_log, stop_event=STOP_EVENT)
            else:
                if target in ("linkedin", "all"):
                    from linkedin_bot import run_linkedin_bot
                    run_linkedin_bot(max_applications=max_apps, headless=headless, log_fn=bot_log, stop_event=STOP_EVENT)
                if not STOP_EVENT.is_set() and target in ("naukri", "all"):
                    from naukri_bot import run_naukri_bot
                    run_naukri_bot(max_applications=max_apps, headless=headless, log_fn=bot_log, stop_event=STOP_EVENT)
                if not STOP_EVENT.is_set() and target in ("indeed", "all"):
                    from indeed_bot import run_indeed_bot
                    run_indeed_bot(max_applications=max_apps, headless=headless, log_fn=bot_log, stop_event=STOP_EVENT)
        except Exception as e:
            import traceback
            err_msg = traceback.format_exc()
            bot_log(f"[ERROR] Bot run crashed with exception: {e}\nTraceback:\n{err_msg}")

    _bot_thread = threading.Thread(target=_run, daemon=True)
    _bot_thread.start()
    return jsonify({"ok": True})

@app.route("/api/stop", methods=["POST"])
def api_stop():
    STOP_EVENT.set()
    bot_log("[STOP] Stop signal received. Halting bot operations gracefully.")
    return jsonify({"ok": True, "note": "Stop signal sent."})

@app.route("/api/review_queue")
def api_review_queue():
    from tracker import get_review_queue
    return jsonify(get_review_queue())

@app.route("/api/approve", methods=["POST"])
def api_approve():
    data = request.get_json() or {}
    url = data.get("url", "")
    if not url:
        return jsonify({"ok": False, "error": "No URL provided"}), 400
    
    from tracker import get_all_rows, approve_review_job
    company = "Company"
    role = "Role"
    for row in get_all_rows():
        if row.get("URL") == url:
            company = row.get("Company", "Company")
            role = row.get("Role", "Role")
            break
            
    ok = approve_review_job(url)
    if not ok:
        return jsonify({"ok": False, "error": "Job not found in review queue"}), 404
        
    # Spawn background thread to actually apply using careers_bot
    def run_approved_apply():
        from browser import create_browser
        from tracker import update_status
        from selenium.webdriver.common.by import By
        import time
        bot_log(f"\n[APPROVE APPLY] Starting auto-application for {company} -- {role}...")
        bot_log(f"  URL: {url}")
        
        driver = None
        try:
            import config.profile
            headless = getattr(config.profile, "HEADLESS_DEFAULT", True)
            
            url_lower = url.lower()
            if "linkedin.com" in url_lower:
                bot_log("  [PORTAL DETECT] LinkedIn Easy Apply detected.")
                driver = create_browser(headless=headless, profile_name="linkedin")
                from linkedin_bot import login as linkedin_login, fill_easy_apply_form
                linkedin_login(driver, log_fn=bot_log)
                driver.get(url)
                time.sleep(3)
                try:
                    desc = driver.find_element(By.TAG_NAME, "body").text
                except Exception:
                    desc = ""
                success = fill_easy_apply_form(driver, job_description=desc, company=company, role=role, log_fn=bot_log)
            elif "naukri.com" in url_lower:
                bot_log("  [PORTAL DETECT] Naukri Apply detected.")
                driver = create_browser(headless=headless, profile_name="naukri")
                from naukri_bot import login as naukri_login, apply_naukri
                naukri_login(driver, log_fn=bot_log)
                driver.get(url)
                time.sleep(3)
                success = apply_naukri(driver, log_fn=bot_log, company=company, role=role)
            else:
                bot_log("  [PORTAL DETECT] Careers/ATS/Redirect Page detected.")
                driver = create_browser(headless=headless, profile_name="approve_apply")
                driver.get(url)
                time.sleep(4)
                current_url = driver.current_url
                bot_log(f"  Loaded URL: {current_url}")
                from careers_bot import apply_to_career_site
                success = apply_to_career_site(driver, current_url, company=company, role=role)

            if success:
                bot_log(f"  [SUCCESS] Applied to '{role}' at '{company}'!")
                update_status(url, "Applied")
            else:
                bot_log(f"  [FAIL] Could not complete apply for '{role}' at '{company}'")
                update_status(url, "Manual Needed")
        except Exception as ex:
            bot_log(f"  [ERROR] Auto-application failed: {ex}")
            update_status(url, "Manual Needed")
        finally:
            if driver:
                driver.quit()
                
    import threading
    t = threading.Thread(target=run_approved_apply, daemon=True)
    t.start()
    return jsonify({"ok": True, "message": "Approved and auto-application started."})

@app.route("/api/reject", methods=["POST"])
def api_reject():
    data = request.get_json() or {}
    url = data.get("url", "")
    if not url:
        return jsonify({"ok": False, "error": "No URL provided"}), 400
    from tracker import reject_review_job
    ok = reject_review_job(url)
    return jsonify({"ok": ok})

@app.route("/api/review/bulk_approve", methods=["POST"])
def api_review_bulk_approve():
    data = request.get_json() or {}
    min_score = data.get("min_score")
    if min_score is not None:
        try:
            min_score = float(min_score)
        except ValueError:
            min_score = None
            
    from tracker import get_review_queue, approve_review_job
    review_jobs = get_review_queue()
    
    approved_count = 0
    import threading
    
    def run_approved_apply_bg(url, company, role):
        from browser import create_browser
        from tracker import update_status
        from selenium.webdriver.common.by import By
        import time
        import config.profile
        
        bot_log(f"\n[APPROVE APPLY] Starting auto-application for {company} -- {role}...")
        driver = None
        try:
            headless = getattr(config.profile, "HEADLESS_DEFAULT", True)
            url_lower = url.lower()
            if "linkedin.com" in url_lower:
                driver = create_browser(headless=headless, profile_name="linkedin")
                from linkedin_bot import login as linkedin_login, fill_easy_apply_form
                linkedin_login(driver, log_fn=bot_log)
                driver.get(url)
                time.sleep(3)
                try:
                    desc = driver.find_element(By.TAG_NAME, "body").text
                except Exception:
                    desc = ""
                success = fill_easy_apply_form(driver, job_description=desc, company=company, role=role, log_fn=bot_log)
            elif "naukri.com" in url_lower:
                driver = create_browser(headless=headless, profile_name="naukri")
                from naukri_bot import login as naukri_login, apply_naukri
                naukri_login(driver, log_fn=bot_log)
                driver.get(url)
                time.sleep(3)
                success = apply_naukri(driver, log_fn=bot_log, company=company, role=role)
            else:
                driver = create_browser(headless=headless, profile_name="approve_apply")
                driver.get(url)
                time.sleep(4)
                from careers_bot import apply_to_career_site
                success = apply_to_career_site(driver, driver.current_url, company=company, role=role)

            if success:
                bot_log(f"  [SUCCESS] Applied to '{role}' at '{company}'!")
                update_status(url, "Applied")
            else:
                bot_log(f"  [FAIL] Could not complete apply for '{role}' at '{company}'")
                update_status(url, "Manual Needed")
        except Exception as ex:
            bot_log(f"  [ERROR] Auto-application failed: {ex}")
            update_status(url, "Manual Needed")
        finally:
            if driver:
                driver.quit()

    for job in review_jobs:
        score = job.get("Score", 0)
        url = job.get("URL", "")
        company = job.get("Company", "Company")
        role = job.get("Role", "Role")
        
        if min_score is not None and score < min_score:
            continue
            
        ok = approve_review_job(url)
        if ok:
            approved_count += 1
            # Run sequential launch delayed start to avoid selenium thread crash
            time.sleep(1)
            threading.Thread(target=run_approved_apply_bg, args=(url, company, role), daemon=True).start()
            
    return jsonify({"ok": True, "count": approved_count})

@app.route("/api/review/bulk_reject", methods=["POST"])
def api_review_bulk_reject():
    from tracker import get_review_queue, reject_review_job
    review_jobs = get_review_queue()
    rejected_count = 0
    for job in review_jobs:
        url = job.get("URL", "")
        if reject_review_job(url):
            rejected_count += 1
    return jsonify({"ok": True, "count": rejected_count})

@app.route("/api/export-csv")
def api_export_csv():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    tracker_path = os.path.join(script_dir, TRACKER_FILE)
    if os.path.exists(tracker_path):
        return send_file(tracker_path, as_attachment=True, download_name="job_applications.csv")
    return jsonify({"error": "Tracker file not found"}), 404

@app.route("/api/profile", methods=["GET", "POST"])
def api_profile_settings():
    profile_path = "config/profile.py"
    if request.method == "GET":
        try:
            import importlib
            import config.profile
            importlib.reload(config.profile)
            
            # Extract lists/dicts
            from config.profile import PROFILE, MY_SKILLS, SEARCH_KEYWORDS, SEARCH_LOCATIONS, TARGET_COMPANIES, COVER_LETTER, MIN_MATCH_SCORE, DAILY_LIMIT
            company_credentials = getattr(config.profile, "COMPANY_CREDENTIALS", {})
            tech_experience = getattr(config.profile, "TECH_EXPERIENCE", {})
            gemini_api_key = getattr(config.profile, "GEMINI_API_KEY", "")
            auto_threshold = getattr(config.profile, "AUTO_THRESHOLD", 75)
            review_threshold = getattr(config.profile, "REVIEW_THRESHOLD", 55)
            imap_host = getattr(config.profile, "IMAP_HOST", "imap.gmail.com")
            imap_email = getattr(config.profile, "IMAP_EMAIL", "")
            imap_password = getattr(config.profile, "IMAP_PASSWORD", "")
            
            return jsonify({
                "profile": PROFILE,
                "skills": MY_SKILLS,
                "keywords": SEARCH_KEYWORDS,
                "locations": SEARCH_LOCATIONS,
                "companies": TARGET_COMPANIES,
                "cover_letter": COVER_LETTER,
                "min_match_score": MIN_MATCH_SCORE,
                "daily_limit": DAILY_LIMIT,
                "company_credentials": company_credentials,
                "tech_experience": tech_experience,
                "gemini_api_key": gemini_api_key,
                "auto_threshold": auto_threshold,
                "review_threshold": review_threshold,
                "imap_host": imap_host,
                "imap_email": imap_email,
                "imap_password": imap_password
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500
            
    elif request.method == "POST":
        try:
            data = request.get_json() or {}
            profile_dict = data.get("profile", {})
            skills_list = data.get("skills", [])
            keywords_list = data.get("keywords", [])
            locations_list = data.get("locations", [])
            companies_list = data.get("companies", [])
            cover_letter = data.get("cover_letter", "")
            daily_limit = int(data.get("daily_limit", 50))
            min_match_score = int(data.get("min_match_score", 30))
            auto_threshold = int(data.get("auto_threshold", 75))
            review_threshold = int(data.get("review_threshold", 55))
            company_credentials_dict = data.get("company_credentials")
            tech_experience_dict = data.get("tech_experience", {})
            gemini_api_key = data.get("gemini_api_key", "")
            imap_host = data.get("imap_host", "imap.gmail.com")
            imap_email = data.get("imap_email", "")
            imap_password = data.get("imap_password", "")
            
            if company_credentials_dict is None:
                import importlib
                import config.profile
                importlib.reload(config.profile)
                company_credentials_dict = getattr(config.profile, "COMPANY_CREDENTIALS", {})
            
            # Recompute tech experience dict preserving user's custom settings
            tech_exp = {}
            for skill in skills_list:
                s_lower = skill.lower()
                tech_exp[s_lower] = tech_experience_dict.get(s_lower, profile_dict.get("total_experience_years", "5"))
                
            content = f"""# Auto-generated by Job Bot Portal
COMPANY_CREDENTIALS = {repr(company_credentials_dict)}
PROFILE = {repr(profile_dict)}

MY_SKILLS = {repr(skills_list)}

TECH_EXPERIENCE = {repr(tech_exp)}

WORK_PREFERENCES = {{
    "preferred_work_mode":   "Hybrid",
    "open_to_relocation":    True,
    "authorized_india":      True,
    "require_sponsorship":   False,
    "gender":                "Prefer not to say",
}}

DAILY_LIMIT        = {daily_limit}
PER_RUN_LIMIT      = 15
SCHEDULED_RUNS     = ["09:00", "14:00", "19:00"]
HEADLESS_DEFAULT   = True

MIN_MATCH_SCORE = {min_match_score}
AUTO_THRESHOLD = {auto_threshold}
REVIEW_THRESHOLD = {review_threshold}

SEARCH_KEYWORDS = {repr(keywords_list)}
SEARCH_LOCATIONS = {repr(locations_list)}
TARGET_COMPANIES = {repr(companies_list)}

COVER_LETTER = \"\"\"{cover_letter.strip()}\"\"\".strip()

GEMINI_API_KEY = {repr(gemini_api_key)}

IMAP_HOST = {repr(imap_host)}
IMAP_EMAIL = {repr(imap_email)}
IMAP_PASSWORD = {repr(imap_password)}
"""
            with open(profile_path, "w", encoding="utf-8") as f:
                f.write(content)
                
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

@app.route("/api/notifications")
def api_notifications():
    try:
        import importlib
        import config.profile
        importlib.reload(config.profile)
        company_creds = getattr(config.profile, "COMPANY_CREDENTIALS", {})
        
        # Read CSV log to analyze skips
        csv_path = "logs/job_applications.csv"
        if not os.path.exists(csv_path):
            return jsonify({"notifications": []})
            
        skipped_groups = {}
        with open(csv_path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                status = row.get("Status")
                comp = row.get("Company") or ""
                score_str = row.get("Match %") or "0%"
                role = row.get("Role") or "Unknown"
                url = row.get("URL") or ""
                
                try:
                    score = float(score_str.replace("%", "").strip())
                except ValueError:
                    score = 0
                    
                if status in ("Manual Needed", "Skipped") and score >= 20 and comp:
                    comp_key = comp.strip()
                    if comp_key not in skipped_groups:
                        skipped_groups[comp_key] = {"count": 0, "roles": set(), "urls": []}
                    skipped_groups[comp_key]["count"] += 1
                    skipped_groups[comp_key]["roles"].add(role.strip())
                    skipped_groups[comp_key]["urls"].append(url)
                    
        from careers_bot import detect_platform
        notifications = []
        for comp_name, group in skipped_groups.items():
            # Only recommend if count >= 2
            if group["count"] >= 2:
                # Check if we already have credentials
                has_creds = False
                for c_name in company_creds:
                    if c_name.lower() in comp_name.lower() or comp_name.lower() in c_name.lower():
                        has_creds = True
                        break
                        
                if not has_creds:
                    # Detect platform of first URL to determine if it requires credentials
                    requires_login = False
                    platform_detected = "unknown"
                    if group["urls"]:
                        platform_detected = detect_platform(group["urls"][0])
                        if platform_detected in ("workday", "icims", "taleo", "successfactors"):
                            requires_login = True
                            
                    roles_list = list(group["roles"])[:3]
                    roles_str = ", ".join(roles_list)
                    if len(group["roles"]) > 3:
                        roles_str += "..."
                        
                    if requires_login:
                        msg = f"<strong>{comp_name}</strong> has {group['count']} high-match jobs ({roles_str}) on {platform_detected.upper()} that require account logins. You can configure custom credentials below, or let the bot auto-register/apply using your default corporate email!"
                    elif platform_detected in ("greenhouse", "lever", "smartrecruiters"):
                        msg = f"<strong>{comp_name}</strong> has {group['count']} high-match jobs ({roles_str}) on login-free platform {platform_detected.upper()}! The bot can auto-apply **without credentials**."
                    else:
                        msg = f"<strong>{comp_name}</strong> has {group['count']} high-match jobs ({roles_str}) that were skipped/stalled. The bot will attempt to auto-apply without credentials or using default profile fallback."
                        
                    notifications.append({
                        "company": comp_name,
                        "count": group["count"],
                        "roles": roles_list,
                        "message": msg
                    })
                    
        return jsonify({"notifications": notifications})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/company-credentials", methods=["POST"])
def api_company_credentials():
    try:
        data = request.get_json() or {}
        comp = data.get("company", "").strip()
        email = data.get("email", "").strip()
        password = data.get("password", "").strip()
        
        if not comp or not email or not password:
            return jsonify({"error": "Missing company, email, or password"}), 400
            
        import importlib
        import config.profile
        importlib.reload(config.profile)
        
        from config.profile import PROFILE, MY_SKILLS, SEARCH_KEYWORDS, SEARCH_LOCATIONS, TARGET_COMPANIES, COVER_LETTER, MIN_MATCH_SCORE, DAILY_LIMIT
        company_creds = getattr(config.profile, "COMPANY_CREDENTIALS", {})
        
        # Save / Update
        company_creds[comp] = {"email": email, "password": password}
        
        tech_exp = getattr(config.profile, "TECH_EXPERIENCE", {})
            
        profile_path = "config/profile.py"
        content = f"""# Auto-generated by Job Bot Portal
COMPANY_CREDENTIALS = {repr(company_creds)}
PROFILE = {repr(PROFILE)}

MY_SKILLS = {repr(MY_SKILLS)}

TECH_EXPERIENCE = {repr(tech_exp)}

WORK_PREFERENCES = {{
    "preferred_work_mode":   "Hybrid",
    "open_to_relocation":    True,
    "authorized_india":      True,
    "require_sponsorship":   False,
    "gender":                "Prefer not to say",
}}

DAILY_LIMIT        = {DAILY_LIMIT}
PER_RUN_LIMIT      = 15
SCHEDULED_RUNS     = ["09:00", "14:00", "19:00"]
HEADLESS_DEFAULT   = True

MIN_MATCH_SCORE = {MIN_MATCH_SCORE}

SEARCH_KEYWORDS = {repr(SEARCH_KEYWORDS)}
SEARCH_LOCATIONS = {repr(SEARCH_LOCATIONS)}
TARGET_COMPANIES = {repr(TARGET_COMPANIES)}

COVER_LETTER = \"\"\"{COVER_LETTER.strip()}\"\"\".strip()
"""
        with open(profile_path, "w", encoding="utf-8") as f:
            f.write(content)
            
        importlib.reload(config.profile)
        
        # Trigger retry logic in background!
        from retry_engine import trigger_retry_thread
        trigger_retry_thread(comp, log_fn=bot_log)
        
        return jsonify({"ok": True, "message": f"Credentials added for {comp} and retry started!"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/company-credentials/delete", methods=["POST"])
def api_company_credentials_delete():
    try:
        data = request.get_json() or {}
        comp = data.get("company", "").strip()
        if not comp:
            return jsonify({"error": "Missing company name"}), 400
            
        import importlib
        import config.profile
        importlib.reload(config.profile)
        
        from config.profile import PROFILE, MY_SKILLS, SEARCH_KEYWORDS, SEARCH_LOCATIONS, TARGET_COMPANIES, COVER_LETTER, MIN_MATCH_SCORE, DAILY_LIMIT
        company_creds = getattr(config.profile, "COMPANY_CREDENTIALS", {})
        
        if comp in company_creds:
            del company_creds[comp]
            
        tech_exp = getattr(config.profile, "TECH_EXPERIENCE", {})
            
        profile_path = "config/profile.py"
        content = f"""# Auto-generated by Job Bot Portal
COMPANY_CREDENTIALS = {repr(company_creds)}
PROFILE = {repr(PROFILE)}

MY_SKILLS = {repr(MY_SKILLS)}

TECH_EXPERIENCE = {repr(tech_exp)}

WORK_PREFERENCES = {{
    "preferred_work_mode":   "Hybrid",
    "open_to_relocation":    True,
    "authorized_india":      True,
    "require_sponsorship":   False,
    "gender":                "Prefer not to say",
}}

DAILY_LIMIT        = {DAILY_LIMIT}
PER_RUN_LIMIT      = 15
SCHEDULED_RUNS     = ["09:00", "14:00", "19:00"]
HEADLESS_DEFAULT   = True

MIN_MATCH_SCORE = {MIN_MATCH_SCORE}

SEARCH_KEYWORDS = {repr(SEARCH_KEYWORDS)}
SEARCH_LOCATIONS = {repr(SEARCH_LOCATIONS)}
TARGET_COMPANIES = {repr(TARGET_COMPANIES)}

COVER_LETTER = \"\"\"{COVER_LETTER.strip()}\"\"\".strip()
"""
        with open(profile_path, "w", encoding="utf-8") as f:
            f.write(content)
            
        importlib.reload(config.profile)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/targeted_results")
def api_targeted_results():
    global TARGETED_SEARCH_RESULTS
    return jsonify(TARGETED_SEARCH_RESULTS)

@app.route("/api/assist_apply", methods=["POST"])
def api_assist_apply():
    data = request.get_json() or {}
    url = data.get("url", "")
    company = data.get("company", "Company")
    role = data.get("role", "Role")
    
    if not url:
        return jsonify({"ok": False, "error": "No URL provided"}), 400
        
    def run_assist():
        from browser import create_browser
        import time
        bot_log(f"\n[ASSIST APPLY] Launching browser for {company} -- {role} (Manual Assist)...")
        
        profile_name = "linkedin" if "linkedin.com" in url.lower() else ("naukri" if "naukri.com" in url.lower() else "approve_apply")
        
        try:
            # Assist must always be non-headless
            driver = create_browser(headless=False, profile_name=profile_name)
            driver.get(url)
            bot_log(f"  [ASSIST] Opened {url} in browser.")
            bot_log(f"  [ASSIST] Please login/fill the form manually. This browser window will remain open for your interaction.")
            
            # Keep browser alive until closed by user
            while True:
                time.sleep(2)
                try:
                    _ = driver.current_url
                except Exception:
                    bot_log("  [ASSIST] Browser closed. Assist application session ended.")
                    break
        except Exception as e:
            bot_log(f"  [ERROR] Assist run error: {e}")
            
    threading.Thread(target=run_assist, daemon=True).start()
    return jsonify({"ok": True, "message": "Manual Assist session started."})

# ── Scheduler ───────────────────────────────────────────────────────
def _start_scheduler():
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        scheduler = BackgroundScheduler()
        for run_time in SCHEDULED_RUNS:
            h, m = map(int, run_time.split(":"))
            scheduler.add_job(
                lambda: api_run_internal("all"),
                "cron", hour=h, minute=m
            )
        scheduler.start()
        print(f"[SCHEDULER] Scheduled runs at: {', '.join(SCHEDULED_RUNS)}")
    except ImportError:
        print("[WARN] apscheduler not installed — scheduled runs disabled. Run: pip install apscheduler")

def api_run_internal(target):
    """Internal version for scheduler (no Flask context)."""
    from linkedin_bot import run_linkedin_bot
    from naukri_bot import run_naukri_bot
    STOP_EVENT.clear()
    if target in ("linkedin", "all"):
        run_linkedin_bot(max_applications=15, headless=True, log_fn=bot_log, stop_event=STOP_EVENT)
    if not STOP_EVENT.is_set() and target in ("naukri", "all"):
        run_naukri_bot(max_applications=15, headless=True, log_fn=bot_log, stop_event=STOP_EVENT)

if __name__ == "__main__":
    try:
        import email_monitor
        email_monitor.start_monitor(interval_minutes=5, log_fn=bot_log)
    except Exception as e:
        print(f"[WARN] Email monitor thread failed to start: {e}")
        
    _start_scheduler()
    print("[DASHBOARD] Open http://localhost:5005")
    app.run(host='0.0.0.0', port=5005, debug=False, threaded=True)
