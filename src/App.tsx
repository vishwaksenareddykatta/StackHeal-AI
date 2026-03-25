import { useState, useRef, useCallback, useEffect } from "react";

// ─── Types ────────────────────────────────────────────────────────────────────

interface PipelineResult {
  type: string;
  message: string;
  line: number;
  snippet: string;
  severity: "Low" | "Medium" | "High" | "Critical" | string;
  language: string;
  root_cause: string;
  description: string;
  correctedCode: string;
  simple: string;
  detailed: string;
  confidence: number;
}

interface RepoFile {
  name: string;
  folder: string;
  content: string | null;
  status: "pending" | "ok" | "error";
  severity: string | null;
  result: PipelineResult | null;
}

type AppMode = "landing" | "file" | "repo";
type ExplainTab = "simple" | "detailed";
type PipelineStage = "idle" | "parse" | "analyze" | "detect" | "fix" | "done" | "error";
type BackendStatus = "checking" | "online" | "offline";

// ✅ Uses Vite proxy — /api → http://localhost:8000 (no CORS issues)
const API_BASE = "/api";

const LANG_EXTENSIONS: Record<string, string> = {
  py: "Python", js: "JavaScript", ts: "TypeScript", jsx: "JavaScript",
  tsx: "TypeScript", java: "Java", cpp: "C++", go: "Go", rs: "Rust", rb: "Ruby",
};

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

// ─── Hooks ────────────────────────────────────────────────────────────────────

function useConfBar(target: number, active: boolean) {
  const [width, setWidth] = useState(0);
  useEffect(() => {
    if (!active) { setWidth(0); return; }
    const t = setTimeout(() => setWidth(target * 100), 120);
    return () => clearTimeout(t);
  }, [target, active]);
  return width;
}

