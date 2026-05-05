const { useEffect, useMemo, useRef, useState } = React;

const AUTO_REFRESH_MS = 30000;

const toneStyles = {
  neutral: "border-slate-700/70 bg-slate-900/60 text-slate-200",
  success: "border-emerald-500/30 bg-emerald-500/10 text-emerald-200",
  accent: "border-sky-400/30 bg-sky-400/10 text-sky-200",
  warning: "border-amber-400/30 bg-amber-400/10 text-amber-200",
  danger: "border-rose-400/30 bg-rose-400/10 text-rose-200",
  protective: "border-cyan-400/30 bg-cyan-400/10 text-cyan-200",
  operational: "border-amber-300/30 bg-amber-300/10 text-amber-100",
  critical: "border-rose-400/30 bg-rose-400/10 text-rose-200",
  clean: "border-emerald-400/30 bg-emerald-400/10 text-emerald-200",
};

function cn(...parts) {
  return parts.filter(Boolean).join(" ");
}

function safeNumber(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function fmtNumber(value, digits = 0) {
  const parsed = safeNumber(value, Number.NaN);
  if (!Number.isFinite(parsed)) return "-";
  return parsed.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function fmtCompact(value, digits = 1) {
  const parsed = safeNumber(value, Number.NaN);
  if (!Number.isFinite(parsed)) return "-";
  return new Intl.NumberFormat(undefined, {
    notation: "compact",
    maximumFractionDigits: digits,
  }).format(parsed);
}

function fmtPct(value, digits = 1) {
  const parsed = safeNumber(value, Number.NaN);
  if (!Number.isFinite(parsed)) return "-";
  return `${parsed.toFixed(digits)}%`;
}

function fmtR(value, digits = 2) {
  const parsed = safeNumber(value, Number.NaN);
  if (!Number.isFinite(parsed)) return "-";
  return `${parsed.toFixed(digits)}R`;
}

function fmtDateTime(value) {
  if (!value) return "-";
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return String(value);
  return dt.toLocaleString();
}

function modeLabel(mode) {
  const normalized = String(mode || "").trim().toLowerCase();
  if (normalized === "t1") return "T+1";
  if (normalized === "swing") return "Swing";
  if (normalized === "intraday") return "Intraday";
  return normalized || "-";
}

function statusTone(status) {
  const normalized = String(status || "").trim().toLowerCase();
  if (["ok", "success", "healthy", "clear", "risk_on", "pass", "succeeded", "clean"].includes(normalized)) return "success";
  if (["warning", "protective_warning", "operational_warning", "paper", "paper_only"].includes(normalized)) return "warning";
  if (["failed", "critical_failure", "error", "risk_off", "blocked", "cooldown", "triggered"].includes(normalized)) return "danger";
  return "neutral";
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      message = await response.text();
    } catch {}
    throw new Error(message);
  }
  return response.json();
}

function useReducedMotion() {
  const [reducedMotion, setReducedMotion] = useState(false);
  useEffect(() => {
    if (!window.matchMedia) return undefined;
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReducedMotion(Boolean(media.matches));
    update();
    media.addEventListener?.("change", update);
    return () => media.removeEventListener?.("change", update);
  }, []);
  return reducedMotion;
}

function useScrollProgress() {
  useEffect(() => {
    const onScroll = () => {
      const total = document.documentElement.scrollHeight - window.innerHeight;
      const next = total > 0 ? Math.min(100, Math.max(0, (window.scrollY / total) * 100)) : 0;
      document.documentElement.style.setProperty("--premium-progress", `${next}%`);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
    };
  }, []);
}

function useParallaxBackground(disabled) {
  useEffect(() => {
    if (disabled) {
      document.documentElement.style.setProperty("--orb-shift-x", "0px");
      document.documentElement.style.setProperty("--orb-shift-y", "0px");
      return undefined;
    }
    const onMove = (event) => {
      const offsetX = ((event.clientX / window.innerWidth) - 0.5) * 20;
      const offsetY = ((event.clientY / window.innerHeight) - 0.5) * 20;
      document.documentElement.style.setProperty("--orb-shift-x", `${offsetX}px`);
      document.documentElement.style.setProperty("--orb-shift-y", `${offsetY}px`);
    };
    window.addEventListener("mousemove", onMove);
    return () => window.removeEventListener("mousemove", onMove);
  }, [disabled]);
}

function StatusPill({ label, tone = "neutral", className = "" }) {
  return (
    <span className={cn("inline-flex items-center gap-2 rounded-full border px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.22em]", toneStyles[tone] || toneStyles.neutral, className)}>
      <span className="premium-status-dot" style={{ color: "currentColor" }} />
      {label}
    </span>
  );
}

function CounterNumber({ value, digits = 0, prefix = "", suffix = "", reducedMotion = false }) {
  const ref = useRef(null);
  const stateRef = useRef({ value: 0 });

  useEffect(() => {
    if (!ref.current) return undefined;
    const target = safeNumber(value, 0);
    const render = (current) => {
      ref.current.textContent = `${prefix}${fmtNumber(current, digits)}${suffix}`;
    };
    if (reducedMotion || !window.gsap) {
      stateRef.current.value = target;
      render(target);
      return undefined;
    }

    // Counter tween: animate KPI changes smoothly so refreshes feel continuous instead of snapping.
    const tween = window.gsap.to(stateRef.current, {
      value: target,
      duration: 1.15,
      ease: "power2.out",
      onUpdate: () => render(stateRef.current.value),
      onComplete: () => {
        stateRef.current.value = target;
        render(target);
      },
    });
    return () => tween.kill();
  }, [digits, prefix, reducedMotion, suffix, value]);

  return <span ref={ref}>{`${prefix}${fmtNumber(value, digits)}${suffix}`}</span>;
}

function buildSparkPath(values, width = 220, height = 72, padding = 8) {
  const cleaned = values.map((value) => safeNumber(value, 0));
  if (cleaned.length === 0) return { line: "", area: "" };
  const min = Math.min(...cleaned);
  const max = Math.max(...cleaned);
  const span = Math.max(max - min, 1);
  const step = cleaned.length > 1 ? (width - padding * 2) / (cleaned.length - 1) : 0;
  const points = cleaned.map((value, index) => {
    const x = padding + index * step;
    const y = height - padding - ((value - min) / span) * (height - padding * 2);
    return [x, y];
  });
  const line = points.map(([x, y], index) => `${index === 0 ? "M" : "L"}${x},${y}`).join(" ");
  const area = `${line} L ${width - padding},${height - padding} L ${padding},${height - padding} Z`;
  return { line, area };
}

function Sparkline({ values, lineColor = "#2dd4bf" }) {
  const { line, area } = useMemo(() => buildSparkPath(values), [values]);
  const gradientId = `spark-${lineColor.replace("#", "")}`;
  return (
    <div className="h-20 w-full">
      <svg viewBox="0 0 220 72" className="h-full w-full overflow-visible">
        <defs>
          <linearGradient id={gradientId} x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor={lineColor} stopOpacity="0.26" />
            <stop offset="100%" stopColor={lineColor} stopOpacity="0.03" />
          </linearGradient>
        </defs>
        <path d={area} fill={`url(#${gradientId})`} />
        <path d={line} fill="none" stroke={lineColor} strokeWidth="2.75" strokeLinecap="round" />
      </svg>
    </div>
  );
}

function SectionHeading({ eyebrow, title, description, action }) {
  return (
    <div className="mb-6 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
      <div className="max-w-2xl">
        <p className="mb-2 font-mono text-[11px] uppercase tracking-[0.34em] text-slate-400">{eyebrow}</p>
        <h2 className="font-display text-2xl font-semibold tracking-tight text-white md:text-3xl">{title}</h2>
        <p className="mt-2 text-sm leading-7 text-slate-400 md:text-base">{description}</p>
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}

function TiltCard({ children, className = "", reducedMotion = false }) {
  const ref = useRef(null);
  const onMouseMove = (event) => {
    if (reducedMotion || !ref.current || window.innerWidth < 1024) return;
    const bounds = ref.current.getBoundingClientRect();
    const px = (event.clientX - bounds.left) / bounds.width - 0.5;
    const py = (event.clientY - bounds.top) / bounds.height - 0.5;
    ref.current.style.transform = `perspective(1200px) rotateX(${(-py * 7).toFixed(2)}deg) rotateY(${(px * 9).toFixed(2)}deg) translateY(-3px)`;
  };
  const reset = () => {
    if (ref.current) ref.current.style.transform = "";
  };
  return (
    <div ref={ref} className={cn("premium-tilt relative rounded-3xl transition-transform duration-300 ease-out", className)} onMouseMove={onMouseMove} onMouseLeave={reset}>
      {children}
    </div>
  );
}

function KpiCard({ label, value, subtext, suffix = "", digits = 0, tone = "accent", reducedMotion = false }) {
  const toneClass = tone === "accent" ? "from-emerald-400/20 via-cyan-400/5 to-transparent" : tone === "warning" ? "from-amber-400/20 via-amber-200/5 to-transparent" : tone === "danger" ? "from-rose-400/18 via-rose-200/5 to-transparent" : "from-slate-300/12 via-slate-200/4 to-transparent";
  return (
    <TiltCard reducedMotion={reducedMotion}>
      <article data-kpi-card className={cn("metric-card-glow glass-panel premium-ring relative overflow-hidden rounded-3xl p-5", "bg-gradient-to-br", toneClass)}>
        <p className="text-sm text-slate-400">{label}</p>
        <div className="mt-3 flex items-end justify-between gap-4">
          <h3 className="font-display text-3xl font-semibold text-white sm:text-4xl">
            <CounterNumber value={value} digits={digits} suffix={suffix} reducedMotion={reducedMotion} />
          </h3>
          <div className={cn("h-2.5 w-2.5 rounded-full", tone === "danger" ? "bg-rose-400" : tone === "warning" ? "bg-amber-300" : "bg-emerald-400")} />
        </div>
        <p className="mt-3 text-sm leading-6 text-slate-400">{subtext}</p>
      </article>
    </TiltCard>
  );
}

function SkeletonBlock({ className = "" }) {
  return <div className={cn("premium-shimmer rounded-2xl", className)} />;
}

function LoadingKpiGrid() {
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      {Array.from({ length: 4 }).map((_, index) => (
        <div key={index} className="glass-panel rounded-3xl p-5">
          <SkeletonBlock className="h-4 w-24" />
          <SkeletonBlock className="mt-4 h-10 w-28" />
          <SkeletonBlock className="mt-4 h-3 w-full" />
          <SkeletonBlock className="mt-2 h-3 w-4/5" />
        </div>
      ))}
    </div>
  );
}

