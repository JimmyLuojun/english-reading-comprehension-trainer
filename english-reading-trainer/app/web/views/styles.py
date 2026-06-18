"""Inline CSS for server-rendered web pages."""

from __future__ import annotations

def _css() -> str:
    return """
    :root {
      color-scheme: light;
      --bg: #f6f8f5;
      --surface: #fffefa;
      --surface-alt: #eef4f1;
      --nav-surface: rgba(255, 254, 250, 0.9);
      --line: #e3e8ef;
      --text: #1f2937;
      --text-dim: #4b5563;
      --muted: #667085;
      --accent: #0f8f83;
      --accent-strong: #0c7268;
      --accent-line: #97d5cf;
      --accent-soft: #e7f6f3;
      --ok: #047857;
      --danger: #b42318;
      --danger-line: #fecdca;
      --danger-bg: #fff1f0;
      --radius: 8px;
      --radius-sm: 6px;
      --radius-pill: 999px;
      --shadow: 0 18px 50px rgba(20, 30, 40, 0.08);
      --font-display: Georgia, "Noto Serif SC", "Songti SC", serif;
      --analysis-panel-width: 520px;
      --reader-max-width: 840px;
    }
    html[data-theme="sepia"] {
      color-scheme: light;
      --bg: #efe6d3;
      --surface: #faf5ea;
      --surface-alt: #f1e9d7;
      --nav-surface: rgba(250, 244, 228, 0.92);
      --line: #e6dcc6;
      --text: #463a28;
      --text-dim: #6b5c40;
      --muted: #8a7a5c;
      --accent: #0f8f83;
      --accent-strong: #0c7268;
      --accent-line: #92c9bd;
      --accent-soft: #e1efe8;
      --radius: 8px;
      --radius-sm: 6px;
      --radius-pill: 999px;
      --shadow: 0 16px 40px rgba(70, 55, 25, 0.07);
      --font-display: Georgia, "Noto Serif SC", "Songti SC", serif;
    }
    ::selection {
      background: var(--accent);
      color: #fff;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    nav {
      display: flex;
      gap: 6px;
      align-items: center;
      padding: 12px 24px;
      border-bottom: 1px solid var(--line);
      background: var(--nav-surface);
      backdrop-filter: blur(10px);
      position: sticky;
      top: 0;
      z-index: 1;
    }
    nav a, .button, button {
      border: 1px solid var(--line);
      background: var(--surface);
      color: var(--text);
      text-decoration: none;
      padding: 7px 10px;
      border-radius: var(--radius-sm);
      font: inherit;
      cursor: pointer;
      white-space: nowrap;
      transition: border-color 140ms ease, color 140ms ease, background-color 140ms ease;
    }
    nav a.active, .button.primary, button:hover, .button:hover {
      border-color: var(--accent);
      color: var(--accent-strong);
    }
    .button.primary, button.primary {
      background: var(--accent);
      border-color: var(--accent);
      color: #fff;
    }
    .button.primary:hover, button.primary:hover {
      background: var(--accent-strong);
      border-color: var(--accent-strong);
      color: #fff;
    }
    #theme-toggle {
      margin-left: auto;
    }
    button.danger, .button.danger {
      border-color: var(--danger-line);
      color: var(--danger);
    }
    button.danger:hover, .button.danger:hover {
      background: var(--danger-bg);
      border-color: var(--danger);
      color: var(--danger);
    }
    .reader-page {
      background: var(--surface);
    }
    .reader-page nav {
      padding: 8px 16px;
      background: var(--nav-surface);
      backdrop-filter: blur(10px);
    }
    main {
      width: min(1180px, calc(100vw - 32px));
      margin: 24px auto 48px;
    }
    body.narrow main {
      width: min(760px, calc(100vw - 32px));
    }
    .reader-page main {
      width: 100%;
      margin: 0;
    }
    @media (min-width: 1180px) {
      .reader-page main {
        padding-right: var(--analysis-panel-width);
      }
    }
    h1, h2, .reader-title {
      font-family: var(--font-display);
      font-weight: 600;
    }
    h1 { margin: 0; font-size: 30px; line-height: 1.15; }
    h2 { margin: 32px 0 12px; font-size: 20px; line-height: 1.2; }
    p { margin: 6px 0; }
    .muted { color: var(--muted); }
    .toolbar {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: flex-start;
      margin-bottom: 18px;
    }
    .metrics {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 10px;
      margin-bottom: 20px;
    }
    .metric {
      display: block;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 12px;
      color: inherit;
      text-decoration: none;
      box-shadow: var(--shadow);
      transition: border-color 140ms ease, box-shadow 140ms ease, transform 140ms ease;
    }
    .metric span { display: block; color: var(--muted); font-size: 13px; }
    .metric strong { font-size: 24px; font-variant-numeric: tabular-nums; }
    .metric-link:hover, .metric-link:focus {
      border-color: var(--accent);
      color: var(--accent-strong);
      transform: translateY(-1px);
    }
    .metric-link:focus-visible {
      outline: 2px solid var(--accent);
      outline-offset: 2px;
    }
    .band {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 20px;
      margin-bottom: 18px;
      box-shadow: var(--shadow);
    }
    .split {
      display: grid;
      grid-template-columns: minmax(0, 2fr) minmax(260px, 1fr);
      gap: 24px;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: none;
      overflow: visible;
    }
    th, td {
      border-bottom: 1px solid var(--line);
      padding: 9px 10px;
      text-align: left;
      vertical-align: top;
      font-variant-numeric: tabular-nums;
    }
    th {
      color: var(--muted);
      font-size: 12px;
      font-weight: 600;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      background: var(--surface-alt);
    }
    tbody tr:hover { background: var(--surface-alt); }
    tr:last-child td { border-bottom: 0; }
    .review-item-col { width: 40%; }
    .reader {
      width: min(100%, var(--reader-max-width));
      max-width: var(--reader-max-width);
      margin: 32px auto 96px;
      padding: 0 16px;
    }
    .reader-header {
      margin: 0 0 32px;
    }
    .reader-header-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 18px;
    }
    .reader-title {
      margin: 0 0 4px;
      font-size: 28px;
      line-height: 1.2;
    }
    .reader-chapter {
      margin: 0;
      color: var(--text-dim);
      font-size: 16px;
      font-weight: 400;
    }
    .reader-anchor {
      scroll-margin-top: 72px;
    }
    .reader-section-nav {
      margin: 0 0 20px;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.45;
    }
    .reader-section-nav a {
      color: inherit;
      text-decoration: none;
    }
    .reader-section-nav a:hover {
      color: var(--accent-strong);
    }
    .reader-section-nav-next {
      margin: 28px 0 0;
    }
    .reader-para {
      margin: 0 0 1.2em;
      color: var(--text);
      font-family: Georgia, "Source Han Serif SC", "Songti SC", serif;
      font-size: 20px;
      line-height: 1.8;
    }
    .reader-figure {
      margin: 28px 0;
    }
    .reader-figure img {
      display: block;
      max-width: 100%;
      height: auto;
      margin: 0 auto;
    }
    .reader-figure figcaption {
      margin-top: 8px;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.45;
      text-align: center;
    }
    .reader-missing-asset {
      border: 1px dashed var(--line);
      color: var(--muted);
      padding: 10px 12px;
      font-size: 14px;
      text-align: center;
    }
    .reader-sentence {
      cursor: text;
      scroll-margin-top: 72px;
      text-underline-offset: 0.22em;
    }
    [data-sentence-id].marked {
      background: linear-gradient(transparent 60%, #ffe58a 60%);
      box-decoration-break: clone;
      -webkit-box-decoration-break: clone;
    }
    [data-sentence-id].translated {
      text-decoration-line: underline;
      text-decoration-style: dotted;
      text-decoration-color: #2563eb;
      text-decoration-thickness: 1.5px;
    }
    .reader-sentence:target {
      background: #bfdbfe;
      border-radius: 2px;
      box-shadow: 0 0 0 2px #bfdbfe;
    }
    [data-sentence-id].analyzed,
    [data-sentence-id].analyzed-stale {
      border-left: 1px solid #2563eb;
      padding-left: 4px;
    }
    [data-sentence-id].analyzed-stale {
      border-left-style: dashed;
    }
    [data-sentence-id].analysis-highlight-fallback {
      outline: 2px solid rgba(37, 99, 235, 0.35);
      outline-offset: 2px;
    }
    .analysis-highlight {
      background: #bfdbfe;
      box-shadow: 0 0 0 2px #bfdbfe;
    }
    [data-word-card] {
      margin: 0 -0.03em;
      border-radius: 3px;
      padding: 0 0.06em;
      background: linear-gradient(transparent 54%, rgba(251, 191, 36, 0.34) 54%);
      box-decoration-break: clone;
      -webkit-box-decoration-break: clone;
      cursor: pointer;
      text-decoration-line: underline;
      text-decoration-style: solid;
      text-decoration-color: rgba(217, 119, 6, 0.72);
      text-decoration-thickness: 0.12em;
      text-underline-offset: 0.18em;
      transition: background-color 120ms ease, text-decoration-color 120ms ease;
    }
    [data-word-card]:hover {
      background: linear-gradient(transparent 42%, rgba(251, 191, 36, 0.52) 42%);
      text-decoration-color: #b45309;
    }
    [data-word-card][data-lexical-type="word"] {
      background: linear-gradient(transparent 54%, rgba(16, 185, 129, 0.28) 54%);
      text-decoration-color: rgba(5, 150, 105, 0.78);
    }
    [data-word-card][data-lexical-type="word"]:hover {
      background: linear-gradient(transparent 42%, rgba(16, 185, 129, 0.42) 42%);
      text-decoration-color: #047857;
    }
    [data-word-card][data-lexical-type="phrase"] {
      background: linear-gradient(transparent 54%, rgba(168, 85, 247, 0.24) 54%);
      text-decoration-color: rgba(126, 34, 206, 0.74);
    }
    [data-word-card][data-lexical-type="phrase"]:hover {
      background: linear-gradient(transparent 42%, rgba(168, 85, 247, 0.38) 42%);
      text-decoration-color: #6b21a8;
    }
    [data-word-card][data-lexical-type="collocation"],
    [data-word-card][data-lexical-type="idiom"] {
      background: linear-gradient(transparent 54%, rgba(249, 115, 22, 0.28) 54%);
      text-decoration-color: rgba(194, 65, 12, 0.76);
    }
    [data-word-card][data-lexical-type="collocation"]:hover,
    [data-word-card][data-lexical-type="idiom"]:hover {
      background: linear-gradient(transparent 42%, rgba(249, 115, 22, 0.44) 42%);
      text-decoration-color: #9a3412;
    }
    .selection-toolbar {
      position: absolute;
      z-index: 20;
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      align-items: center;
      box-sizing: border-box;
      max-width: min(calc(100vw - 16px), 520px);
      padding: 8px;
      border-radius: var(--radius);
      background: #111827;
      color: #f9fafb;
      box-shadow: 0 12px 32px rgba(15, 23, 42, 0.28);
    }
    .selection-toolbar[hidden] { display: none; }
    .toolbar-group {
      display: flex;
      gap: 6px;
      align-items: center;
      flex-wrap: wrap;
      max-width: 100%;
    }
    .toolbar-group[hidden] { display: none; }
    .selection-toolbar button {
      border-color: #374151;
      background: #f9fafb;
      color: #111827;
      max-width: 100%;
      white-space: normal;
    }
    .selection-toolbar button.danger {
      border-color: #fecaca;
      color: #991b1b;
    }
    .toolbar-status {
      padding: 5px 4px;
      color: #e5e7eb;
      font-size: 14px;
      white-space: nowrap;
    }
    #toolbar-analysis-word-status {
      flex-basis: 100%;
    }
    .word-detail-panel {
      display: grid;
      gap: 8px;
      box-sizing: border-box;
      width: min(420px, calc(100vw - 32px));
    }
    .word-detail-panel[hidden] { display: none; }
    .word-detail-surface {
      color: #f1f5f9;
      font-size: 15px;
    }
    .word-detail-fields {
      display: grid;
      gap: 6px;
      min-width: 0;
    }
    .word-detail-label {
      display: grid;
      gap: 3px;
      color: #94a3b8;
      font-size: 12px;
    }
    .word-detail-label input {
      box-sizing: border-box;
      width: 100%;
      min-width: 0;
      background: #f9fafb;
      color: #111827;
      border: 1px solid #cbd5e1;
      border-radius: 4px;
      padding: 5px 8px;
      font-size: 14px;
    }
    .word-detail-actions {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
    }
    .word-detail-actions button {
      flex: 1 1 max-content;
      min-width: min(140px, 100%);
    }
    .translation-editor {
      display: grid;
      gap: 6px;
      width: min(520px, calc(92vw - 16px));
      max-height: min(52vh, 360px);
      overflow: auto;
    }
    .translation-editor[hidden] { display: none; }
    .translation-editor label {
      color: #e5e7eb;
      font-size: 13px;
    }
    .translation-editor textarea {
      min-height: 92px;
      min-width: 100%;
      resize: vertical;
      background: #f9fafb;
      color: #111827;
    }
    .translation-actions {
      display: flex;
      gap: 6px;
      justify-content: flex-end;
      flex-wrap: wrap;
    }
    .analysis-panel {
      position: fixed;
      z-index: 15;
      top: 49px;
      right: 0;
      bottom: 0;
      width: min(var(--analysis-panel-width), 92vw);
      overflow-y: auto;
      border-left: 1px solid var(--line);
      background: var(--surface);
      box-shadow: -14px 0 32px rgba(15, 23, 42, 0.14);
      padding: 18px;
    }
    .analysis-panel[hidden] { display: none; }
    .analysis-panel-tab {
      position: fixed;
      z-index: 14;
      top: 96px;
      right: 0;
      border-right: 0;
      border-radius: var(--radius-sm) 0 0 var(--radius-sm);
      padding: 10px 8px;
      color: var(--accent-strong);
      writing-mode: vertical-rl;
      text-orientation: mixed;
      box-shadow: -8px 0 22px rgba(15, 23, 42, 0.12);
    }
    .analysis-open .analysis-panel-tab {
      display: none;
    }
    .analysis-panel-header {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: flex-start;
      margin-bottom: 12px;
    }
    .analysis-panel-header h2 {
      margin: 0;
      font-size: 18px;
    }
    .analysis-title-row {
      display: flex;
      gap: 6px;
      align-items: center;
      flex-wrap: wrap;
    }
    .panel-kicker {
      margin: 0 0 2px;
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.12em;
    }
    .analysis-status {
      min-height: 20px;
      margin: 8px 0 12px;
      color: var(--text-dim);
      font-size: 14px;
    }
    .analysis-status.error {
      color: #b91c1c;
    }
    .analysis-section {
      border-top: 1px solid var(--line);
      padding-top: 12px;
      margin-top: 12px;
    }
    .analysis-section h3 {
      display: flex;
      flex-direction: column;
      gap: 1px;
      margin: 0 0 8px;
      padding-left: 10px;
      border-left: 4px solid var(--accent);
      color: var(--text);
      font-size: 13px;
      font-weight: 700;
    }
    .analysis-section h4 {
      display: flex;
      flex-direction: column;
      gap: 1px;
      margin: 10px 0 4px;
      padding-left: 8px;
      border-left: 2px solid var(--accent-line);
      color: var(--text-dim);
      font-size: 12px;
      font-weight: 600;
    }
    .section-label-zh {
      font-size: 16px;
      font-weight: 700;
      color: var(--accent-strong);
      line-height: 1.25;
    }
    .analysis-section h4 .section-label-zh {
      font-size: 14px;
      color: var(--text-dim);
    }
    .section-label-en {
      font-size: 11px;
      font-weight: 600;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }
    .analysis-text {
      margin: 0;
      font-size: 20px;
      line-height: 1.7;
    }
    .glossary-word {
      position: relative;
      border: 1px solid #93c5fd;
      border-bottom: 2px solid #2563eb;
      border-radius: 4px;
      padding: 0 2px;
      background: #fef3c7;
      color: #111827;
      cursor: pointer;
    }
    .glossary-word:hover {
      border-color: #2563eb;
      border-bottom-color: #2563eb;
      background: #dbeafe;
      box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.16);
    }
    .glossary-word[data-lexical-type="word"] {
      border-color: rgba(5, 150, 105, 0.5);
      border-bottom-color: #059669;
      background: #d1fae5;
    }
    .glossary-word[data-lexical-type="word"]:hover {
      border-color: #047857;
      border-bottom-color: #047857;
      background: #a7f3d0;
      box-shadow: 0 0 0 2px rgba(16, 185, 129, 0.18);
    }
    .glossary-word[data-lexical-type="phrase"] {
      border-color: rgba(126, 34, 206, 0.45);
      border-bottom-color: #7e22ce;
      background: #f3e8ff;
    }
    .glossary-word[data-lexical-type="phrase"]:hover {
      border-color: #6b21a8;
      border-bottom-color: #6b21a8;
      background: #e9d5ff;
      box-shadow: 0 0 0 2px rgba(168, 85, 247, 0.18);
    }
    .glossary-word[data-lexical-type="collocation"],
    .glossary-word[data-lexical-type="idiom"] {
      border-color: rgba(194, 65, 12, 0.45);
      border-bottom-color: #c2410c;
      background: #ffedd5;
    }
    .glossary-word[data-lexical-type="collocation"]:hover,
    .glossary-word[data-lexical-type="idiom"]:hover {
      border-color: #9a3412;
      border-bottom-color: #9a3412;
      background: #fed7aa;
      box-shadow: 0 0 0 2px rgba(249, 115, 22, 0.18);
    }
    .analysis-translation {
      margin-top: 6px;
      color: var(--text-dim);
    }
    .analysis-codes {
      display: inline-block;
      margin: 2px 0 8px;
      border: 1px solid var(--accent-line);
      border-radius: var(--radius-pill);
      padding: 2px 8px;
      color: var(--accent-strong);
      background: var(--accent-soft);
      font-size: 13px;
    }
    .word-analysis-list {
      margin: 4px 0 0;
      padding-left: 18px;
    }
    .word-analysis-list li {
      margin: 2px 0;
      line-height: 1.45;
    }
    [data-word-card].word-analysis-active {
      background: #fef9c3;
      border-radius: 2px;
      outline: 2px solid #f59e0b;
      outline-offset: 1px;
    }
    .vs-simpler-item {
      margin: 4px 0;
    }
    .word-notes-fields {
      display: grid;
      gap: 6px;
      margin: 4px 0 8px;
    }
    .word-notes-label {
      display: flex;
      flex-direction: column;
      gap: 3px;
      font-size: 13px;
      color: var(--muted);
    }
    .word-notes-label input {
      font: inherit;
      border: 1px solid var(--line);
      border-radius: var(--radius-sm);
      padding: 5px 8px;
      color: var(--text);
      font-size: 14px;
    }
    .sentence-study-section textarea {
      width: 100%;
      min-height: 76px;
      margin-top: 6px;
      resize: vertical;
      font: inherit;
      border: 1px solid var(--line);
      border-radius: var(--radius-sm);
      padding: 7px 9px;
      color: var(--text);
      font-size: 14px;
      line-height: 1.45;
    }
    #sentence-panel-note-accept {
      margin-top: 6px;
    }
    .word-notes-actions {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .evidence-item {
      width: 100%;
      margin: 6px 0 0;
      border-color: var(--line);
      background: var(--surface-alt);
      color: var(--text);
      text-align: left;
      white-space: normal;
    }
    .evidence-item:hover {
      border-color: var(--accent);
      color: var(--accent-strong);
    }
    .similar-mistakes {
      margin-top: 12px;
      border-top: 1px solid var(--line);
      padding-top: 10px;
    }
    .similar-mistakes h4 {
      margin: 0 0 4px;
      color: var(--text);
      font-size: 14px;
    }
    .similar-mistake {
      margin-top: 10px;
      border: 1px solid #dbeafe;
      border-radius: var(--radius);
      padding: 10px;
      background: var(--surface-alt);
    }
    .similar-mistake-source {
      margin: 2px 0 0;
      line-height: 1.5;
      color: var(--text);
    }
    .similar-mistake-comparison {
      display: grid;
      gap: 4px;
      margin-top: 8px;
    }
    .similar-mistake-line {
      margin: 0;
      line-height: 1.45;
      color: var(--text);
    }
    .similar-mistake-line strong {
      color: var(--muted);
      font-weight: 600;
    }
    .analysis-panel-actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: 16px;
      padding-top: 12px;
      border-top: 1px solid var(--line);
    }
    .badge {
      color: var(--ok);
      border: 1px solid #9bd4bd;
      border-radius: var(--radius-pill);
      padding: 1px 7px;
      margin-left: 6px;
    }
    .actions, .answer-form, .inline-form {
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
    }
    .answer-form {
      gap: 6px;
      flex-wrap: nowrap;
    }
    .answer-form button { padding: 4px 10px; }
    .card-anchor {
      scroll-margin-top: 72px;
    }
    .card-anchor:target {
      outline: 2px solid #2563eb;
      outline-offset: -2px;
      background: #eff6ff;
    }
    .glossary-return {
      margin-left: auto;
    }
    .inline-form input, .inline-form select, textarea {
      border: 1px solid var(--line);
      border-radius: var(--radius-sm);
      padding: 7px 9px;
      font: inherit;
      min-width: 160px;
    }
    textarea { width: 100%; min-height: 180px; }
    td button.danger, td .button.danger {
      border-color: var(--line);
      color: var(--muted);
    }
    td button.danger:hover, td .button.danger:hover {
      background: var(--danger-bg);
      border-color: var(--danger);
      color: var(--danger);
    }
    .stack-form { display: grid; gap: 8px; }
    .stack-form input:not([type=file]) { max-width: 420px; }
    .stack-form textarea { max-width: 640px; }
    .stack-form button { justify-self: start; }
    .small { padding: 4px 8px; }
    .prompt, .profile-summary pre {
      white-space: pre-wrap;
      background: #111827;
      color: #f9fafb;
      padding: 14px;
      border-radius: var(--radius-sm);
      overflow-x: auto;
    }
    .empty {
      color: var(--muted);
      border: 1px dashed var(--line);
      border-radius: var(--radius-sm);
      padding: 12px;
      background: var(--surface);
    }
    @media (max-width: 1179px) {
      .analysis-panel {
        inset: 0;
        width: 100%;
        border-left: 0;
        padding: 16px;
      }
      .analysis-panel-header {
        padding-bottom: 8px;
        border-bottom: 1px solid var(--line);
      }
    }
    @media (max-width: 780px) {
      nav { overflow-x: auto; padding: 10px; }
      main { width: min(100vw - 20px, 1180px); margin-top: 16px; }
      .reader-page main {
        width: 100%;
        margin: 0;
      }
      .toolbar, .split { display: block; }
      table { font-size: 14px; }
      th, td { padding: 8px; }
      .reader {
        margin: 24px auto 80px;
        padding: 0 20px;
      }
      .reader-para {
        font-size: 17px;
        line-height: 1.7;
      }
      .selection-toolbar {
        position: fixed;
        left: 10px !important;
        right: 10px;
        bottom: 10px;
        top: auto !important;
        max-width: none;
      }
      .translation-editor {
        width: 100%;
      }
    }
    .hover-popover {
      position: relative;
      display: inline-block;
      margin-bottom: 6px;
    }
    .hover-popover-trigger {
      color: var(--accent);
      cursor: pointer;
      font-size: 13px;
      white-space: nowrap;
    }
    .hover-popover-trigger:focus {
      outline: 2px solid var(--accent-line);
      outline-offset: 2px;
      border-radius: 3px;
    }
    .hover-popover-panel {
      position: absolute;
      top: calc(100% + 6px);
      left: 0;
      z-index: 500;
      display: none;
      width: min(360px, 80vw);
      max-height: min(280px, 60vh);
      overflow: auto;
      padding: 10px 12px;
      border-radius: var(--radius-sm);
      background: #111827;
      color: #f9fafb;
      box-shadow: 0 16px 36px rgba(15, 23, 42, 0.24);
      text-align: left;
      white-space: normal;
    }
    .hover-popover-right .hover-popover-panel {
      top: auto;
      right: 0;
      bottom: calc(100% + 8px);
      left: auto;
    }
    .hover-popover:hover .hover-popover-panel,
    .hover-popover:focus-within .hover-popover-panel {
      display: block;
    }
    .hover-popover-text {
      margin: 0;
      font-size: 13px;
      line-height: 1.45;
      color: inherit;
    }
    .hover-popover-text + .hover-popover-text {
      margin-top: 8px;
    }
    .source-link {
      color: var(--accent-strong);
      text-decoration: none;
    }
    .source-link:hover {
      text-decoration: underline;
    }
    .speak-inline {
      display: inline-flex;
      gap: 6px;
      align-items: baseline;
      max-width: 100%;
    }
    .speak-button {
      padding: 2px 5px;
      min-width: 26px;
      line-height: 1.2;
      color: var(--accent-strong);
    }
    .speak-button[hidden] {
      display: none;
    }
    .speak-button[disabled] {
      cursor: not-allowed;
      color: var(--muted);
      opacity: 0.55;
    }
    .speak-text {
      overflow-wrap: anywhere;
    }
    .sentence-field-cell {
      min-width: 260px;
      max-width: 560px;
    }
    .sentence-field-text {
      display: inline;
      margin-right: 4px;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }
    .sentence-field-edit {
      margin-top: 6px;
      display: grid;
      gap: 6px;
    }
    .sentence-field-edit[hidden] {
      display: none;
    }
    .sentence-field-input {
      width: 100%;
      min-height: 72px;
      resize: vertical;
      border-color: var(--accent);
    }
    .sentence-field-status {
      margin: 0;
    }
    .note-text { cursor: pointer; }
    .note-text:hover { text-decoration: underline dotted; }
    .note-edit-btn { background: none; border: none; cursor: pointer; color: var(--muted); font-size: 12px; padding: 0 2px; opacity: 0.5; }
    .note-edit-btn:hover { opacity: 1; color: var(--accent); }
    .note-input { border: 1px solid var(--accent); border-radius: 4px; padding: 2px 6px; font: inherit; font-size: 13px; min-width: 140px; }
    .word-card-delete {
      min-width: 64px;
    }
    .word-card-delete[disabled] {
      cursor: progress;
      opacity: 0.65;
    }
    """