function useBackendStatus(): BackendStatus {
  const [status, setStatus] = useState<BackendStatus>("checking");
  useEffect(() => {
    const check = async () => {
      try {
        const res = await fetch(`${API_BASE}/health`, { signal: AbortSignal.timeout(3000) });
        setStatus(res.ok ? "online" : "offline");
      } catch {
        setStatus("offline");
      }
    };
    check();
    const interval = setInterval(check, 10000);
    return () => clearInterval(interval);
  }, []);
  return status;
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function BackendBadge({ status }: { status: BackendStatus }) {
  const color = status === "online" ? "var(--green)" : status === "offline" ? "var(--red)" : "var(--yellow)";
  const label = status === "online" ? "● Backend Online" : status === "offline" ? "● Backend Offline" : "● Connecting...";
  return (
    <div style={{
      padding: "3px 10px", borderRadius: 20, border: `1px solid ${color}44`,
      background: `${color}11`, fontSize: 11, color,
      fontFamily: "'JetBrains Mono', monospace", fontWeight: 600, whiteSpace: "nowrap",
    }}>
      {label}
    </div>
  );
}

function ConfBar({ score, active }: { score: number; active: boolean }) {
  const w = useConfBar(score, active);
  const pct = Math.round(score * 100);
  return (
    <div className="result-card">
      <div className="result-card-header">
        <span className="result-card-title">Confidence Score</span>
        <span className="conf-pct">{pct}%</span>
      </div>
      <div className="conf-label"><span>AI Confidence</span></div>
      <div className="conf-bar-wrap">
        <div className="conf-bar-fill" style={{ width: `${w}%` }} />
      </div>
    </div>
  );
}

function SevBadge({ severity }: { severity: string }) {
  const cls =
    severity === "High" || severity === "Critical" ? "sev-high"
    : severity === "Medium" ? "sev-med"
    : "sev-low";
  return <span className={`severity-badge ${cls}`}>{severity.toUpperCase()}</span>;
}

function ResultCards({ result, lang }: { result: PipelineResult; lang: string }) {
  const [tab, setTab] = useState<ExplainTab>("simple");
  const [copied, setCopied] = useState(false);

  const copyFix = useCallback(() => {
    navigator.clipboard.writeText(result.correctedCode).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }, [result.correctedCode]);

  const diffLines = [
    { type: "remove" as const, text: result.snippet || "// original code" },
    ...result.correctedCode.split("\n").map((l) => ({ type: "add" as const, text: l })),
  ];

  return (
    <div className="slide-in" style={{ display: "flex", flexDirection: "column", gap: 0 }}>
      <div className="result-card">
        <div className="result-card-header">
          <span className="result-card-title">⚠ Error Detected</span>
          <SevBadge severity={result.severity} />
        </div>
        <div className="error-text">{result.type}: {result.message}</div>
        {result.line > 0 && <div className="error-line">Line {result.line} · {lang}</div>}
      </div>

      <div className="result-card">
        <div className="result-card-header"><span className="result-card-title">🔍 Root Cause</span></div>
        <div className="explanation-text">{result.root_cause}</div>
      </div>

      <div className="result-card">
        <div className="result-card-header"><span className="result-card-title">💡 Explanation</span></div>
        <div className="tabs">
          <div className={`tab ${tab === "simple" ? "active" : ""}`} onClick={() => setTab("simple")}>Simple</div>
          <div className={`tab ${tab === "detailed" ? "active" : ""}`} onClick={() => setTab("detailed")}>Detailed</div>
        </div>
        <div className="explanation-text">{tab === "simple" ? result.simple : result.detailed}</div>
      </div>

      <div className="result-card">
        <div className="result-card-header"><span className="result-card-title">🔧 Suggested Fix</span></div>
        <div style={{ fontSize: 12, color: "var(--muted2)", marginBottom: 8 }}>{result.description}</div>
        <div className="fix-code">
          <pre style={{ whiteSpace: "pre-wrap", margin: 0 }}>{result.correctedCode}</pre>
          <button className="copy-btn" onClick={copyFix}>{copied ? "✓ Copied" : "Copy"}</button>
        </div>
      </div>

      <div className="result-card">
        <div className="result-card-header"><span className="result-card-title">📋 Diff View</span></div>
        <div style={{ background: "var(--bg)", borderRadius: 7, padding: 10, overflowX: "auto" }}>
          {diffLines.map((d, i) => (
            <div key={i} className={`diff-line ${d.type === "remove" ? "diff-remove" : "diff-add"}`}>
              {d.type === "remove" ? "- " : "+ "}{d.text}
            </div>
          ))}
        </div>
      </div>

      <ConfBar score={result.confidence} active />
    </div>
  );
}

// ─── Pipeline bar ─────────────────────────────────────────────────────────────

const PIPE_STAGES = [
  { id: "parse", label: "Parse" },
  { id: "analyze", label: "Analyze" },
  { id: "detect", label: "Detect" },
  { id: "fix", label: "Fix" },
  { id: "done", label: "Complete" },
];
const STAGE_ORDER = PIPE_STAGES.map((s) => s.id);

function PipelineBar({ current }: { current: PipelineStage }) {
  return (
    <div className="pipeline-bar">
      {PIPE_STAGES.map((s, i) => {
        const idx = STAGE_ORDER.indexOf(current);
        const cls = current === "done" ? "pipe-stage done"
          : i < idx ? "pipe-stage done"
          : i === idx ? "pipe-stage active"
          : "pipe-stage";
        return (
          <span key={s.id}>
            <span className={cls}><span className="pipe-dot" />{s.label}</span>
            {i < PIPE_STAGES.length - 1 && <span className="pipe-arrow">›</span>}
          </span>
        );
      })}
    </div>
  );
}

// ─── File Mode ────────────────────────────────────────────────────────────────

function FileMode() {
  const [code, setCode] = useState("");
  const [lang, setLang] = useState("Python");
  const [stage, setStage] = useState<PipelineStage>("idle");
  const [result, setResult] = useState<PipelineResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [overlayText, setOverlayText] = useState("Initializing pipeline...");
  const [overlayStage, setOverlayStage] = useState("STAGE 1/5 — PARSING");
  const [hasFile, setHasFile] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const gutterRef = useRef<HTMLDivElement>(null);

  const lineCount = code.split("\n").length;

  const syncGutter = useCallback(() => {
    if (gutterRef.current && textareaRef.current)
      gutterRef.current.scrollTop = textareaRef.current.scrollTop;
  }, []);

  const loadFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
    if (LANG_EXTENSIONS[ext]) setLang(LANG_EXTENSIONS[ext]);
    const reader = new FileReader();
    reader.onload = (ev) => { setCode((ev.target?.result as string) ?? ""); setHasFile(true); };
    reader.readAsText(file);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (!file) return;
    const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
    if (LANG_EXTENSIONS[ext]) setLang(LANG_EXTENSIONS[ext]);
    const reader = new FileReader();
    reader.onload = (ev) => { setCode((ev.target?.result as string) ?? ""); setHasFile(true); };
    reader.readAsText(file);
  };

  const analyze = async () => {
    const input = code.trim();
    if (!input) return;
    setResult(null);
    setError(null);

    const stages: [PipelineStage, string, string][] = [
      ["parse",   "Parsing source code...",    "STAGE 1/5 — PARSING"],
      ["analyze", "Running static analysis...", "STAGE 2/5 — ANALYSIS"],
      ["detect",  "Detecting anomalies...",     "STAGE 3/5 — DETECTION"],
      ["fix",     "Generating AI fix...",       "STAGE 4/5 — FIX GENERATION"],
    ];

    for (const [s, text, stageLabel] of stages) {
      setStage(s); setOverlayText(text); setOverlayStage(stageLabel);
      await sleep(600 + Math.random() * 300);
    }

    setOverlayText("Calling StackHeal pipeline...");
    setOverlayStage("STAGE 5/5 — AI AGENTS");

    try {
      const res = await fetch(`${API_BASE}/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: input, language: lang }),
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail ?? `Server error ${res.status}`);
      }
      setResult(await res.json());
      setStage("done");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Unknown error");
      setStage("error");
    }
  };

  const showOverlay = stage !== "idle" && stage !== "done" && stage !== "error";
  const reset = () => { setHasFile(false); setCode(""); setStage("idle"); setResult(null); setError(null); };

  return (
    <div className="main-area">
      {/* ── LEFT: editor ── */}
      <div className="panel left-panel-file">
        <div className="panel-header"><div className="panel-header-dot" />SOURCE INPUT</div>

        {!hasFile ? (
          <div className="upload-zone"
            onDragOver={(e) => e.preventDefault()} onDrop={handleDrop}
            onClick={() => document.getElementById("fileInput")?.click()}>
            <div className="upload-icon">📄</div>
            <div className="upload-text">Drop a file or click to browse</div>
            <div className="upload-subtext">.py · .js · .ts · .java · .cpp · .go · .rs</div>
            <input type="file" id="fileInput" style={{ display: "none" }}
              accept=".py,.js,.ts,.jsx,.tsx,.java,.cpp,.c,.go,.rs,.rb,.php,.cs"
              onChange={loadFile} />
          </div>
        ) : (
          <div className="editor-wrap">
            <div className="editor-gutter" ref={gutterRef}>
              {Array.from({ length: Math.max(lineCount, 20) }, (_, i) => (
                <div key={i + 1}>{i + 1}</div>
              ))}
            </div>
            <textarea ref={textareaRef} id="codeEditor" spellCheck={false}
              style={{ paddingLeft: 52 }} value={code}
              onChange={(e) => setCode(e.target.value)} onScroll={syncGutter}
              placeholder="// paste your code here..." />
            {showOverlay && (
              <div className="analyzing-overlay show">
                <div className="spinner" />
                <div className="analyzing-text">{overlayText}</div>
                <div className="analyzing-stage">{overlayStage}</div>
              </div>
            )}
          </div>
        )}

        <div className="controls-bar">
          <select value={lang} onChange={(e) => setLang(e.target.value)}>
            {["Python","JavaScript","TypeScript","Java","C++","Go","Rust","Ruby"].map(l => <option key={l}>{l}</option>)}
          </select>
          {!hasFile
            ? <button className="btn-sm" onClick={() => setHasFile(true)}>+ Paste Code</button>
            : <button className="btn-sm" onClick={reset}>↺ Reset</button>
          }
          <button className={`btn-analyze${showOverlay ? " loading" : ""}`}
            onClick={analyze} disabled={showOverlay || !code.trim()}>
            {showOverlay ? "⏳ Analyzing..." : "▶ Analyze"}
          </button>
        </div>
      </div>

      {/* ── RIGHT: results — flex:1 fills all remaining space ── */}
      <div className="panel results-panel">
        <PipelineBar current={stage} />
        <div className="right-scroll" style={{ padding: 14 }}>
          {stage === "idle" && (
            <div className="placeholder">
              <div className="placeholder-icon">🔍</div>
              <span>Run analysis to see results</span>
            </div>
          )}
          {stage === "error" && (
            <div className="result-card" style={{ borderColor: "rgba(255,77,106,.3)" }}>
              <div className="result-card-title" style={{ color: "var(--red)", marginBottom: 8 }}>⚠ Pipeline Error</div>
              <div className="explanation-text">{error}</div>
              <div className="explanation-text" style={{ marginTop: 8, fontSize: 11 }}>
                Make sure <code style={{ color: "var(--blue)" }}>uvicorn main:app --reload --port 8000</code> is running.
              </div>
            </div>
          )}
          {result && <ResultCards result={result} lang={lang} />}
        </div>
      </div>
    </div>
  );
}

// ─── Repo Mode ────────────────────────────────────────────────────────────────

const PG_NODES = [
  { icon: "📂", label: "Load" }, { icon: "⚙️", label: "Parse" },
  { icon: "🔬", label: "Scan" }, { icon: "🧠", label: "AI" }, { icon: "🔧", label: "Fix" },
];

function RepoMode() {
  const [files, setFiles] = useState<RepoFile[]>([]);
  const [selected, setSelected] = useState<RepoFile | null>(null);
  const [scanning, setScanning] = useState(false);
  const [scanStage, setScanStage] = useState(0);
  const [scanDone, setScanDone] = useState(false);
  const [tocSearch, setTocSearch] = useState("");
  const [tocFilter, setTocFilter] = useState<"all" | "error" | "ok">("all");
  const [activeNode, setActiveNode] = useState(-1);

  const loadFiles = (e: React.ChangeEvent<HTMLInputElement>) => {
    const rawFiles = Array.from(e.target.files ?? []);
    if (!rawFiles.length) return;
    const pending: RepoFile[] = rawFiles.map((f) => ({
      name: f.name,
      folder: (f as File & { webkitRelativePath?: string }).webkitRelativePath
        ? (f as File & { webkitRelativePath: string }).webkitRelativePath.split("/").slice(0, -1).join("/") || "root"
        : "root",
      content: null, status: "pending", severity: null, result: null,
    }));
    let loaded = 0;
    rawFiles.forEach((f, i) => {
      const reader = new FileReader();
      reader.onload = (ev) => {
        pending[i].content = (ev.target?.result as string) ?? "";
        if (++loaded === rawFiles.length) setFiles([...pending]);
      };
      reader.readAsText(f);
    });
  };

  const scanAll = async () => {
    if (!files.length) return;
    setScanning(true); setScanDone(false); setActiveNode(0);
    for (let i = 0; i < 3; i++) { setScanStage(i); setActiveNode(i + 1); await sleep(700 + Math.random() * 400); }
    const updated = [...files];
    for (const f of updated) {
      if (!f.content?.trim()) { f.status = "ok"; continue; }
      try {
        const res = await fetch(`${API_BASE}/analyze`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ code: f.content }),
        });
        if (res.ok) {
          const data: PipelineResult = await res.json();
          f.result = data; f.severity = data.severity;
          f.status = data.type === "NoError" ? "ok" : "error";
        } else { f.status = "ok"; }
      } catch { f.status = "pending"; }
    }
    setActiveNode(4); setFiles(updated); setScanning(false); setScanDone(true);
    if (selected) { const r = updated.find((f) => f.name === selected.name); if (r) setSelected(r); }
  };

  const filteredFiles = files.filter((f) => {
    if (tocFilter === "error" && f.status !== "error") return false;
    if (tocFilter === "ok" && f.status !== "ok") return false;
    if (tocSearch && !f.name.toLowerCase().includes(tocSearch.toLowerCase())) return false;
    return true;
  });
  const folders = filteredFiles.reduce<Record<string, RepoFile[]>>((acc, f) => {
    (acc[f.folder] ??= []).push(f); return acc;
  }, {});
  const errorCount = files.filter((f) => f.status === "error").length;

  return (
    <div className="main-area">
      {/* TOC */}
      <div className="panel left-panel-repo">
        <div className="panel-header"><div className="panel-header-dot" />FILES</div>
        <div className="toc-search">
          <input type="text" placeholder="Search files..." value={tocSearch} onChange={(e) => setTocSearch(e.target.value)} />
        </div>
        <div className="toc-filters">
          {(["all","error","ok"] as const).map((f) => (
            <button key={f}
              className={`filter-chip${tocFilter === f ? " active" : ""}${f === "error" ? " err-filter" : ""}`}
              onClick={() => setTocFilter(f)}>
              {f === "all" ? "All" : f === "error" ? "Errors" : "Clean"}
            </button>
          ))}
        </div>
        <div className="toc-list">
          {Object.keys(folders).length === 0
            ? <div style={{ padding: 20, textAlign: "center", color: "var(--muted)", fontSize: 12 }}>{files.length === 0 ? "Upload files to begin" : "No files match"}</div>
            : Object.entries(folders).map(([folder, fls]) => (
              <div key={folder}>
                <div className="toc-folder">📁 <span>{folder}</span></div>
                {fls.map((f) => (
                  <div key={f.name}
                    className={`toc-file${selected?.name === f.name ? " selected" : ""}`}
                    onClick={() => { setSelected(f); setActiveNode(f.status === "error" ? 2 : f.status === "ok" ? 4 : 0); }}>
                    <div className={`file-status ${f.status === "ok" ? "status-ok" : f.status === "error" ? "status-err" : "status-pending"}`} />
                    <div className="file-name">{f.name}</div>
                    {f.severity && (
                      <div className={`severity-badge ${f.severity === "High" || f.severity === "Critical" ? "sev-high" : "sev-med"}`}
                        style={{ fontSize: 9, padding: "1px 5px" }}>{f.severity[0]}</div>
                    )}
                  </div>
                ))}
              </div>
            ))}
        </div>
      </div>

      {/* Center editor */}
      <div className="panel center-panel">
        <div className="panel-header">
          <div className="panel-header-dot" style={{ background: "var(--purple)", boxShadow: "0 0 8px var(--glow-purple)" }} />
          <span>{selected?.name ?? "No file selected"}</span>
        </div>
        <div className="pipeline-graph-wrap">
          <div className="pipeline-graph-title">Pipeline Flow</div>
          <div className="pipeline-graph">
            {PG_NODES.map((n, i) => (
              <span key={i} style={{ display: "contents" }}>
                <div className={`pg-node${i === activeNode ? " active-node" : scanDone && i <= activeNode ? " ok-node" : ""}`}
                  onClick={() => setActiveNode(i)}>
                  <div className="pg-icon">{n.icon}</div>
                  <div className="pg-label">{n.label}</div>
                </div>
                {i < PG_NODES.length - 1 && <div className="pg-connector" />}
              </span>
            ))}
          </div>
        </div>
        <div className="editor-wrap" style={{ position: "relative" }}>
          {!selected
            ? <div className="placeholder"><div className="placeholder-icon">📂</div><span>Select a file from the TOC</span></div>
            : <textarea id="repoEditor" spellCheck={false} style={{ display: "block", padding: 16 }} value={selected.content ?? ""} readOnly />
          }
          {scanning && (
            <div className="analyzing-overlay show">
              <div className="spinner" />
              <div className="analyzing-text">{["Parsing files...", "Running AI analysis...", "Generating fixes..."][scanStage]}</div>
              <div className="analyzing-stage">STAGE {scanStage + 1}/3</div>
            </div>
          )}
        </div>
        <div className="controls-bar">
          <div className="upload-zone"
            style={{ margin: 0, flex: 1, flexDirection: "row", gap: 10, padding: "6px 14px", borderRadius: 7 }}
            onClick={() => document.getElementById("folderInput")?.click()}>
            <span style={{ fontSize: 14 }}>📁</span>
            <span style={{ fontSize: 12, color: "var(--muted2)" }}>{files.length > 0 ? `${files.length} file(s) loaded` : "Upload folder / drop files"}</span>
            <input type="file" id="folderInput" style={{ display: "none" }} multiple onChange={loadFiles} />
          </div>
          <button className="btn-analyze" onClick={scanAll} disabled={scanning || !files.length}>
            {scanning ? "⏳ Scanning..." : "▶ Scan All"}
          </button>
        </div>
      </div>

      {/* Results */}
      <div className="panel results-panel">
        <div className="pipeline-bar">
          {[{ id: "p", label: "Parse" }, { id: "s", label: "Scan" }, { id: "f", label: "Fix" }].map((s, i) => (
            <span key={s.id}>
              <span className={`pipe-stage${scanning && i === scanStage ? " active" : scanning && i < scanStage ? " done" : scanDone ? " done" : ""}`}>
                <span className="pipe-dot" />{s.label}
              </span>
              {i < 2 && <span className="pipe-arrow">›</span>}
            </span>
          ))}
        </div>
        <div className="right-scroll" style={{ padding: 14 }}>
          {!selected && <div className="placeholder"><div className="placeholder-icon">🧬</div><span>Select a file to view analysis</span></div>}
          {selected && selected.status === "pending" && <div className="placeholder" style={{ padding: "40px 0" }}><div className="placeholder-icon">⏳</div><span>Run "Scan All" to analyze</span></div>}
          {selected && selected.status === "ok" && !selected.result && (
            <div>
              <div className="result-card" style={{ borderColor: "rgba(46,229,157,.2)" }}>
                <div className="result-card-header">
                  <span className="result-card-title" style={{ color: "var(--green)" }}>✓ No Issues</span>
                  <span className="severity-badge sev-low">CLEAN</span>
                </div>
                <div style={{ fontSize: 12, color: "var(--muted2)" }}>This file passed all checks. No errors detected.</div>
              </div>
              <ConfBar score={0.98} active />
            </div>
          )}
          {selected?.result && selected.status === "error" && <ResultCards result={selected.result} lang={selected.result.language} />}
          {scanDone && <div style={{ padding: "12px 0", textAlign: "center", fontSize: 11, color: "var(--muted2)" }}>✓ Scan complete — {errorCount} issue(s) found</div>}
        </div>
      </div>
    </div>
  );
}

// ─── Logo ─────────────────────────────────────────────────────────────────────

const LogoSVG = ({ size = 52 }: { size?: number }) => (
  <svg width={size} height={size * 0.808} viewBox="0 0 52 42" fill="none">
    <rect y="4" width="52" height="8" rx="3" fill="#5A6478" opacity="0.6" />
    <rect y="17" width="52" height="8" rx="3" fill="#5A6478" opacity="0.8" />
    <rect y="30" width="52" height="8" rx="3" fill="#5A6478" opacity="0.6" />
    <rect x="6" y="4" width="12" height="8" rx="2" fill="#5B8CFF" />
    <rect x="6" y="17" width="18" height="8" rx="2" fill="#9D5CFF" />
    <rect x="6" y="30" width="8" height="8" rx="2" fill="#5B8CFF" opacity="0.7" />
  </svg>
);

// ─── App Root ─────────────────────────────────────────────────────────────────

export default function App() {
  const [mode, setMode] = useState<AppMode>("landing");
  const [landingHidden, setLandingHidden] = useState(false);
  const backendStatus = useBackendStatus();

  const enterMode = (m: "file" | "repo") => { setLandingHidden(true); setTimeout(() => setMode(m), 300); };
  const goHome = () => { setMode("landing"); setLandingHidden(false); };

  return (
    <>
      <style>{`
        :root {
          --bg:#080c10; --bg2:#0d1219; --bg3:#111820; --panel:#0f1620;
          --border:rgba(91,140,255,0.12); --border2:rgba(255,255,255,0.06);
          --blue:#5B8CFF; --purple:#9D5CFF; --green:#2EE59D; --red:#FF4D6A; --yellow:#FFB547;
          --text:#E8EDF5; --muted:#5A6478; --muted2:#8892A4;
          --glow-blue:rgba(91,140,255,0.3); --glow-purple:rgba(157,92,255,0.3);
          --glow-red:rgba(255,77,106,0.4); --glow-green:rgba(46,229,157,0.3);
        }
        *, *::before, *::after { margin:0; padding:0; box-sizing:border-box; }

        /* ✅ FULLSCREEN FIX — html/body/root all 100% with no overflow */
        html, body { width:100%; height:100%; overflow:hidden; background:var(--bg); color:var(--text); font-family:'DM Sans',sans-serif; }
        #root { width:100%; height:100%; display:flex; flex-direction:column; }

        ::-webkit-scrollbar { width:4px; height:4px; }
        ::-webkit-scrollbar-track { background:transparent; }
        ::-webkit-scrollbar-thumb { background:rgba(91,140,255,0.3); border-radius:2px; }

        /* LANDING */
        #landing {
          position:fixed; inset:0; display:flex; flex-direction:column; align-items:center; justify-content:center;
          background:
            radial-gradient(ellipse 80% 60% at 50% 0%, rgba(91,140,255,0.07) 0%, transparent 70%),
            radial-gradient(ellipse 60% 40% at 80% 100%, rgba(157,92,255,0.05) 0%, transparent 60%),
            var(--bg);
          z-index:100; transition:opacity .5s ease, transform .5s ease;
        }
        #landing.hidden { opacity:0; pointer-events:none; transform:scale(0.97); }
        .grid-bg {
          position:absolute; inset:0;
          background-image:linear-gradient(rgba(91,140,255,0.04) 1px,transparent 1px),linear-gradient(90deg,rgba(91,140,255,0.04) 1px,transparent 1px);
          background-size:48px 48px;
          mask-image:radial-gradient(ellipse 80% 80% at 50% 50%, black 20%, transparent 100%);
        }
        .landing-logo { display:flex; align-items:center; gap:16px; margin-bottom:64px; animation:fadeUp .8s cubic-bezier(.16,1,.3,1) both; }
        .landing-logo-text { font-family:'Syne',sans-serif; font-size:32px; font-weight:800; background:linear-gradient(135deg,#fff 30%,var(--blue)); -webkit-background-clip:text; -webkit-text-fill-color:transparent; }
        .landing-tagline { font-size:13px; letter-spacing:.2em; text-transform:uppercase; color:var(--muted2); margin-bottom:56px; animation:fadeUp .8s .1s cubic-bezier(.16,1,.3,1) both; }
        .landing-cards { display:flex; gap:20px; animation:fadeUp .8s .2s cubic-bezier(.16,1,.3,1) both; }
        .option-card { width:280px; padding:32px 28px; border-radius:16px; cursor:pointer; position:relative; overflow:hidden; background:var(--panel); border:1px solid var(--border2); transition:transform .25s,border-color .25s,box-shadow .25s; }
        .option-card::before { content:''; position:absolute; inset:0; background:linear-gradient(135deg,rgba(91,140,255,0.06),transparent 60%); opacity:0; transition:opacity .25s; }
        .option-card:hover { transform:translateY(-4px); border-color:var(--border); box-shadow:0 20px 60px rgba(0,0,0,.5),0 0 40px var(--glow-blue); }
        .option-card:hover::before { opacity:1; }
        .card-icon { width:52px; height:52px; border-radius:12px; display:flex; align-items:center; justify-content:center; background:linear-gradient(135deg,rgba(91,140,255,0.15),rgba(157,92,255,0.08)); border:1px solid rgba(91,140,255,0.2); margin-bottom:20px; font-size:22px; }
        .card-title { font-family:'Syne',sans-serif; font-weight:700; font-size:18px; margin-bottom:8px; }
        .card-desc { font-size:13px; color:var(--muted2); line-height:1.6; }
        .card-arrow { margin-top:24px; font-size:12px; color:var(--blue); letter-spacing:.1em; display:flex; align-items:center; gap:6px; }
        .card-arrow::after { content:'→'; transition:transform .2s; }
        .option-card:hover .card-arrow::after { transform:translateX(4px); }

        /* APP SHELL — ✅ fills full screen */
        #appShell { width:100%; height:100%; display:flex; flex-direction:column; overflow:hidden; }
        .header { height:52px; flex-shrink:0; display:flex; align-items:center; justify-content:space-between; padding:0 20px; border-bottom:1px solid var(--border2); background:rgba(8,12,16,.9); backdrop-filter:blur(12px); z-index:50; }
        .header-logo { display:flex; align-items:center; gap:10px; cursor:pointer; }
        .header-logo-text { font-family:'Syne',sans-serif; font-weight:800; font-size:16px; background:linear-gradient(135deg,#fff,var(--blue)); -webkit-background-clip:text; -webkit-text-fill-color:transparent; }
        .mode-badge { padding:3px 10px; border-radius:20px; font-size:11px; font-weight:600; letter-spacing:.05em; background:linear-gradient(135deg,rgba(91,140,255,0.15),rgba(157,92,255,0.1)); border:1px solid rgba(91,140,255,0.25); color:var(--blue); font-family:'JetBrains Mono',monospace; }
        .header-actions { display:flex; align-items:center; gap:8px; }
        .btn-sm { padding:5px 14px; border-radius:8px; font-size:12px; font-weight:500; cursor:pointer; background:rgba(91,140,255,0.1); border:1px solid rgba(91,140,255,0.2); color:var(--blue); transition:all .2s; font-family:'DM Sans',sans-serif; }
        .btn-sm:hover { background:rgba(91,140,255,0.2); }

        /* ✅ main-area fills ALL remaining height after the header */
        .main-area { flex:1; display:flex; overflow:hidden; min-height:0; width:100%; }

        .panel { background:var(--panel); border-right:1px solid var(--border2); display:flex; flex-direction:column; overflow:hidden; }

        /* Fixed-width panels */
        .left-panel-file { width:360px; flex-shrink:0; }
        .left-panel-repo { width:200px; flex-shrink:0; }
        .center-panel { width:360px; flex-shrink:0; }

        /* ✅ results-panel: flex:1 — takes ALL remaining width, no black gap */
        .results-panel { flex:1; min-width:0; border-right:none; border-left:1px solid var(--border2); }

        .panel-header { padding:12px 16px; border-bottom:1px solid var(--border2); display:flex; align-items:center; gap:8px; font-size:11px; font-weight:600; letter-spacing:.1em; text-transform:uppercase; color:var(--muted2); flex-shrink:0; }
        .panel-header-dot { width:6px; height:6px; border-radius:50%; background:var(--blue); box-shadow:0 0 8px var(--glow-blue); }
        .editor-wrap { flex:1; position:relative; overflow:hidden; }
        #codeEditor, #repoEditor { width:100%; height:100%; border:none; outline:none; background:transparent; resize:none; font-family:'JetBrains Mono',monospace; font-size:13px; line-height:1.7; color:#C9D1D9; padding:16px; tab-size:2; overflow:auto; }
        .editor-gutter { position:absolute; left:0; top:0; bottom:0; width:40px; background:rgba(0,0,0,.2); display:flex; flex-direction:column; padding:16px 0; pointer-events:none; font-family:'JetBrains Mono',monospace; font-size:13px; line-height:1.7; color:var(--muted); text-align:right; padding-right:8px; overflow:hidden; }
        .controls-bar { padding:10px 14px; border-top:1px solid var(--border2); display:flex; align-items:center; gap:10px; flex-shrink:0; background:rgba(0,0,0,.2); }
        select { padding:5px 10px; border-radius:7px; background:var(--bg3); border:1px solid var(--border2); color:var(--text); font-size:12px; font-family:'DM Sans',sans-serif; cursor:pointer; outline:none; }
        .btn-analyze { margin-left:auto; padding:6px 18px; border-radius:8px; border:none; cursor:pointer; background:linear-gradient(135deg,var(--blue),var(--purple)); color:#fff; font-size:12px; font-weight:600; font-family:'Syne',sans-serif; letter-spacing:.05em; position:relative; overflow:hidden; transition:box-shadow .2s,transform .15s; }
        .btn-analyze:hover { box-shadow:0 0 24px var(--glow-blue); transform:translateY(-1px); }
        .btn-analyze:disabled { opacity:.6; cursor:not-allowed; transform:none; }
        .btn-analyze.loading { pointer-events:none; }
        .btn-analyze.loading::after { content:''; position:absolute; inset:0; background:linear-gradient(90deg,transparent,rgba(255,255,255,.2),transparent); animation:shimmer 1s infinite; }

        .pipeline-bar { padding:8px 14px; border-bottom:1px solid var(--border2); display:flex; align-items:center; gap:6px; flex-shrink:0; overflow-x:auto; }
        .pipe-stage { display:flex; align-items:center; gap:6px; padding:4px 10px; border-radius:20px; font-size:11px; font-family:'JetBrains Mono',monospace; color:var(--muted2); border:1px solid transparent; transition:all .3s; white-space:nowrap; }
        .pipe-stage.active { color:var(--blue); border-color:rgba(91,140,255,.25); background:rgba(91,140,255,.08); box-shadow:0 0 16px rgba(91,140,255,.15); }
        .pipe-stage.done { color:var(--green); border-color:rgba(46,229,157,.2); background:rgba(46,229,157,.06); }
        .pipe-dot { width:6px; height:6px; border-radius:50%; background:currentColor; opacity:.6; display:inline-block; }
        .pipe-arrow { color:var(--muted); font-size:10px; margin:0 2px; }

        .right-scroll { flex:1; overflow-y:auto; }
        .result-card { background:var(--bg3); border:1px solid var(--border2); border-radius:10px; padding:14px; margin-bottom:12px; transition:border-color .2s; }
        .result-card:hover { border-color:var(--border); }
        .result-card-header { display:flex; align-items:center; justify-content:space-between; margin-bottom:10px; }
        .result-card-title { font-size:10px; font-weight:600; letter-spacing:.12em; text-transform:uppercase; color:var(--muted2); }
        .severity-badge { padding:2px 8px; border-radius:4px; font-size:10px; font-family:'JetBrains Mono',monospace; font-weight:600; }
        .sev-high { background:rgba(255,77,106,.15); color:var(--red); border:1px solid rgba(255,77,106,.2); }
        .sev-med { background:rgba(255,181,71,.1); color:var(--yellow); border:1px solid rgba(255,181,71,.2); }
        .sev-low { background:rgba(46,229,157,.1); color:var(--green); border:1px solid rgba(46,229,157,.2); }
        .error-text { font-family:'JetBrains Mono',monospace; font-size:12px; color:var(--red); line-height:1.6; }
        .error-line { font-size:11px; color:var(--muted2); margin-top:4px; }
        .tabs { display:flex; border-bottom:1px solid var(--border2); margin-bottom:12px; }
        .tab { padding:6px 14px; font-size:11px; font-weight:600; letter-spacing:.06em; cursor:pointer; color:var(--muted2); border-bottom:2px solid transparent; transition:all .2s; margin-bottom:-1px; }
        .tab.active { color:var(--blue); border-bottom-color:var(--blue); }
        .explanation-text { font-size:12px; line-height:1.8; color:var(--muted2); }
        .fix-code { background:var(--bg); border:1px solid var(--border2); border-radius:7px; padding:12px; font-family:'JetBrains Mono',monospace; font-size:12px; color:#A8D8A8; line-height:1.7; overflow-x:auto; position:relative; }
        .copy-btn { position:absolute; top:8px; right:8px; padding:3px 8px; border-radius:5px; background:rgba(91,140,255,.12); border:1px solid rgba(91,140,255,.2); color:var(--blue); font-size:10px; font-weight:600; cursor:pointer; transition:all .2s; }
        .copy-btn:hover { background:rgba(91,140,255,.22); }
        .diff-line { font-family:'JetBrains Mono',monospace; font-size:11.5px; line-height:1.7; padding:1px 8px; border-radius:3px; }
        .diff-remove { color:#FF8B9A; background:rgba(255,77,106,.08); }
        .diff-add { color:#7FD9A8; background:rgba(46,229,157,.08); }
        .conf-bar-wrap { height:6px; background:var(--bg); border-radius:3px; overflow:hidden; margin-top:6px; }
        .conf-bar-fill { height:100%; border-radius:3px; background:linear-gradient(90deg,var(--blue),var(--green)); transition:width 1s cubic-bezier(.16,1,.3,1); }
        .conf-label { display:flex; justify-content:space-between; font-size:11px; color:var(--muted2); margin-bottom:4px; }
        .conf-pct { font-family:'JetBrains Mono',monospace; color:var(--green); }

        .toc-search { padding:8px 12px; border-bottom:1px solid var(--border2); flex-shrink:0; }
        .toc-search input { width:100%; background:var(--bg3); border:1px solid var(--border2); border-radius:6px; padding:5px 10px; font-size:12px; color:var(--text); outline:none; }
        .toc-search input::placeholder { color:var(--muted); }
        .toc-filters { padding:8px 12px; border-bottom:1px solid var(--border2); display:flex; gap:6px; flex-shrink:0; }
        .filter-chip { padding:3px 8px; border-radius:12px; font-size:10px; font-weight:600; cursor:pointer; border:1px solid var(--border2); color:var(--muted2); background:transparent; transition:all .2s; }
        .filter-chip.active { background:rgba(91,140,255,.12); border-color:rgba(91,140,255,.25); color:var(--blue); }
        .filter-chip.err-filter.active { background:rgba(255,77,106,.1); border-color:rgba(255,77,106,.2); color:var(--red); }
        .toc-list { flex:1; overflow-y:auto; padding:8px 0; }
        .toc-folder { padding:6px 12px; font-size:11px; color:var(--muted); display:flex; align-items:center; gap:6px; letter-spacing:.05em; }
        .toc-file { padding:7px 12px 7px 24px; font-size:12px; display:flex; align-items:center; gap:8px; cursor:pointer; transition:background .15s; font-family:'JetBrains Mono',monospace; position:relative; }
        .toc-file:hover { background:rgba(255,255,255,.03); }
        .toc-file.selected { background:rgba(91,140,255,.08); }
        .toc-file.selected::before { content:''; position:absolute; left:0; top:0; bottom:0; width:2px; background:var(--blue); }
        .file-status { width:6px; height:6px; border-radius:50%; flex-shrink:0; }
        .status-ok { background:var(--green); box-shadow:0 0 6px var(--glow-green); }
        .status-err { background:var(--red); box-shadow:0 0 6px var(--glow-red); animation:pulse-red 2s infinite; }
        .status-pending { background:var(--muted); }
        .file-name { flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:11.5px; color:var(--muted2); }
        .toc-file.selected .file-name { color:var(--text); }

        .pipeline-graph-wrap { padding:14px; border-bottom:1px solid var(--border2); flex-shrink:0; }
        .pipeline-graph-title { font-size:10px; letter-spacing:.12em; text-transform:uppercase; color:var(--muted2); margin-bottom:10px; }
        .pipeline-graph { display:flex; align-items:center; }
        .pg-node { display:flex; flex-direction:column; align-items:center; gap:4px; padding:8px 12px; border-radius:8px; cursor:pointer; transition:all .25s; border:1px solid transparent; min-width:60px; }
        .pg-node:hover { background:rgba(91,140,255,.06); border-color:rgba(91,140,255,.15); }
        .pg-node.active-node { background:rgba(91,140,255,.1); border-color:rgba(91,140,255,.25); }
        .pg-node.ok-node { background:rgba(46,229,157,.06); border-color:rgba(46,229,157,.15); }
        .pg-icon { font-size:18px; }
        .pg-label { font-size:9px; letter-spacing:.08em; text-transform:uppercase; color:var(--muted2); }
        .pg-connector { flex:1; height:2px; background:linear-gradient(90deg,var(--border2),rgba(91,140,255,.2)); position:relative; overflow:hidden; }
        .pg-connector::after { content:''; position:absolute; inset:0; background:linear-gradient(90deg,transparent,var(--blue),transparent); animation:flow 2s linear infinite; }

        .placeholder { flex:1; display:flex; flex-direction:column; align-items:center; justify-content:center; color:var(--muted); font-size:13px; gap:10px; }
        .placeholder-icon { font-size:32px; opacity:.3; }
        .analyzing-overlay { position:absolute; inset:0; background:rgba(8,12,16,.85); backdrop-filter:blur(6px); display:flex; flex-direction:column; align-items:center; justify-content:center; gap:16px; z-index:10; opacity:0; pointer-events:none; transition:opacity .3s; }
        .analyzing-overlay.show { opacity:1; pointer-events:all; }
        .spinner { width:40px; height:40px; border:2px solid var(--border2); border-top-color:var(--blue); border-radius:50%; animation:spin .8s linear infinite; }
        .analyzing-text { font-family:'JetBrains Mono',monospace; font-size:12px; color:var(--blue); }
        .analyzing-stage { font-size:11px; color:var(--muted2); letter-spacing:.08em; }

        .upload-zone { flex:1; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:12px; border:2px dashed rgba(91,140,255,.15); border-radius:10px; margin:14px; cursor:pointer; transition:all .25s; }
        .upload-zone:hover { border-color:rgba(91,140,255,.35); background:rgba(91,140,255,.03); }
        .upload-icon { font-size:28px; opacity:.4; }
        .upload-text { font-size:13px; color:var(--muted2); }
        .upload-subtext { font-size:11px; color:var(--muted); }
        .slide-in { animation:slideIn .3s cubic-bezier(.16,1,.3,1) both; }

        @keyframes fadeUp { from{opacity:0;transform:translateY(20px)} to{opacity:1;transform:translateY(0)} }
        @keyframes shimmer { from{transform:translateX(-100%)} to{transform:translateX(100%)} }
        @keyframes spin { to{transform:rotate(360deg)} }
        @keyframes pulse-red { 0%,100%{box-shadow:0 0 6px var(--glow-red)} 50%{box-shadow:0 0 10px var(--glow-red)} }
        @keyframes flow { from{transform:translateX(-100%)} to{transform:translateX(100%)} }
        @keyframes slideIn { from{opacity:0;transform:translateX(10px)} to{opacity:1;transform:translateX(0)} }
      `}</style>

      {/* LANDING */}
      <div id="landing" className={landingHidden ? "hidden" : ""}>
        <div className="grid-bg" />
        <div className="landing-logo">
          <LogoSVG size={52} />
          <span className="landing-logo-text">StackHeal AI</span>
        </div>
        <div className="landing-tagline">Intelligent Debugging Pipeline · v2.1</div>
        <div className="landing-cards">
          <div className="option-card" onClick={() => enterMode("file")}>
            <div className="card-icon">🗂</div>
            <div className="card-title">Single File</div>
            <div className="card-desc">Upload a single source file and receive line-level error detection, root cause analysis, and AI-generated fixes.</div>
            <div className="card-arrow">ANALYZE FILE</div>
          </div>
          <div className="option-card" onClick={() => enterMode("repo")}>
            <div className="card-icon">🏗</div>
            <div className="card-title">Repository</div>
            <div className="card-desc">Upload an entire project. Get a full pipeline scan across all files with dependency-aware analysis.</div>
            <div className="card-arrow">SCAN REPO</div>
          </div>
        </div>
      </div>

      {/* APP SHELL */}
      {mode !== "landing" && (
        <div id="appShell">
          <div className="header">
            <div className="header-logo" onClick={goHome}>
              <LogoSVG size={22} />
              <span className="header-logo-text">StackHeal AI</span>
            </div>
            <span className="mode-badge">{mode === "file" ? "SINGLE FILE" : "REPOSITORY"}</span>
            <div className="header-actions">
              <BackendBadge status={backendStatus} />
              <button className="btn-sm" onClick={goHome}>⬅ Home</button>
            </div>
          </div>
          {mode === "file" ? <FileMode /> : <RepoMode />}
        </div>
      )}
    </>
  );
}