function FilterChip({ label, active, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-full border px-3 py-2 text-xs font-semibold tracking-[0.18em] uppercase transition-all duration-200",
        active
          ? "premium-tab-indicator text-sky-100 shadow-glow"
          : "border-slate-700/70 bg-slate-900/55 text-slate-400 hover:border-slate-500/70 hover:text-slate-200"
      )}
    >
      {label}
    </button>
  );
}

function AnimatedTabPanel({ activeKey, reducedMotion, children }) {
  const ref = useRef(null);
  useEffect(() => {
    if (!ref.current || reducedMotion || !window.gsap) return undefined;
    // Tab switch animation: keep panel changes crisp with a short fade/lift instead of a hard content swap.
    const tween = window.gsap.fromTo(ref.current, { autoAlpha: 0, y: 12 }, { autoAlpha: 1, y: 0, duration: 0.38, ease: "power2.out" });
    return () => tween.kill();
  }, [activeKey, reducedMotion]);
  return <div ref={ref} key={activeKey}>{children}</div>;
}

function MetricList({ items }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {items.map((item) => (
        <div key={item.label} className="glass-panel-soft rounded-2xl p-4">
          <p className="text-xs uppercase tracking-[0.22em] text-slate-500">{item.label}</p>
          <div className="mt-2 flex items-end justify-between gap-4">
            <strong className="text-lg font-semibold text-white">{item.value}</strong>
            {item.tone ? <StatusPill label={item.toneLabel || item.tone} tone={item.tone} className="px-2 py-1 text-[10px]" /> : null}
          </div>
          <p className="mt-2 text-sm text-slate-400">{item.help}</p>
        </div>
      ))}
    </div>
  );
}

function EmptyState({ title, message }) {
  return (
    <div className="glass-panel-soft rounded-3xl border border-dashed border-slate-700/80 p-8 text-center">
      <p className="font-display text-lg text-white">{title}</p>
      <p className="mt-2 text-sm leading-6 text-slate-400">{message}</p>
    </div>
  );
}

function AlertCard({ alert }) {
  const tone = alert.severity === "error" ? "danger" : alert.severity === "warning" ? "warning" : alert.severity === "info" ? "accent" : "neutral";
  return (
    <article className="glass-panel-soft rounded-3xl p-5">
      <div className="flex flex-wrap items-center gap-3">
        <StatusPill label={alert.code || alert.severity || "alert"} tone={tone} className="px-2 py-1 text-[10px]" />
        <h4 className="font-display text-lg font-semibold text-white">{alert.title || "Operator alert"}</h4>
      </div>
      <p className="mt-3 text-sm leading-7 text-slate-300">{alert.message || "No detail provided."}</p>
    </article>
  );
}

function RunCard({ run }) {
  const [open, setOpen] = useState(run.status !== "clean");
  const issues = Array.isArray(run.issues) ? run.issues : [];
  const badgeTone = run.status === "failed" ? "critical" : run.status_category === "protective_warning" ? "protective" : run.status === "warning" ? "operational" : "clean";

  return (
    <article className="glass-panel-soft rounded-3xl p-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-3">
            <h4 className="font-display text-lg font-semibold text-white">{run.run_id}</h4>
            <StatusPill label={run.status} tone={badgeTone} className="px-2 py-1 text-[10px]" />
            <StatusPill label={run.status_category_label || "Run status"} tone={badgeTone === "clean" ? "clean" : badgeTone === "protective" ? "protective" : badgeTone === "operational" ? "warning" : "danger"} className="px-2 py-1 text-[10px]" />
          </div>
          <p className="text-sm leading-7 text-slate-400">{run.status_note || "No run note available."}</p>
          <div className="flex flex-wrap gap-3 text-xs uppercase tracking-[0.2em] text-slate-500">
            <span>Source {run.source || "-"}</span>
            <span>Signals {fmtNumber(run.signals, 0)}</span>
            <span>Events {fmtNumber(run.events, 0)}</span>
            <span>Errors {fmtNumber(run.error_count, 0)}</span>
            <span>Warnings {fmtNumber(run.warning_count, 0)}</span>
          </div>
          <div className="text-xs text-slate-500">Started {fmtDateTime(run.started_at)} · Ended {fmtDateTime(run.ended_at)}</div>
        </div>
        <button type="button" onClick={() => setOpen((value) => !value)} className="inline-flex items-center gap-2 rounded-full border border-slate-700/70 bg-slate-900/70 px-3 py-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-200 transition hover:border-slate-500/80">
          <span className={cn("transition-transform duration-200", open ? "rotate-180" : "")}>?</span>
          {issues.length} issue{issues.length === 1 ? "" : "s"}
        </button>
      </div>

      <div className="overflow-hidden transition-[max-height,opacity,margin] duration-300" style={{ maxHeight: open ? `${issues.length * 180 + 120}px` : "0px", opacity: open ? 1 : 0, marginTop: open ? "1rem" : "0rem" }}>
        <div className="premium-divider mb-4" />
        <div className="space-y-3">
          {issues.length ? issues.map((issue, index) => (
            <div key={`${run.run_id}-${index}`} className="rounded-2xl border border-slate-800/70 bg-slate-950/70 p-4">
              <div className="flex flex-wrap items-center gap-3">
                <StatusPill label={issue.level || "INFO"} tone={issue.level === "ERROR" ? "danger" : issue.category_tone === "protective" ? "protective" : "warning"} className="px-2 py-1 text-[10px]" />
                <strong className="text-sm font-semibold text-white">{issue.summary || issue.message}</strong>
              </div>
              <p className="mt-3 text-sm leading-7 text-slate-300">{issue.detail || "No detail provided."}</p>
            </div>
          )) : <p className="text-sm text-slate-400">This run finished clean with no issue payload.</p>}
        </div>
      </div>
    </article>
  );
}

function SimpleBarChart({ items, color = "bg-emerald-400" }) {
  const maxValue = Math.max(1, ...items.map((item) => safeNumber(item.value, 0)));
  return (
    <div className="space-y-3">
      {items.map((item) => (
        <div key={item.label}>
          <div className="mb-1 flex items-center justify-between gap-3 text-xs uppercase tracking-[0.18em] text-slate-500">
            <span>{item.label}</span>
            <span>{item.display || fmtNumber(item.value, 0)}</span>
          </div>
          <div className="h-2 rounded-full bg-slate-900/80">
            <div className={cn("h-2 rounded-full", color)} style={{ width: `${Math.max(8, (safeNumber(item.value, 0) / maxValue) * 100)}%` }} />
          </div>
        </div>
      ))}
    </div>
  );
}

function DetailChart({ detail, loading }) {
  if (loading) {
    return (
      <div className="glass-panel-soft rounded-3xl p-5">
        <SkeletonBlock className="h-4 w-24" />
        <SkeletonBlock className="mt-5 h-48 w-full rounded-3xl" />
      </div>
    );
  }
  const points = detail?.chart?.points || [];
  const values = points.map((point) => safeNumber(point.close, 0));
  const { line, area } = buildSparkPath(values, 540, 220, 18);
  return (
    <div className="glass-panel-soft rounded-3xl p-5">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Ticker chart</p>
          <h4 className="mt-1 font-display text-lg font-semibold text-white">{detail?.ticker || "-"}</h4>
        </div>
        <StatusPill label={`${fmtNumber(detail?.bar_count, 0)} bars`} tone="accent" className="px-2 py-1 text-[10px]" />
      </div>
      <div className="relative overflow-hidden rounded-[26px] border border-slate-800/80 bg-slate-950/80 p-3">
        <div className="pointer-events-none absolute inset-x-0 top-0 h-24 bg-gradient-to-b from-emerald-400/8 to-transparent" />
        <svg viewBox="0 0 540 220" className="h-56 w-full">
          <defs>
            <linearGradient id="tickerAreaGradient" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%" stopColor="#2dd4bf" stopOpacity="0.32" />
              <stop offset="100%" stopColor="#2dd4bf" stopOpacity="0.02" />
            </linearGradient>
          </defs>
          <path d={area} fill="url(#tickerAreaGradient)" />
          <path d={line} fill="none" stroke="#38bdf8" strokeWidth="3" strokeLinecap="round" />
        </svg>
      </div>
    </div>
  );
}

function TickerDetailModal({ ticker, open, onClose, reducedMotion }) {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const overlayRef = useRef(null);
  const panelRef = useRef(null);

  useEffect(() => {
    if (!open || !ticker) return undefined;
    setLoading(true);
    setError("");
    setDetail(null);
    api(`/public_detail_${encodeURIComponent(ticker)}.json`)
      .then((payload) => setDetail(payload))
      .catch((err) => setError(err.message || "Failed to load ticker detail."))
      .finally(() => setLoading(false));
    return undefined;
  }, [open, ticker]);

  useEffect(() => {
    if (!open) return undefined;
    document.body.style.overflow = "hidden";
    const onKeyDown = (event) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = "";
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [onClose, open]);

  useEffect(() => {
    if (!open || reducedMotion || !window.gsap) return undefined;
    // Modal entrance: fade the backdrop and lift the panel slightly so detail exploration feels deliberate.
    const ctx = window.gsap.context(() => {
      window.gsap.fromTo(overlayRef.current, { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.22, ease: "power1.out" });
      window.gsap.fromTo(panelRef.current, { autoAlpha: 0, y: 22, scale: 0.985 }, { autoAlpha: 1, y: 0, scale: 1, duration: 0.34, ease: "power3.out" });
    });
    return () => ctx.revert();
  }, [open, reducedMotion]);

  if (!open) return null;
  const stats = detail?.stats || {};
  const levels = detail?.levels || {};
  const latestSignal = detail?.latest_signal || {};
  const reasonBreakdown = detail?.reason_breakdown || [];

  return (
    <div ref={overlayRef} className="modal-backdrop fixed inset-0 z-[120] flex items-end justify-center p-4 sm:items-center">
      <div className="absolute inset-0" onClick={onClose} />
      <div ref={panelRef} className="relative z-10 max-h-[90vh] w-full max-w-6xl overflow-hidden rounded-[32px] border border-slate-700/70 bg-finance-950 shadow-2xl">
        <div className="premium-scrollbar max-h-[90vh] overflow-y-auto">
          <div className="sticky top-0 z-20 border-b border-slate-800/80 bg-finance-950/95 px-5 py-4 backdrop-blur md:px-8">
            <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
              <div>
                <p className="font-mono text-[11px] uppercase tracking-[0.34em] text-slate-500">Ticker intelligence</p>
                <h3 className="mt-2 font-display text-2xl font-semibold text-white">{ticker}</h3>
                <p className="mt-1 text-sm text-slate-400">Decision context, signal levels, and historical bar structure from the current backend snapshot.</p>
              </div>
              <div className="flex flex-wrap items-center gap-3">
                <StatusPill label={modeLabel(latestSignal.mode)} tone="accent" />
                <StatusPill label={`Score ${fmtNumber(latestSignal.score, 2)}`} tone="success" />
                <button type="button" onClick={onClose} className="rounded-full border border-slate-700/70 bg-slate-900/70 px-4 py-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-200 transition hover:border-slate-500/80">Close</button>
              </div>
            </div>
          </div>

          <div className="space-y-6 p-5 md:p-8">
            {error ? <div className="rounded-3xl border border-rose-400/30 bg-rose-500/10 p-5 text-sm text-rose-100">{error}</div> : null}
            <DetailChart detail={detail} loading={loading} />
            <div className="grid gap-5 xl:grid-cols-[1.1fr,0.9fr]">
              <div className="glass-panel-soft rounded-3xl p-5">
                <p className="text-xs uppercase tracking-[0.22em] text-slate-500">Signal levels</p>
                {loading ? <div className="mt-5 grid gap-3 sm:grid-cols-2">{Array.from({ length: 4 }).map((_, index) => <SkeletonBlock key={index} className="h-24 rounded-2xl" />)}</div> : (
                  <div className="mt-5 grid gap-3 sm:grid-cols-2">
                    {[ ["Entry", levels.entry], ["Stop", levels.stop], ["TP1", levels.tp1], ["TP2", levels.tp2] ].map(([label, value]) => (
                      <div key={label} className="rounded-2xl border border-slate-800/80 bg-slate-950/70 p-4">
                        <p className="text-xs uppercase tracking-[0.18em] text-slate-500">{label}</p>
                        <strong className="mt-2 block text-2xl text-white">{fmtNumber(value, 2)}</strong>
                      </div>
                    ))}
                  </div>
                )}
              </div>
              <div className="glass-panel-soft rounded-3xl p-5">
                <p className="text-xs uppercase tracking-[0.22em] text-slate-500">Context metrics</p>
                {loading ? <div className="mt-5 space-y-3">{Array.from({ length: 5 }).map((_, index) => <SkeletonBlock key={index} className="h-14 rounded-2xl" />)}</div> : (
                  <div className="mt-5 space-y-3">
                    {[ ["Last close", fmtNumber(stats.last_close, 2)], ["Change", fmtPct(stats.change_pct, 2)], ["Range low", fmtNumber(stats.min_low, 2)], ["Range high", fmtNumber(stats.max_high, 2)], ["Average volume", fmtCompact(stats.avg_volume, 2)] ].map(([label, value]) => (
                      <div key={label} className="flex items-center justify-between rounded-2xl border border-slate-800/80 bg-slate-950/70 px-4 py-3">
                        <span className="text-sm text-slate-400">{label}</span>
                        <strong className="font-mono text-sm text-slate-100">{value}</strong>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
            <div className="grid gap-5 xl:grid-cols-[0.9fr,1.1fr]">
              <div className="glass-panel-soft rounded-3xl p-5">
                <p className="text-xs uppercase tracking-[0.22em] text-slate-500">Signal rationale</p>
                {loading ? <div className="mt-5 space-y-3">{Array.from({ length: 4 }).map((_, index) => <SkeletonBlock key={index} className="h-14 rounded-2xl" />)}</div> : (
                  <div className="mt-5 space-y-3">
                    {reasonBreakdown.length ? reasonBreakdown.map((item, index) => (
                      <div key={`${item.reason}-${index}`} className="rounded-2xl border border-slate-800/80 bg-slate-950/70 px-4 py-3">
                        <div className="flex items-center justify-between gap-3">
                          <span className="text-sm text-slate-300">{item.reason || item.label || `Reason ${index + 1}`}</span>
                          <strong className="font-mono text-sm text-emerald-200">{fmtNumber(item.score, 2)}</strong>
                        </div>
                      </div>
                    )) : <p className="text-sm text-slate-400">No reason breakdown available for this ticker.</p>}
                  </div>
                )}
              </div>
              <div className="glass-panel-soft rounded-3xl p-5">
                <p className="text-xs uppercase tracking-[0.22em] text-slate-500">Latest signal snapshot</p>
                {loading ? <div className="mt-5 grid gap-3">{Array.from({ length: 5 }).map((_, index) => <SkeletonBlock key={index} className="h-14 rounded-2xl" />)}</div> : (
                  <div className="mt-5 grid gap-3">
                    {[ ["Mode", modeLabel(latestSignal.mode)], ["Score", fmtNumber(latestSignal.score, 2)], ["Size", fmtNumber(latestSignal.size, 2)], ["Reason", latestSignal.reason || "-"], ["Series", detail?.series_type ? `${detail.series_type} · ${detail.timeframe || "-"}` : "-"] ].map(([label, value]) => (
                      <div key={label} className="rounded-2xl border border-slate-800/80 bg-slate-950/70 px-4 py-3">
                        <p className="text-xs uppercase tracking-[0.18em] text-slate-500">{label}</p>
                        <p className="mt-2 text-sm leading-6 text-slate-200">{value}</p>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function SignalsTable({ items, loading, onSelectTicker, query }) {
  if (loading) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 6 }).map((_, index) => (
          <div key={index} className="glass-panel-soft rounded-3xl p-4">
            <SkeletonBlock className="h-4 w-28" />
            <SkeletonBlock className="mt-3 h-3 w-full" />
            <SkeletonBlock className="mt-2 h-3 w-5/6" />
          </div>
        ))}
      </div>
    );
  }

  if (!items.length) {
    return <EmptyState title="No signals matched the active filters" message="Try clearing the search query or lowering the minimum score threshold." />;
  }

  return (
    <>
      <div className="hidden xl:block overflow-hidden rounded-3xl border border-slate-800/80 bg-slate-950/70">
        <div className="premium-scrollbar overflow-x-auto">
          <table className="signal-table min-w-full text-left text-sm">
            <thead className="border-b border-slate-800/80 bg-slate-900/80 text-[11px] uppercase tracking-[0.22em] text-slate-500">
              <tr>
                <th className="px-5 py-4">Ticker</th>
                <th className="px-5 py-4">Mode</th>
                <th className="px-5 py-4">Score</th>
                <th className="px-5 py-4">Prob</th>
                <th className="px-5 py-4">Entry</th>
                <th className="px-5 py-4">Stop</th>
                <th className="px-5 py-4">TP1</th>
                <th className="px-5 py-4">Lots (Kelly)</th>
                <th className="px-5 py-4">Risk IDR</th>
                <th className="px-5 py-4">Reason</th>
              </tr>
            </thead>
            <tbody>
              {items.map((signal) => {
                const activeQuery = query && String(signal.ticker || "").toUpperCase().includes(query.toUpperCase());
                return (
                  <tr key={`${signal.ticker}-${signal.mode}`} className={cn("cursor-pointer border-b border-slate-800/60", activeQuery ? "bg-cyan-400/5" : "")} onClick={() => onSelectTicker(signal.ticker)}>
                    <td className="px-5 py-4 align-top"><span className="rounded-full border border-slate-700/70 bg-slate-900/80 px-3 py-1 font-mono text-xs text-slate-100">{signal.ticker}</span></td>
                    <td className="px-5 py-4 align-top text-slate-300">{modeLabel(signal.mode)}</td>
                    <td className="px-5 py-4 align-top"><span className="rounded-full border border-emerald-400/20 bg-emerald-500/10 px-3 py-1 font-mono text-xs text-emerald-200">{fmtNumber(signal.score, 2)}</span></td>
                    <td className="px-5 py-4 align-top"><span className={cn("font-mono text-xs", signal.shadow_p_win > 0.65 ? "neon-text-green font-bold" : "text-slate-300")}>{fmtPct(safeNumber(signal.shadow_p_win, 0) * 100, 1)}</span></td>
                    <td className="px-5 py-4 align-top font-mono text-slate-200">{fmtNumber(signal.entry, 2)}</td>
                    <td className="px-5 py-4 align-top font-mono text-slate-200">{fmtNumber(signal.stop, 2)}</td>
                    <td className="px-5 py-4 align-top font-mono text-slate-200">{fmtNumber(signal.tp1, 2)}</td>
                    <td className="px-5 py-4 align-top"><span className="rounded-full border border-sky-400/20 bg-sky-500/10 px-3 py-1 font-mono text-xs text-sky-200">{fmtNumber(signal.dyn_lots || signal.size, 0)}</span></td>
                    <td className="px-5 py-4 align-top font-mono text-rose-200">{fmtCompact(signal.dyn_risk_idr || 0, 1)}</td>
                    <td className="px-5 py-4 align-top text-slate-400"><p className="line-clamp-2">{signal.reason || "-"}</p></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      <div className="grid gap-3 xl:hidden">
        {items.map((signal) => (
          <button key={`${signal.ticker}-${signal.mode}`} type="button" onClick={() => onSelectTicker(signal.ticker)} className="glass-panel-soft rounded-3xl p-4 text-left transition hover:border-slate-600/80">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="flex items-center gap-3">
                  <span className="rounded-full border border-slate-700/70 bg-slate-900/80 px-3 py-1 font-mono text-xs text-slate-100">{signal.ticker}</span>
                  <StatusPill label={modeLabel(signal.mode)} tone="accent" className="px-2 py-1 text-[10px]" />
                </div>
                <p className="mt-3 line-clamp-2 text-sm leading-6 text-slate-400">{signal.reason || "No reason available."}</p>
              </div>
              <div className="text-right">
                <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Score</p>
                <strong className="font-display text-2xl text-white">{fmtNumber(signal.score, 2)}</strong>
              </div>
            </div>
            <div className="mt-4 grid grid-cols-2 gap-3 text-sm text-slate-300 sm:grid-cols-4">
              {[ ["Entry", signal.entry], ["Stop", signal.stop], ["Prob", safeNumber(signal.shadow_p_win, 0)*100], ["Lots", signal.dyn_lots || signal.size] ].map(([label, value]) => (
                <div key={label}>
                  <p className="text-xs uppercase tracking-[0.18em] text-slate-500">{label}</p>
                  <p className="mt-1 font-mono">{label === "Prob" ? fmtPct(value, 1) : fmtNumber(value, 2)}</p>
                </div>
              ))}
            </div>
          </button>
        ))}
      </div>
    </>
  );
}

function App() {
  const reducedMotion = useReducedMotion();
  useScrollProgress();
  useParallaxBackground(reducedMotion);

  const [dashboard, setDashboard] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filterMode, setFilterMode] = useState("all");
  const [filterQuery, setFilterQuery] = useState("");
  const [minScore, setMinScore] = useState(0);
  const [activeTab, setActiveTab] = useState("signals");
  const [selectedTicker, setSelectedTicker] = useState("");
  const [job, setJob] = useState(null);

  const refreshDashboard = async (showLoader = false) => {
    if (showLoader) setLoading(true);
    setError("");
    try {
      const payload = await api("/public_dashboard.json");
      setDashboard(payload);
    } catch (err) {
      setError(err.message || "Failed to load dashboard.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { refreshDashboard(true); }, []);

  useEffect(() => {
    const handle = window.setInterval(() => refreshDashboard(false), AUTO_REFRESH_MS);
    return () => window.clearInterval(handle);
  }, []);

  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.status)) return undefined;
    const poll = window.setInterval(async () => {
      try {
        const next = await api(`/api/jobs/${job.job_id}`);
        setJob(next);
        if (!["queued", "running"].includes(next.status)) {
          window.clearInterval(poll);
          refreshDashboard(false);
        }
      } catch {
        window.clearInterval(poll);
      }
    }, 1800);
    return () => window.clearInterval(poll);
  }, [job]);

  useEffect(() => {
    if (loading || reducedMotion || !window.gsap) return undefined;
    if (window.ScrollTrigger) window.gsap.registerPlugin(window.ScrollTrigger);

    // Hero intro timeline: reveal the headline, metrics, and CTAs on first paint with a short stagger.
    const ctx = window.gsap.context(() => {
      window.gsap.from("[data-hero-reveal]", { autoAlpha: 0, y: 18, duration: 0.68, ease: "power3.out", stagger: 0.07 });
      // Scroll reveal: each major section animates in once as it enters the viewport for a premium but restrained feel.
      document.querySelectorAll("[data-reveal]").forEach((section) => {
        window.gsap.fromTo(section, { autoAlpha: 0, y: 30 }, {
          autoAlpha: 1,
          y: 0,
          duration: 0.76,
          ease: "power3.out",
          scrollTrigger: { trigger: section, start: "top 82%", once: true },
        });
      });
    });

    return () => ctx.revert();
  }, [dashboard, loading, reducedMotion]);

  const signals = dashboard?.signals?.items || [];
  const runs = dashboard?.runs || [];
  const alerts = dashboard?.operator_alerts || [];
  const eventRiskItems = dashboard?.event_risk?.active_items || [];
  const paperFills = dashboard?.paper_fills || {};
  const swingAudit = dashboard?.swing_audit || {};
  const decision = dashboard?.decision || {};
  const backtest = dashboard?.backtest || {};
  const topPicks = dashboard?.top_picks || {};
  const executionPlan = dashboard?.execution_plan || {};
  const summary = dashboard?.summary || {};
  const funnel = dashboard?.funnel || {};
  const regime = backtest?.regime || {};
  const killSwitch = backtest?.kill_switch || {};
  const gateComponents = backtest?.gate_components || {};
  const modelPromotion = backtest?.model_v2_promotion || {};
  const modeActivation = backtest?.mode_activation || {};
  const quality = dashboard?.quality || {};
  const riskBudget = dashboard?.risk_budget || {};
  const closedLoop = dashboard?.closed_loop_retrain || {};
  const paperLiveMode = dashboard?.paper_live_mode || {};
  const signalByMode = dashboard?.signals?.by_mode || {};
  const intraday = dashboard?.intraday || {};

  const filteredSignals = useMemo(() => {
    const query = filterQuery.trim().toUpperCase();
    return signals.filter((signal) => {
      const mode = String(signal.mode || "").toLowerCase();
      const score = safeNumber(signal.score, 0);
      const ticker = String(signal.ticker || "").toUpperCase();
      if (filterMode !== "all" && mode !== filterMode) return false;
      if (score < minScore) return false;
      if (query && !ticker.includes(query)) return false;
      return true;
    });
  }, [filterMode, filterQuery, minScore, signals]);

  const heroSparkValues = useMemo(() => {
    const source = filteredSignals.length ? filteredSignals : signals;
    return source.slice(0, 12).map((signal) => safeNumber(signal.score, 0));
  }, [filteredSignals, signals]);

  const recentRunChart = useMemo(() => runs.slice(0, 6).reverse().map((run) => ({ label: run.run_id?.slice(-4) || "run", value: safeNumber(run.events, 0), display: fmtNumber(run.events, 0) })), [runs]);
  const volatilityChart = useMemo(() => {
    const items = Array.isArray(swingAudit.by_volatility) ? swingAudit.by_volatility : [];
    return items.slice(0, 4).map((item) => ({ label: item.bucket || item.label || "bucket", value: safeNumber(item.expectancy_r, 0) + 1, display: fmtR(item.expectancy_r, 2) }));
  }, [swingAudit]);
  const topSwingItems = Array.isArray(topPicks.swing_items) ? topPicks.swing_items.slice(0, 5) : [];
  const executionPreview = Array.isArray(executionPlan.items) ? executionPlan.items.slice(0, 6) : [];
  const activeModes = Array.isArray(modeActivation.active_modes) ? modeActivation.active_modes : [];
  const inactiveModes = Array.isArray(modeActivation.inactive_modes) ? modeActivation.inactive_modes : [];
  const latestRun = runs[0] || {};
  const scoreFunnelModes = funnel?.modes || {};
  const funnelSummary = [
    {
      label: "Swing kept",
      value: safeNumber(scoreFunnelModes?.swing?.kept_final, 0),
      display: fmtNumber(scoreFunnelModes?.swing?.kept_final, 0),
    },
    {
      label: "Score dropped",
      value: safeNumber(scoreFunnelModes?.swing?.dropped_by_score, 0),
      display: fmtNumber(scoreFunnelModes?.swing?.dropped_by_score, 0),
    },
    {
      label: "Event dropped",
      value: safeNumber(scoreFunnelModes?.swing?.dropped_by_event_risk, 0),
      display: fmtNumber(scoreFunnelModes?.swing?.dropped_by_event_risk, 0),
    },
    {
      label: "Size dropped",
      value: safeNumber(funnel?.combined?.dropped_by_size_filter, 0),
      display: fmtNumber(funnel?.combined?.dropped_by_size_filter, 0),
    },
  ];
  const commandMatrix = [
    {
      label: "Data max date",
      value: summary.data_max_date || decision.data_max_date || "-",
      help: "Latest daily close successfully carried into the current snapshot.",
    },
    {
      label: "Data age",
      value: summary.data_age_days != null ? `${fmtNumber(summary.data_age_days, 0)} days` : "-",
      help: "Freshness check to detect stale inputs before they affect decision quality.",
    },
    {
      label: "Active modes",
      value: activeModes.length ? activeModes.map(modeLabel).join(", ") : "None",
      help: "Modes still enabled after runtime policy and strategy freeze rules.",
    },
    {
      label: "Allowed post-gate modes",
      value: Array.isArray(decision.allowed_modes) && decision.allowed_modes.length ? decision.allowed_modes.map(modeLabel).join(", ") : "None",
      help: "Modes that remain executable after the full live gate and risk-protection stack.",
    },
    {
      label: "Paper / live",
      value: paperLiveMode.mode || "unknown",
      help: "Operational rollout posture that controls whether signals are purely paper or live-eligible.",
    },
    {
      label: "Post-gate signals",
      value: fmtNumber(funnel?.post_gate?.signal_count, 0),
      help: "Final executable signal count after all gates, sizing rules, and decision constraints.",
    },
    {
      label: "Research candidates",
      value: fmtNumber(topSwingItems.length, 0),
      help: "Ranked swing ideas kept for research review even when no trade is currently allowed.",
    },
  ];
  const swingGate = gateComponents?.swing || {};
  const promotionSwing = modelPromotion?.modes?.swing || {};
  const promotionSummary = promotionSwing?.summary || {};
  const promotionReasons = Array.isArray(promotionSwing?.reasons) ? promotionSwing.reasons : [];
  const gateMatrix = [
    {
      label: "Model gate",
      ok: Boolean(swingGate.model_gate_ok),
      help: "Checks whether the active model layer and promotion rules allow swing to proceed.",
    },
    {
      label: "Regime gate",
      ok: Boolean(swingGate.regime_ok),
      help: "Market breadth and return regime filter that blocks trading when market posture is weak.",
    },
    {
      label: "Kill switch",
      ok: Boolean(swingGate.kill_switch_ok),
      help: "Rolling performance guardrail designed to stop degraded modes before losses snowball.",
    },
    {
      label: "Quality gate",
      ok: Boolean(swingGate.quality_ok),
      help: "Freshness and data-quality validation to keep stale or corrupted inputs out of the pipeline.",
    },
  ];
  const funnelStats = funnel?.score_funnel || funnel || {};
  const preGate = funnel?.pre_gate || {};
  const postGate = funnel?.post_gate || {};
  const regimeInsights = Array.isArray(swingAudit.by_regime) ? swingAudit.by_regime : [];
  const groupInsights = Array.isArray(swingAudit.by_group) ? swingAudit.by_group : [];
  const volatilityInsights = Array.isArray(swingAudit.by_volatility) ? swingAudit.by_volatility : [];

  const triggerRunDaily = async () => {
    try {
      const payload = await api("/api/run-daily", { method: "POST", body: JSON.stringify({ skip_telegram: true }) });
      setJob(payload.job);
    } catch (err) {
      setError(err.message || "Failed to submit run-daily.");
    }
  };

  const tabContent = useMemo(() => {
    if (!dashboard) return null;
    if (activeTab === "signals") {
      return (
        <div className="grid gap-5 xl:grid-cols-[1.2fr,0.8fr]">
          <div className="glass-panel-soft rounded-3xl p-5">
            <div className="mb-5 flex items-center justify-between gap-4">
              <div>
                <p className="text-xs uppercase tracking-[0.22em] text-slate-500">Signal flow</p>
                <h3 className="mt-2 font-display text-xl font-semibold text-white">Quality-weighted signal distribution</h3>
              </div>
              <StatusPill label={`${filteredSignals.length} visible`} tone="success" />
            </div>
            <Sparkline values={heroSparkValues} />
            <div className="mt-4 grid gap-3 sm:grid-cols-3">
              {Object.entries(signalByMode || {}).map(([mode, count]) => (
                <div key={mode} className="rounded-2xl border border-slate-800/80 bg-slate-950/70 p-4">
                  <p className="text-xs uppercase tracking-[0.18em] text-slate-500">{modeLabel(mode)}</p>
                  <strong className="mt-2 block text-2xl text-white">{fmtNumber(count, 0)}</strong>
                </div>
              ))}
            </div>
          </div>
          <div className="glass-panel-soft rounded-3xl p-5">
            <p className="text-xs uppercase tracking-[0.22em] text-slate-500">Decision posture</p>
            <h3 className="mt-2 font-display text-xl font-semibold text-white">Trading stance for the current snapshot</h3>
            <div className="mt-5 grid gap-3">
              {[ ["Decision status", decision.status || "-"], ["Action", decision.action || "-"], ["Trade ready", decision.trade_ready ? "Yes" : "No"], ["Allowed modes", (decision.allowed_modes || []).map(modeLabel).join(", ") || "None"] ].map(([label, value]) => (
                <div key={label} className="rounded-2xl border border-slate-800/80 bg-slate-950/70 px-4 py-3">
                  <p className="text-xs uppercase tracking-[0.18em] text-slate-500">{label}</p>
                  <p className="mt-2 text-sm leading-6 text-slate-200">{value}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      );
    }

    if (activeTab === "risk") {
      return <MetricList items={[
        { label: "Market regime", value: String(regime.status || "-"), help: regime.reason || "Primary market guardrail status from breadth, returns, and ATR context.", tone: statusTone(regime.status), toneLabel: String(regime.status || "unknown") },
        { label: "Kill switch", value: String(killSwitch.status || "-"), help: "Rolling performance protection to stop degraded modes before they snowball.", tone: statusTone(killSwitch.status), toneLabel: String(killSwitch.status || "unknown") },
        { label: "Quality check", value: String(quality.status || "-"), help: quality.message || "Freshness, duplicates, missing rows, and outlier monitoring.", tone: statusTone(quality.status), toneLabel: String(quality.status || "unknown") },
        { label: "Risk budget", value: `${fmtPct(riskBudget.risk_budget_pct, 2)} active`, help: `Effective risk/trade ${fmtPct(riskBudget.effective_risk_per_trade_pct, 2)} · Daily stop ${fmtR(riskBudget.hard_daily_stop_r, 1)}`, tone: statusTone(riskBudget.status), toneLabel: String(riskBudget.status || "unknown") },
      ]} />;
    }

    return (
      <div className="grid gap-5 xl:grid-cols-[0.9fr,1.1fr]">
        <div className="glass-panel-soft rounded-3xl p-5">
          <p className="text-xs uppercase tracking-[0.22em] text-slate-500">Deployment posture</p>
          <h3 className="mt-2 font-display text-xl font-semibold text-white">Rollout and operating mode</h3>
          <div className="mt-5 space-y-3">
            {[ ["Paper / live mode", paperLiveMode.mode || "-"], ["Rollout phase", paperLiveMode.rollout_phase || "-"], ["Closed-loop retrain", closedLoop.status || "-"], ["Train status", closedLoop.train_status || "-"] ].map(([label, value]) => (
              <div key={label} className="rounded-2xl border border-slate-800/80 bg-slate-950/70 px-4 py-3">
                <p className="text-xs uppercase tracking-[0.18em] text-slate-500">{label}</p>
                <p className="mt-2 text-sm leading-6 text-slate-200">{value}</p>
              </div>
            ))}
          </div>
        </div>
        <div className="glass-panel-soft rounded-3xl p-5">
          <p className="text-xs uppercase tracking-[0.22em] text-slate-500">Execution readiness</p>
          <h3 className="mt-2 font-display text-xl font-semibold text-white">Plan rows, active event risk, and paper fills</h3>
          <div className="mt-5 grid gap-3 sm:grid-cols-3">
            {[ ["Execution rows", fmtNumber(dashboard.execution_plan?.total, 0)], ["Event-risk active", fmtNumber(dashboard.event_risk?.active_total, 0)], ["Paper trades", fmtNumber(paperFills.trade_count_total, 0)] ].map(([label, value]) => (
              <div key={label} className="rounded-2xl border border-slate-800/80 bg-slate-950/70 p-4">
                <p className="text-xs uppercase tracking-[0.18em] text-slate-500">{label}</p>
                <strong className="mt-2 block text-2xl text-white">{value}</strong>
              </div>
            ))}
          </div>
          <div className="mt-5"><SimpleBarChart items={recentRunChart.length ? recentRunChart : [{ label: "No runs", value: 1, display: "0" }]} color="bg-sky-400" /></div>
        </div>
      </div>
    );
  }, [activeTab, dashboard, filteredSignals.length, heroSparkValues, signalByMode, decision, regime, killSwitch, quality, riskBudget, paperLiveMode, closedLoop, paperFills.trade_count_total, recentRunChart]);

  const activeFilters = [filterMode !== "all", minScore > 0, filterQuery.trim() !== ""].filter(Boolean).length;

  return (
    <div className="relative">
      <header className="sticky top-0 z-50 border-b border-slate-800/70 bg-finance-950/80 backdrop-blur-xl">
        <div className="premium-shell flex w-full items-center justify-between gap-4 py-4">
          <div className="flex min-w-0 items-center gap-4">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-emerald-400/20 bg-emerald-400/10 font-display text-lg font-semibold text-emerald-200">ID</div>
            <div className="min-w-0">
              <p className="font-mono text-[11px] uppercase tracking-[0.34em] text-slate-500">Premium decision-support</p>
              <h1 className="truncate font-display text-lg font-semibold text-white sm:text-xl">IDX Trading Lab</h1>
            </div>
          </div>
          <nav className="hidden items-center gap-2 xl:flex">
            {[ ["Overview", "#overview"], ["Control", "#control"], ["Execution", "#execution"], ["Signals", "#signals"], ["Risk", "#risk"], ["Research", "#research"], ["Runs", "#runs"] ].map(([label, href]) => (
              <a key={label} href={href} className="rounded-full border border-transparent px-3 py-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-400 transition hover:border-slate-700/70 hover:bg-slate-900/70 hover:text-slate-100">{label}</a>
            ))}
          </nav>
          <div className="flex items-center gap-2">
            <button type="button" onClick={() => refreshDashboard(false)} className="rounded-full border border-slate-700/70 bg-slate-900/70 px-4 py-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-200 transition hover:border-slate-500/80">Refresh</button>
          </div>
        </div>
      </header>

      <main className="premium-shell premium-main">
        <section id="overview" className="premium-hero-panel relative overflow-hidden rounded-[32px] border border-slate-800/70 bg-hero-grid bg-[size:42px_42px] p-6 shadow-glow sm:p-8 lg:p-10" data-reveal>
          <div className="absolute inset-0 bg-gradient-to-br from-emerald-400/10 via-transparent to-sky-400/10" />
          <div className="premium-hero-layout premium-grid-balanced relative grid xl:grid-cols-[1.04fr,0.96fr]">
            <div className="flex h-full flex-col justify-between gap-8">
              <StatusPill label={`Auto refresh ${AUTO_REFRESH_MS / 1000}s`} tone="accent" className="w-fit" />
              <div className="space-y-3">
                <p data-hero-reveal className="font-mono text-[11px] uppercase tracking-[0.36em] text-slate-400">Institutional-grade trading research interface</p>
                <div className="hero-title space-y-2">
                  <span data-hero-reveal><strong className="font-display text-4xl font-semibold leading-tight text-white sm:text-5xl xl:text-6xl">Premium intelligence for</strong></span>
                  <span data-hero-reveal><strong className="font-display text-4xl font-semibold leading-tight text-transparent sm:text-5xl xl:text-6xl bg-gradient-to-r from-emerald-200 via-cyan-200 to-sky-300 bg-clip-text">signal selection and risk posture</strong></span>
                </div>
                <p data-hero-reveal className="max-w-2xl text-base leading-8 text-slate-300 sm:text-lg">A responsive dark financial workspace for scoring, monitoring, and auditing the entire daily trading research pipeline without sacrificing readability.</p>
              </div>
              <div data-hero-reveal className="flex flex-wrap gap-3">
                <StatusPill label={`Decision ${decision.status || "-"}`} tone={statusTone(decision.status)} />
                <StatusPill label={`Regime ${regime.status || "-"}`} tone={statusTone(regime.status)} />
                <StatusPill label={`Kill ${killSwitch.status || "-"}`} tone={statusTone(killSwitch.status)} />
                <StatusPill label={`Quality ${quality.status || "-"}`} tone={statusTone(quality.status)} />
              </div>
              <div data-hero-reveal className="flex flex-wrap gap-3">
                <a href="#signals" className="rounded-full border border-slate-700/70 bg-slate-900/70 px-5 py-3 text-xs font-semibold uppercase tracking-[0.2em] text-slate-100 transition hover:border-slate-500/80">Jump to signals</a>
                <a href="#runs" className="rounded-full border border-emerald-400/20 bg-emerald-400/10 px-5 py-3 text-xs font-semibold uppercase tracking-[0.2em] text-emerald-100 transition hover:border-emerald-300/40 hover:bg-emerald-400/16">Review recent runs</a>
              </div>
            </div>
            <div data-hero-reveal className="glass-panel premium-overview-card premium-panel-tight rounded-[28px]">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <p className="text-xs uppercase tracking-[0.22em] text-slate-500">Live overview</p>
                  <h2 className="mt-2 font-display text-2xl font-semibold text-white">Current operating snapshot</h2>
                </div>
                <StatusPill label={decision.trade_ready ? "Trade ready" : "No trade"} tone={decision.trade_ready ? "success" : "warning"} />
              </div>
              <div className="mt-6 grid gap-4 sm:grid-cols-2">
                <div className="rounded-3xl border border-slate-800/70 bg-slate-950/70 p-4">
                  <p className="text-xs uppercase tracking-[0.18em] text-slate-500">As of</p>
                  <p className="mt-2 text-sm leading-6 text-slate-200">{fmtDateTime(dashboard?.signals?.generated_at || dashboard?.generated_at)}</p>
                </div>
                <div className="rounded-3xl border border-slate-800/70 bg-slate-950/70 p-4">
                  <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Action reason</p>
                  <p className="mt-2 text-sm leading-6 text-slate-200">{decision.action_reason || "No reason available."}</p>
                </div>
              </div>
              <div className="mt-5 rounded-[28px] border border-slate-800/70 bg-slate-950/70 p-4">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Signal momentum</p>
                  <span className="font-mono text-xs text-slate-500">{filteredSignals.length} filtered rows</span>
                </div>
                <Sparkline values={heroSparkValues.length ? heroSparkValues : [0, 0, 0]} />
              </div>
            </div>
          </div>
        </section>

        <section className="mt-8" data-reveal>
          {loading ? <LoadingKpiGrid /> : (
            <div className="premium-grid-balanced grid md:grid-cols-2 xl:grid-cols-4">
              <KpiCard label="Executable Signals" value={filteredSignals.length} subtext="Post-gate signals that remain available for operator review and possible execution." reducedMotion={reducedMotion} />
              <KpiCard label="Average Executable Score" value={dashboard?.signals?.avg_score || 0} digits={2} tone="accent" subtext="Mean score across signals that survived the final live decision pipeline." reducedMotion={reducedMotion} />
              <KpiCard label="Execution Rows" value={dashboard?.execution_plan?.total || 0} tone="warning" subtext="Rows prepared for execution review and position-sizing confirmation." reducedMotion={reducedMotion} />
              <KpiCard label="Event-Risk Active" value={dashboard?.event_risk?.active_total || 0} tone="danger" subtext="Tickers flagged for suspend, UMA, material events, or similar operational caution." reducedMotion={reducedMotion} />
            </div>
          )}
        </section>

        <section id="control" className="mt-12" data-reveal>
          <SectionHeading eyebrow="Operational matrix" title="Control-room content with clear research vs execution meaning" description="This block separates executable posture from research posture, so a ranked swing idea is not mistaken for an active tradable signal." />
          <div className="premium-grid-balanced grid xl:grid-cols-[0.98fr,1.02fr]">
            <div className="glass-panel rounded-3xl p-5">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-xs uppercase tracking-[0.22em] text-slate-500">Command matrix</p>
                  <h3 className="mt-2 font-display text-xl font-semibold text-white">Core operating facts before any trade decision</h3>
                </div>
                <StatusPill label={decision.trade_ready ? "Decision live" : "Decision held"} tone={decision.trade_ready ? "success" : "warning"} />
              </div>
              <div className="mt-5 grid gap-3 md:grid-cols-2">
                {commandMatrix.map((item) => (
                  <article key={item.label} className="rounded-3xl border border-slate-800/80 bg-slate-950/70 p-4">
                    <p className="text-xs uppercase tracking-[0.18em] text-slate-500">{item.label}</p>
                    <strong className="mt-3 block font-display text-2xl leading-tight text-white">{item.value}</strong>
                    <p className="mt-3 text-sm leading-7 text-slate-400">{item.help}</p>
                  </article>
                ))}
              </div>

              <div className="mt-8">
                <div className="mb-4 flex items-center justify-between">
                  <p className="text-xs uppercase tracking-[0.22em] text-slate-500">V2 Intelligence Modules</p>
                </div>
                <div className="grid gap-3 md:grid-cols-3">
                  <article className="glass-panel-heavy rounded-3xl p-4">
                    <div className="flex justify-between items-center mb-3">
                      <p className="text-xs uppercase tracking-[0.18em] text-slate-400">Regime Threshold</p>
                      <StatusPill label={regime.status || "Unknown"} tone={regime.status === "risk_on" ? "success" : "danger"} />
                    </div>
                    <strong className={cn("block font-display text-xl leading-tight", regime.status === "risk_on" ? "neon-text-green" : "neon-text-red")}>
                      {regime.status === "risk_on" ? "Bull Market (Aggressive)" : "Bear Market (Strict)"}
                    </strong>
                    <p className="mt-2 text-sm text-slate-400 line-clamp-2">{regime.reason || "Determines entry threshold logic."}</p>
                  </article>

                  <article className="glass-panel-heavy rounded-3xl p-4">
                    <div className="flex justify-between items-center mb-3">
                      <p className="text-xs uppercase tracking-[0.18em] text-slate-400">Sector Limits</p>
                      <StatusPill label={`${fmtNumber(dashboard?.risk_budget?.sector_exposure_cap_pct || 35)}% Cap`} tone="accent" />
                    </div>
                    <strong className="block font-display text-xl leading-tight text-white">Active Diversification</strong>
                    <p className="mt-2 text-sm text-slate-400">Prevents portfolio concentration in single industry sectors.</p>
                  </article>

                  <article className="glass-panel-heavy rounded-3xl p-4">
                    <div className="flex justify-between items-center mb-3">
                      <p className="text-xs uppercase tracking-[0.18em] text-slate-400">Closed-Loop Feedback</p>
                      <StatusPill label={closedLoop.status === "not_run" ? "Pending Fills" : closedLoop.status} tone={closedLoop.status === "triggered" ? "success" : "warning"} />
                    </div>
                    <div className="mt-1 flex gap-4">
                      <div>
                        <p className="text-[10px] uppercase text-slate-500">Actual Win Rate</p>
                        <strong className="block font-mono text-lg text-emerald-200">{fmtPct(closedLoop.live_profit_factor_r * 100, 1) || "0.0%"}</strong>
                      </div>
                      <div>
                        <p className="text-[10px] uppercase text-slate-500">Expectancy</p>
                        <strong className="block font-mono text-lg text-sky-200">{fmtR(closedLoop.live_expectancy_r, 2) || "0.00R"}</strong>
                      </div>
                    </div>
                  </article>
                </div>
              </div>
            </div>
            <div className="premium-grid-balanced grid 2xl:grid-cols-[1.05fr,0.95fr]">
              <div className="glass-panel rounded-3xl p-5">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-xs uppercase tracking-[0.22em] text-slate-500">Swing research watchlist</p>
                    <h3 className="mt-2 font-display text-xl font-semibold text-white">Pre-gate swing candidates from the latest ranking snapshot</h3>
                  </div>
                  <StatusPill label={postGate.signal_count > 0 ? `${topSwingItems.length} ranked` : "research only"} tone={postGate.signal_count > 0 ? "accent" : "protective"} />
                </div>
                <p className="mt-3 text-sm leading-7 text-slate-400">
                  {postGate.signal_count > 0
                    ? "These names passed the ranking stage. Use the executable plan below to see which ones actually survived the final gate."
                    : "These names passed ranking, but the live gate still blocked execution. Read them as research candidates, not active trade signals."}
                </p>
                <div className="mt-5 space-y-3">
                  {topSwingItems.length ? topSwingItems.map((item) => (
                    <button
                      key={`${item.ticker}-${item.rank || item.score}`}
                      type="button"
                      onClick={() => setSelectedTicker(item.ticker)}
                      className="group w-full rounded-3xl border border-slate-800/80 bg-slate-950/70 p-4 text-left transition hover:border-cyan-400/30 hover:bg-slate-900/80"
                    >
                      <div className="flex flex-wrap items-start justify-between gap-4">
                        <div>
                          <div className="flex flex-wrap items-center gap-3">
                            <span className="rounded-full border border-slate-700/70 bg-slate-900/80 px-3 py-1 font-mono text-xs text-slate-100">{item.ticker || "-"}</span>
                            <StatusPill label={`Rank ${fmtNumber(item.rank, 0)}`} tone="accent" className="px-2 py-1 text-[10px]" />
                          </div>
                          <p className="mt-3 line-clamp-2 text-sm leading-7 text-slate-300">{item.reason || "No scoring rationale was provided for this candidate."}</p>
                        </div>
                        <div className="text-right">
                          <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Score</p>
                          <strong className="font-display text-3xl text-white transition group-hover:text-cyan-200">{fmtNumber(item.score, 2)}</strong>
                        </div>
                      </div>
                      <div className="mt-4 grid gap-3 sm:grid-cols-3">
                        {[["Entry", fmtNumber(item.entry, 2)], ["Stop", fmtNumber(item.stop, 2)], ["TP1", fmtNumber(item.tp1, 2)]].map(([label, value]) => (
                          <div key={label} className="rounded-2xl border border-slate-800/70 bg-slate-900/70 px-3 py-2">
                            <p className="text-[11px] uppercase tracking-[0.18em] text-slate-500">{label}</p>
                            <p className="mt-2 font-mono text-sm text-slate-200">{value}</p>
                          </div>
                        ))}
                      </div>
                    </button>
                  )) : <EmptyState title="No ranked swing candidates" message="Once the latest scoring snapshot produces ranked swing rows, the premium board will surface them here." />}
                </div>
              </div>
              <div className="glass-panel rounded-3xl p-5">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-xs uppercase tracking-[0.22em] text-slate-500">Mode policy</p>
                    <h3 className="mt-2 font-display text-xl font-semibold text-white">Active and frozen operating modes</h3>
                  </div>
                  <StatusPill label={modeActivation.swing_only ? "Swing only" : "Mixed"} tone={modeActivation.swing_only ? "protective" : "accent"} />
                </div>
                <div className="mt-5 space-y-4">
                  <div className="rounded-3xl border border-slate-800/80 bg-slate-950/70 p-4">
                    <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Active modes</p>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {activeModes.length ? activeModes.map((mode) => <StatusPill key={mode} label={modeLabel(mode)} tone="success" className="px-2 py-1 text-[10px]" />) : <span className="text-sm text-slate-400">No active mode.</span>}
                    </div>
                  </div>
                  <div className="rounded-3xl border border-slate-800/80 bg-slate-950/70 p-4">
                    <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Inactive modes</p>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {inactiveModes.length ? inactiveModes.map((mode) => <StatusPill key={mode} label={modeLabel(mode)} tone="warning" className="px-2 py-1 text-[10px]" />) : <span className="text-sm text-slate-400">No frozen modes.</span>}
                    </div>
                  </div>
                  <div className="rounded-3xl border border-slate-800/80 bg-slate-950/70 p-4">
                    <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Run note</p>
                    <p className="mt-3 text-sm leading-7 text-slate-300">{latestRun.status_note || decision.action_reason || "No recent run note is available."}</p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section id="execution" className="mt-12" data-reveal>
          <SectionHeading eyebrow="Execution intelligence" title="Executable plan, signal funnel, and model readiness" description="This section shows what is actually executable after gating, while still explaining where research candidates were dropped before becoming tradable." />
          <div className="premium-grid-balanced grid xl:grid-cols-[1.02fr,0.98fr]">
            <div className="space-y-5">
              <div className="glass-panel rounded-3xl p-5">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-xs uppercase tracking-[0.22em] text-slate-500">Executable plan</p>
                    <h3 className="mt-2 font-display text-xl font-semibold text-white">Rows that survived the final gate and remain action-ready</h3>
                  </div>
                  <StatusPill label={`${executionPreview.length} rows`} tone={executionPreview.length ? "accent" : "warning"} />
                </div>
                <div className="mt-5 grid gap-3">
                  {executionPreview.length ? executionPreview.map((item) => (
                    <div key={`${item.ticker}-${item.mode}-${item.entry}`} className="rounded-3xl border border-slate-800/80 bg-slate-950/70 p-4">
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div className="flex items-center gap-3">
                          <span className="rounded-full border border-slate-700/70 bg-slate-900/80 px-3 py-1 font-mono text-xs text-slate-100">{item.ticker || "-"}</span>
                          <StatusPill label={modeLabel(item.mode)} tone="accent" className="px-2 py-1 text-[10px]" />
                        </div>
                        <strong className="font-mono text-sm text-emerald-200">{fmtNumber(item.score, 2)}</strong>
                      </div>
                      <div className="mt-4 grid gap-3 sm:grid-cols-4">
                        {[["Entry", item.entry], ["Stop", item.stop], ["TP1", item.tp1], ["Size", item.size]].map(([label, value]) => (
                          <div key={label} className="rounded-2xl border border-slate-800/70 bg-slate-900/70 px-3 py-2">
                            <p className="text-[11px] uppercase tracking-[0.18em] text-slate-500">{label}</p>
                            <p className="mt-2 font-mono text-sm text-slate-200">{fmtNumber(value, 2)}</p>
                          </div>
                        ))}
                      </div>
                      <p className="mt-4 line-clamp-2 text-sm leading-7 text-slate-400">{item.reason || "No execution note available."}</p>
                    </div>
                  )) : <EmptyState title="No executable rows prepared" message="The scoring pipeline may still have research candidates, but nothing survived the latest post-gate snapshot." />}
                </div>
              </div>
              <div className="glass-panel rounded-3xl p-5">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-xs uppercase tracking-[0.22em] text-slate-500">Signal funnel</p>
                    <h3 className="mt-2 font-display text-xl font-semibold text-white">Where swing candidates are getting filtered out</h3>
                  </div>
                  <StatusPill label={`${fmtNumber(preGate.signal_count, 0)} pre-gate / ${fmtNumber(postGate.signal_count, 0)} post-gate`} tone="protective" />
                </div>
                <div className="premium-grid-balanced mt-5 grid lg:grid-cols-[0.92fr,1.08fr]">
                  <div className="rounded-3xl border border-slate-800/80 bg-slate-950/70 p-4">
                    <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Funnel summary</p>
                    <div className="mt-4">
                      <SimpleBarChart items={funnelSummary} color="bg-cyan-400" />
                    </div>
                  </div>
                  <div className="space-y-3">
                    {[["Pre-gate signals", preGate.signal_count], ["Post-gate signals", postGate.signal_count], ["Pre-gate execution rows", preGate.execution_plan_count], ["Post-gate execution rows", postGate.execution_plan_count], ["Combined after size filter", funnelStats?.combined?.after_size_filter], ["Combined after top-N", funnelStats?.combined?.after_top_n_combined]].map(([label, value]) => (
                      <div key={label} className="rounded-2xl border border-slate-800/80 bg-slate-950/70 px-4 py-3">
                        <p className="text-xs uppercase tracking-[0.18em] text-slate-500">{label}</p>
                        <strong className="mt-2 block text-2xl text-white">{fmtNumber(value, 0)}</strong>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
            <div className="space-y-5">
              <div className="glass-panel rounded-3xl p-5">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-xs uppercase tracking-[0.22em] text-slate-500">Gate diagnostics</p>
                    <h3 className="mt-2 font-display text-xl font-semibold text-white">Why swing is allowed or blocked</h3>
                  </div>
                  <StatusPill label={decision.trade_ready ? "Gate open" : "Gate constrained"} tone={decision.trade_ready ? "success" : "warning"} />
                </div>
                <div className="mt-5 space-y-3">
                  {gateMatrix.map((item) => (
                    <article key={item.label} className="rounded-3xl border border-slate-800/80 bg-slate-950/70 p-4">
                      <div className="flex items-center justify-between gap-3">
                        <div>
                          <p className="text-xs uppercase tracking-[0.18em] text-slate-500">{item.label}</p>
                          <p className="mt-2 text-sm leading-7 text-slate-400">{item.help}</p>
                        </div>
                        <StatusPill label={item.ok ? "Pass" : "Block"} tone={item.ok ? "success" : "warning"} className="px-2 py-1 text-[10px]" />
                      </div>
                    </article>
                  ))}
                </div>
              </div>
              <div className="glass-panel rounded-3xl p-5">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-xs uppercase tracking-[0.22em] text-slate-500">Model promotion</p>
                    <h3 className="mt-2 font-display text-xl font-semibold text-white">Swing ML readiness without black-box hype</h3>
                  </div>
                  <StatusPill label={promotionSwing.passed ? "Promotion pass" : "Promotion blocked"} tone={promotionSwing.passed ? "success" : "warning"} />
                </div>
                <div className="mt-5 grid gap-3 sm:grid-cols-2">
                  {[["OOS trades", promotionSummary.total_oos_trades], ["Median PF", promotionSummary.median_profit_factor], ["Median expectancy", promotionSummary.median_expectancy], ["Profitable folds", promotionSummary.n_folds_profitable]].map(([label, value]) => (
                    <div key={label} className="rounded-2xl border border-slate-800/80 bg-slate-950/70 p-4">
                      <p className="text-xs uppercase tracking-[0.18em] text-slate-500">{label}</p>
                      <strong className="mt-2 block text-2xl text-white">{typeof value === "number" ? fmtNumber(value, label.includes("expectancy") || label.includes("PF") ? 2 : 0) : "-"}</strong>
                    </div>
                  ))}
                </div>
                <div className="mt-5 space-y-3">
                  {promotionReasons.length ? promotionReasons.slice(0, 4).map((reason, index) => (
                    <div key={`${reason}-${index}`} className="rounded-2xl border border-slate-800/80 bg-slate-950/70 px-4 py-3 text-sm leading-7 text-slate-300">{reason}</div>
                  )) : <p className="text-sm leading-7 text-slate-400">No explicit promotion blockers are present in the current payload.</p>}
                </div>
              </div>
              <div className="glass-panel rounded-3xl p-5">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-xs uppercase tracking-[0.22em] text-slate-500">Audit heatmap</p>
                    <h3 className="mt-2 font-display text-xl font-semibold text-white">Segment and volatility context at a glance</h3>
                  </div>
                  <StatusPill label={`${volatilityInsights.length + groupInsights.length + regimeInsights.length} slices`} tone="accent" />
                </div>
                <div className="mt-5 grid gap-3">
                  {[...regimeInsights.slice(0, 2).map((item) => ({ label: `Regime · ${item.regime}`, expectancy: item.expectancy_r, pf: item.profit_factor_r })), ...groupInsights.slice(0, 2).map((item) => ({ label: `Group · ${item.segment || item.group_label || "-"}`, expectancy: item.expectancy_r, pf: item.profit_factor_r })), ...volatilityInsights.slice(0, 3).map((item) => ({ label: `Vol · ${item.volatility_bucket || item.bucket || "-"}`, expectancy: item.expectancy_r, pf: item.profit_factor_r }))].map((item) => (
                    <div key={item.label} className="rounded-2xl border border-slate-800/80 bg-slate-950/70 px-4 py-3">
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <p className="text-sm text-slate-200">{item.label}</p>
                        <div className="flex items-center gap-2">
                          <StatusPill label={`PF ${fmtNumber(item.pf, 2)}`} tone={safeNumber(item.pf, 0) >= 1 ? "success" : "warning"} className="px-2 py-1 text-[10px]" />
                          <StatusPill label={fmtR(item.expectancy, 2)} tone={safeNumber(item.expectancy, 0) >= 0 ? "protective" : "danger"} className="px-2 py-1 text-[10px]" />
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </section>

        <section className="mt-12" data-reveal>
          <SectionHeading eyebrow="Control room" title="Tabbed operational overview" description="Switch between signal flow, risk posture, and deployment status. Each panel animates lightly to reinforce context changes without becoming distracting." action={<div className="flex flex-wrap gap-2">{[["signals", "Signal flow"], ["risk", "Risk pulse"], ["deployment", "Deployment"]].map(([key, label]) => <FilterChip key={key} label={label} active={activeTab === key} onClick={() => setActiveTab(key)} />)}</div>} />
          <AnimatedTabPanel activeKey={activeTab} reducedMotion={reducedMotion}>{tabContent}</AnimatedTabPanel>
        </section>

        <section id="signals" className="mt-12" data-reveal>
          <SectionHeading eyebrow="Signal monitor" title="Searchable decision table" description="Filter by mode, score, and ticker. Row hover and modal drilldown are designed to support fast scanning before manual execution." action={<div className="flex items-center gap-3 rounded-full border border-slate-800/80 bg-slate-950/80 px-4 py-2 text-xs uppercase tracking-[0.18em] text-slate-500"><span>{activeFilters} active filter{activeFilters === 1 ? "" : "s"}</span><span className="text-slate-700">•</span><span>{filteredSignals.length} visible</span></div>} />
          <div className="premium-grid-balanced mb-6 grid lg:grid-cols-[220px_240px_minmax(0,1fr)_240px]">
            <div className="glass-panel-soft rounded-3xl p-4"><p className="mb-3 text-xs uppercase tracking-[0.18em] text-slate-500">Mode</p><div className="flex flex-wrap gap-2">{[["all", "All"], ["swing", "Swing"], ["t1", "T+1"], ["intraday", "Intraday"]].map(([mode, label]) => <FilterChip key={mode} label={label} active={filterMode === mode} onClick={() => setFilterMode(mode)} />)}</div></div>
            <div className="glass-panel-soft rounded-3xl p-4">
              <label className="block">
                <span className="mb-3 block text-xs uppercase tracking-[0.18em] text-slate-500">Minimum score</span>
                <input type="range" min="0" max="120" step="1" value={minScore} onChange={(event) => setMinScore(safeNumber(event.target.value, 0))} className="w-full accent-emerald-400" />
                <div className="mt-3 flex items-center justify-between text-xs text-slate-500"><span>0</span><span className="rounded-full border border-slate-700/70 px-2 py-1 font-mono text-slate-200">{fmtNumber(minScore, 0)}</span><span>120</span></div>
              </label>
            </div>
            <div className="glass-panel-soft rounded-3xl p-4">
              <label className="block">
                <span className="mb-3 block text-xs uppercase tracking-[0.18em] text-slate-500">Ticker search</span>
                <div className="flex items-center gap-3 rounded-2xl border border-slate-800/80 bg-slate-950/80 px-4 py-3">
                  <span className="text-slate-500">?</span>
                  <input type="text" value={filterQuery} onChange={(event) => setFilterQuery(event.target.value)} placeholder="BBCA / TLKM / MEDC" className="w-full border-0 bg-transparent p-0 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none focus:ring-0" />
                  {filterQuery ? <button type="button" onClick={() => setFilterQuery("")} className="rounded-full border border-slate-700/70 px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-300 transition hover:border-slate-500/80">Clear</button> : null}
                </div>
              </label>
            </div>
            <div className="glass-panel-soft rounded-3xl p-4"><p className="text-xs uppercase tracking-[0.18em] text-slate-500">Filtered score profile</p><div className="mt-3"><Sparkline values={heroSparkValues.length ? heroSparkValues : [0, 0]} lineColor="#38bdf8" /></div></div>
          </div>
          <SignalsTable items={filteredSignals} loading={loading} onSelectTicker={setSelectedTicker} query={filterQuery} />
        </section>

        <section id="risk" className="mt-12" data-reveal>
          <SectionHeading eyebrow="Risk and research" title="Guardrails, operator alerts, and strategy weak spots" description="This section surfaces the reasons the system blocks trades, highlights operational caveats, and summarizes the latest swing audit and paper execution loop." />
          <div className="grid gap-5 xl:grid-cols-[0.95fr,1.05fr]">
            <div className="space-y-5">
              <div className="glass-panel rounded-3xl p-5">
                <div className="flex items-center justify-between gap-3"><div><p className="text-xs uppercase tracking-[0.22em] text-slate-500">Decision blockers</p><h3 className="mt-2 font-display text-xl font-semibold text-white">Why the system might hold back</h3></div><StatusPill label={decision.trade_ready ? "Clear" : "Blocked"} tone={decision.trade_ready ? "success" : "warning"} /></div>
                <div className="mt-5 space-y-3">{(decision.why_no_signal || []).length ? decision.why_no_signal.map((reason, index) => <div key={index} className="rounded-2xl border border-slate-800/80 bg-slate-950/70 px-4 py-3 text-sm leading-7 text-slate-300">{reason}</div>) : <div className="rounded-2xl border border-slate-800/80 bg-slate-950/70 px-4 py-3 text-sm leading-7 text-slate-300">{decision.action_reason || "No blocking reasons detected."}</div>}</div>
              </div>
              <div className="glass-panel rounded-3xl p-5">
                <div className="flex items-center justify-between gap-3"><div><p className="text-xs uppercase tracking-[0.22em] text-slate-500">Operator alerts</p><h3 className="mt-2 font-display text-xl font-semibold text-white">Operational caveats</h3></div><StatusPill label={`${alerts.length} alerts`} tone={alerts.length ? "warning" : "success"} /></div>
                <div className="mt-5 space-y-3">{alerts.length ? alerts.map((alert, index) => <AlertCard key={`${alert.code}-${index}`} alert={alert} />) : <EmptyState title="No active operator alerts" message="The latest run did not report any special caution messages." />}</div>
              </div>
            </div>
            <div className="space-y-5">
              <div className="glass-panel rounded-3xl p-5">
                <div className="flex items-center justify-between gap-3"><div><p className="text-xs uppercase tracking-[0.22em] text-slate-500">Swing audit</p><h3 className="mt-2 font-display text-xl font-semibold text-white">Edge diagnostics by regime and volatility</h3></div><StatusPill label={swingAudit.status || "unknown"} tone={statusTone(swingAudit.status)} /></div>
                <p className="mt-3 text-sm leading-7 text-slate-400">{swingAudit.message || "Recent strategy audit will appear here once backtest analytics have been generated."}</p>
                <div className="mt-5 grid gap-4 md:grid-cols-2">
                  <div className="rounded-3xl border border-slate-800/80 bg-slate-950/70 p-4"><p className="text-xs uppercase tracking-[0.18em] text-slate-500">Overall expectancy</p><strong className="mt-2 block text-2xl text-white">{fmtR(swingAudit.overall?.expectancy_r, 2)}</strong><p className="mt-2 text-sm text-slate-400">Derived from recent audited swing trades.</p></div>
                  <div className="rounded-3xl border border-slate-800/80 bg-slate-950/70 p-4"><p className="text-xs uppercase tracking-[0.18em] text-slate-500">Profit factor</p><strong className="mt-2 block text-2xl text-white">{fmtNumber(swingAudit.overall?.profit_factor, 2)}</strong><p className="mt-2 text-sm text-slate-400">Useful for spotting stability versus headline win rate.</p></div>
                </div>
                <div className="mt-5 rounded-3xl border border-slate-800/80 bg-slate-950/70 p-4"><p className="text-xs uppercase tracking-[0.18em] text-slate-500">Volatility buckets</p><div className="mt-4"><SimpleBarChart items={volatilityChart.length ? volatilityChart : [{ label: "No audit yet", value: 1, display: "-" }]} color="bg-emerald-400" /></div></div>
                <div className="mt-5 space-y-3">{(swingAudit.weak_spots || []).length ? swingAudit.weak_spots.slice(0, 4).map((spot, index) => <div key={index} className="rounded-2xl border border-slate-800/80 bg-slate-950/70 px-4 py-3"><div className="flex flex-wrap items-center gap-3"><StatusPill label={spot.segment || spot.label || "weak spot"} tone="warning" className="px-2 py-1 text-[10px]" /><strong className="text-sm font-semibold text-white">{spot.metric || "Watchlist segment"}</strong></div><p className="mt-3 text-sm leading-7 text-slate-300">{spot.message || `${spot.label || "Segment"} shows weak expectancy or poor profit factor and deserves extra caution.`}</p></div>) : <p className="text-sm text-slate-400">No weak-spot payload is available yet.</p>}</div>
              </div>
              <div className="glass-panel rounded-3xl p-5">
                <div className="flex items-center justify-between gap-3"><div><p className="text-xs uppercase tracking-[0.22em] text-slate-500">Paper execution loop</p><h3 className="mt-2 font-display text-xl font-semibold text-white">Paper fills and feedback readiness</h3></div><StatusPill label={paperFills.status || "unknown"} tone={statusTone(paperFills.status)} /></div>
                <div className="mt-5 grid gap-3 sm:grid-cols-3">{[["Trade count", fmtNumber(paperFills.trade_count_total, 0)], ["Win rate", fmtPct(paperFills.win_rate_pct, 1)], ["Expectancy", fmtR(paperFills.expectancy_r, 2)]].map(([label, value]) => <div key={label} className="rounded-2xl border border-slate-800/80 bg-slate-950/70 p-4"><p className="text-xs uppercase tracking-[0.18em] text-slate-500">{label}</p><strong className="mt-2 block text-2xl text-white">{value}</strong></div>)}</div>
                <p className="mt-4 text-sm leading-7 text-slate-400">{paperFills.message || "Paper execution summary is ready once the simulation loop has enough recent snapshots."}</p>
              </div>
            </div>
          </div>
        </section>

        <section className="mt-12" data-reveal>
          <SectionHeading eyebrow="Portfolio and exposure" title="Execution posture and event-risk concentration" description="The project does not manage a live broker portfolio directly, but it still exposes portfolio-style insight through execution rows, mode mix, and active event-risk concentration." />
          <div className="grid gap-5 xl:grid-cols-[0.9fr,1.1fr]">
            <div className="glass-panel rounded-3xl p-5">
              <div className="flex items-center justify-between gap-3"><div><p className="text-xs uppercase tracking-[0.22em] text-slate-500">Mode allocation</p><h3 className="mt-2 font-display text-xl font-semibold text-white">Signal concentration by strategy mode</h3></div><StatusPill label={`${Object.keys(signalByMode || {}).length} modes`} tone="accent" /></div>
              <div className="mt-5"><SimpleBarChart items={Object.entries(signalByMode || {}).map(([mode, count]) => ({ label: modeLabel(mode), value: count, display: fmtNumber(count, 0) }))} color="bg-cyan-400" /></div>
            </div>
            <div className="glass-panel rounded-3xl p-5">
              <div className="flex items-center justify-between gap-3"><div><p className="text-xs uppercase tracking-[0.22em] text-slate-500">Active event risk</p><h3 className="mt-2 font-display text-xl font-semibold text-white">Highest-priority exclusions and watchlist</h3></div><StatusPill label={`${eventRiskItems.length} rows`} tone={eventRiskItems.length ? "warning" : "success"} /></div>
              <div className="mt-5 space-y-3">{eventRiskItems.length ? eventRiskItems.slice(0, 5).map((item, index) => <div key={`${item.ticker}-${index}`} className="rounded-2xl border border-slate-800/80 bg-slate-950/70 px-4 py-3"><div className="flex flex-wrap items-center justify-between gap-3"><div className="flex items-center gap-3"><span className="rounded-full border border-slate-700/70 bg-slate-900/80 px-3 py-1 font-mono text-xs text-slate-100">{item.ticker || "-"}</span><StatusPill label={item.status || "event"} tone="warning" className="px-2 py-1 text-[10px]" /></div><span className="text-xs uppercase tracking-[0.18em] text-slate-500">{item.source || "-"}</span></div><p className="mt-3 text-sm leading-7 text-slate-300">{item.reason || "No reason provided."}</p></div>) : <p className="text-sm text-slate-400">No active event-risk rows are currently loaded.</p>}</div>
            </div>
          </div>
        </section>

        <section id="research" className="mt-12" data-reveal>
          <SectionHeading eyebrow="Research context" title="What this premium layer adds on top of the existing backend" description="This UI does not replace the underlying Python engine. It re-uses the same report snapshots, adds stronger information hierarchy, and makes operator movement more deliberate through useful motion." />
          <div className="grid gap-5 lg:grid-cols-3">{[
            { title: "Interactive hierarchy", body: "Sticky navigation, tabs, accordions, and modal drilldown reduce navigation friction so users can inspect signals, risk, and run failures from one place." },
            { title: "Readable dark finance UI", body: "Tailwind-based spacing, muted contrast control, and data-centric cards are tuned for dense information without looking flat or sterile." },
            { title: "Motion with purpose", body: "GSAP is used for scroll reveal, KPI counters, tab transitions, and modal entrance. Movement is restrained and tied to user actions like hover, click, scroll, and filter changes." },
          ].map((item) => <article key={item.title} className="glass-panel rounded-3xl p-5"><p className="font-mono text-[11px] uppercase tracking-[0.32em] text-slate-500">Design rationale</p><h3 className="mt-3 font-display text-xl font-semibold text-white">{item.title}</h3><p className="mt-4 text-sm leading-7 text-slate-300">{item.body}</p></article>)}</div>
        </section>

        <section id="runs" className="mt-12" data-reveal>
          <SectionHeading eyebrow="Run intelligence" title="Recent runs with clear severity separation" description="Runs are grouped per run_id and categorized into clean runs, protective warnings, operational warnings, and critical failures, so operators do not confuse intentional no-trade posture with system breakage." />
          {runs.length ? <div className="space-y-4">{runs.map((run) => <RunCard key={run.run_id} run={run} />)}</div> : <EmptyState title="No recent runs yet" message="Once the backend writes run logs, they will appear here with drilldown details." />}
        </section>

        <footer className="mt-16 border-t border-slate-800/70 py-8 text-sm text-slate-500">
          <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
            <p>Premium dashboard layer built for the existing Python trading decision-support backend. Research candidates and executable signals are intentionally separated to reduce operator confusion.</p>
          </div>
        </footer>
      </main>

      <TickerDetailModal ticker={selectedTicker} open={Boolean(selectedTicker)} onClose={() => setSelectedTicker("")} reducedMotion={reducedMotion} />

      {job ? <div className="premium-shadow-top fixed inset-x-4 bottom-4 z-50 mx-auto max-w-xl rounded-3xl border border-slate-700/70 bg-finance-950/92 p-4 backdrop-blur-xl"><div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between"><div><div className="flex items-center gap-3"><StatusPill label={job.status || "queued"} tone={statusTone(job.status)} /><strong className="font-display text-lg text-white">Run Daily Job</strong></div><p className="mt-2 text-sm leading-7 text-slate-400">{job.error ? job.error : job.status === "succeeded" ? "The pipeline finished successfully. Dashboard data will refresh automatically." : "The backend job is still processing. This card polls the job endpoint until completion."}</p></div><button type="button" onClick={() => setJob(null)} className="rounded-full border border-slate-700/70 bg-slate-900/70 px-4 py-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-200 transition hover:border-slate-500/80">Dismiss</button></div></div> : null}
      {error ? <div className="fixed inset-x-4 bottom-4 z-50 mx-auto max-w-xl rounded-3xl border border-rose-400/30 bg-rose-500/10 p-4 text-sm text-rose-100 backdrop-blur-xl">{error}</div> : null}
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("premiumRoot")).render(<App />);

