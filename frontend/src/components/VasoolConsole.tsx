"use client";

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleDot,
  Clock3,
  CreditCard,
  Filter,
  LifeBuoy,
  Loader2,
  Menu,
  Play,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  UserRound,
  X,
  XCircle,
  Zap,
} from "lucide-react";
import {
  analyzeCase,
  evaluatePolicy,
  executeCase,
  formatINR,
  getCase,
  getCases,
  getHealth,
  getKillSwitchStatus,
  getMetrics,
  getRecentCases,
  reviewCase,
  setKillSwitch,
  type AuditEntry,
  type CaseDetail,
  type CaseSummary,
  type HealthResponse,
  type MetricsResponse,
} from "@/lib/api";

const POLL_MS = 30_000;
const statusMeta: Record<string, { label: string; tone: "neutral" | "good" | "warn" | "danger" }> = {
  detected: { label: "Detected", tone: "neutral" },
  human_review: { label: "Human review", tone: "warn" },
  blocked: { label: "Blocked", tone: "danger" },
  pending_execution: { label: "Ready to execute", tone: "good" },
  executed: { label: "Awaiting payment", tone: "good" },
  partially_recovered: { label: "Partial recovery", tone: "warn" },
  resolved: { label: "Recovered", tone: "good" },
  rejected: { label: "Rejected", tone: "danger" },
  recovery_cancelled: { label: "Cancelled", tone: "danger" },
  recovery_expired: { label: "Expired", tone: "danger" },
  execution_failed: { label: "Execution failed", tone: "danger" },
};

export default function VasoolConsole() {
  const [metrics, setMetrics] = useState<MetricsResponse | null>(null);
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [killSwitch, setKillSwitchState] = useState(false);
  const [selected, setSelected] = useState<CaseDetail | null>(null);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busyAction, setBusyAction] = useState("");
  const [error, setError] = useState("");
  const [mobileNav, setMobileNav] = useState(false);

  const load = useCallback(async (soft = false) => {
    if (soft) setRefreshing(true); else setLoading(true);
    try {
      const [nextMetrics, nextHealth, nextKillSwitch, nextCases, nextAudit] = await Promise.all([
        getMetrics(), getHealth(), getKillSwitchStatus(), getCases(), getRecentCases(),
      ]);
      const hadFailure = !nextMetrics || !nextHealth || !nextCases;
      if (nextMetrics) setMetrics(nextMetrics);
      if (nextHealth) setHealth(nextHealth);
      if (nextKillSwitch) setKillSwitchState(nextKillSwitch.kill_switch_engaged);
      if (nextCases?.cases) setCases(nextCases.cases);
      setAudit(nextAudit);
      if (hadFailure) setError("Some Vasool data could not be refreshed. Check the connection and retry.");
      else setError("");
    } catch {
      setError("Vasool could not reach the backend. Check the deployment URL and retry.");
    } finally {
      setLoading(false); setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const interval = window.setInterval(() => void load(true), POLL_MS);
    return () => window.clearInterval(interval);
  }, [load]);

  const filteredCases = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return cases.filter((item) => {
      const matchesStatus = statusFilter === "all" || item.status === statusFilter;
      const haystack = `${item.id} ${item.customer_name} ${item.failure_reason} ${item.payment_method}`.toLowerCase();
      return matchesStatus && (!normalized || haystack.includes(normalized));
    });
  }, [cases, query, statusFilter]);

  const openCase = async (id: number) => {
    setBusyAction(`open-${id}`); setError("");
    try {
      const detail = await getCase(id);
      if (!detail) throw new Error("Case details are unavailable right now.");
      setSelected(detail);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the case.");
    } finally { setBusyAction(""); }
  };

  const runAnalysis = async (id: number) => {
    setBusyAction(`analyze-${id}`); setError("");
    try {
      await analyzeCase(id);
      await evaluatePolicy(id);
      const detail = await getCase(id);
      if (!detail) throw new Error("The case was processed but details could not be loaded.");
      setSelected(detail);
      await load(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Analysis failed. No payment was executed.");
    } finally { setBusyAction(""); }
  };

  const handleReview = async (decision: "approve" | "reject") => {
    if (!selected || selected.case.status !== "human_review") return;
    const message = decision === "approve"
      ? `Approve case #${selected.case.id} for the next policy-approved Test Mode execution step?`
      : `Reject recovery for case #${selected.case.id}?`;
    if (!window.confirm(message)) return;
    setBusyAction(`review-${decision}`); setError("");
    try {
      await reviewCase(selected.case.id, decision, decision === "approve" ? "Approved by operator" : "Rejected by operator");
      const detail = await getCase(selected.case.id);
      setSelected(detail ?? selected);
      await load(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "The review decision could not be saved.");
    } finally { setBusyAction(""); }
  };

  const executeSelected = async () => {
    if (!selected || selected.case.status !== "pending_execution") return;
    if (!window.confirm(`Create a Razorpay Test Mode Payment Link for case #${selected.case.id}?\n\nOnly a policy-approved action can reach Razorpay.`)) return;
    setBusyAction(`execute-${selected.case.id}`); setError("");
    try {
      const result = await executeCase(selected.case.id);
      const detail = await getCase(selected.case.id);
      if (detail) setSelected(detail);
      else if (result && typeof result === "object") {
        setError("Recovery was submitted, but the updated case could not be loaded. Refresh to verify.");
      }
      await load(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Execution failed. Check the audit trail before retrying.");
    } finally { setBusyAction(""); }
  };

  const toggleKillSwitch = async () => {
    const next = !killSwitch;
    if (!window.confirm(next ? "Pause automated recovery and route new approvals to review?" : "Resume policy-approved automation?")) return;
    setBusyAction("kill-switch"); setError("");
    try {
      const result = await setKillSwitch(next);
      setKillSwitchState(result.kill_switch_engaged);
      await load(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not change the kill switch.");
    } finally { setBusyAction(""); }
  };

  const reviewed = metrics?.cases_pending_review ?? 0;
  const atRisk = metrics?.revenue_at_risk_inr ?? 0;
  const recovered = metrics?.revenue_recovered_inr ?? 0;
  const recoveryRate = metrics?.recovery_rate_pct ?? 0;

  return (
    <div className="min-h-screen bg-[#f4f7fb] text-[#10162b]">
      <div className="pointer-events-none fixed inset-0 -z-0 bg-[radial-gradient(circle_at_top_right,rgba(68,103,255,0.10),transparent_32%),radial-gradient(circle_at_15%_75%,rgba(14,138,92,0.08),transparent_28%)]" />
      <div className="relative z-10 flex min-h-screen">
        <aside className={`${mobileNav ? "translate-x-0" : "-translate-x-full"} fixed inset-y-0 left-0 z-40 flex w-72 flex-col border-r border-white/10 bg-[#0d1426] text-white shadow-2xl transition-transform lg:static lg:translate-x-0 lg:shadow-none`}>
          <div className="flex items-center gap-3 px-6 py-6">
            <div className="grid h-10 w-10 place-items-center rounded-xl bg-white text-[#10162b]"><span className="font-display text-lg font-extrabold">V</span></div>
            <div><div className="font-display text-lg font-extrabold">Vasool</div><div className="font-data text-[10px] uppercase tracking-[0.18em] text-white/50">Recovery OS</div></div>
          </div>
          <div className="mx-4 rounded-2xl border border-white/10 bg-white/5 p-4">
            <div className="flex items-center justify-between text-[10px] uppercase tracking-[0.16em] text-white/50"><span>Environment</span><span className="rounded-full bg-white/10 px-2 py-0.5">{health?.env ?? "unknown"}</span></div>
            <div className="mt-3 flex items-center gap-2 text-sm font-semibold"><span className={`h-2 w-2 rounded-full ${health?.status === "ok" ? "bg-emerald-400" : "bg-amber-400"}`} />{health?.status === "ok" ? "Systems operational" : "Connection needs attention"}</div>
            <div className="mt-1 text-xs text-white/50">Live data · auto-refresh {POLL_MS / 1000}s</div>
          </div>
          <nav className="mt-8 flex-1 space-y-1 px-4" aria-label="Primary navigation">
            {[["Overview", Activity], ["Recovery queue", CreditCard], ["Policy & safety", ShieldCheck], ["Audit ledger", Clock3]].map(([label, Icon]) => (
              <button key={String(label)} onClick={() => { setMobileNav(false); document.getElementById(String(label).toLowerCase().replaceAll(" ", "-"))?.scrollIntoView({ behavior: "smooth" }); }} className="flex w-full items-center gap-3 rounded-xl px-3 py-3 text-left text-sm text-white/65 transition hover:bg-white/[0.07] hover:text-white"><Icon size={17} />{String(label)}</button>
            ))}
          </nav>
          <div className="border-t border-white/10 p-4"><div className="rounded-2xl bg-white/5 p-4"><div className="flex items-center gap-2 text-xs font-semibold"><LifeBuoy size={15} />Operator safety</div><p className="mt-2 text-xs leading-5 text-white/50">AI recommends. Deterministic policy gates execution. Humans control exceptions.</p></div></div>
        </aside>

        <div className="min-w-0 flex-1">
          <header className="sticky top-0 z-30 border-b border-[#dfe5ef]/80 bg-white/90 backdrop-blur-xl">
            <div className="flex h-16 items-center justify-between px-4 sm:px-6 xl:px-10">
              <div className="flex items-center gap-3"><button className="rounded-lg p-2 hover:bg-[#f1f4f8] lg:hidden" onClick={() => setMobileNav(true)} aria-label="Open navigation"><Menu size={20} /></button><div className="hidden sm:block"><div className="font-display text-sm font-bold">Revenue recovery command center</div><div className="text-xs text-[#667085]">Observe · decide · recover · verify</div></div></div>
              <div className="flex items-center gap-2"><button onClick={() => void load(true)} disabled={refreshing} className="inline-flex items-center gap-2 rounded-xl border border-[#dfe5ef] bg-white px-3 py-2 text-xs font-semibold hover:bg-[#f8fafc] disabled:opacity-50"><RefreshCw size={14} className={refreshing ? "animate-spin" : ""} />Refresh</button><button onClick={toggleKillSwitch} disabled={busyAction === "kill-switch"} className={`inline-flex items-center gap-2 rounded-xl px-3 py-2 text-xs font-bold ${killSwitch ? "bg-[#b23a52] text-white" : "border border-[#dfe5ef] bg-white text-[#5d6678] hover:bg-[#f8fafc]"}`}><ShieldCheck size={14} />{killSwitch ? "Automation paused" : "Safety controls"}</button></div>
            </div>
          </header>

          <main className="mx-auto max-w-[1480px] px-4 py-6 sm:px-6 xl:px-10 xl:py-8">
            {error && <div role="alert" className="mb-5 flex items-start gap-3 rounded-2xl border border-[#f3c7d0] bg-[#fff4f6] px-4 py-3 text-sm text-[#982f46]"><AlertTriangle className="mt-0.5 shrink-0" size={17} /><div className="flex-1">{error}</div><button onClick={() => setError("")} aria-label="Dismiss error"><X size={16} /></button></div>}
            {killSwitch && <div className="mb-5 flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-[#f2c7d0] bg-[#fff4f6] px-4 py-3"><div className="flex items-center gap-3"><div className="grid h-9 w-9 place-items-center rounded-xl bg-[#b23a52] text-white"><ShieldCheck size={17} /></div><div><div className="text-sm font-bold text-[#8e2940]">Automation is paused</div><div className="text-xs text-[#a04a5e]">New approval attempts remain paused until the kill switch is released.</div></div></div><button onClick={toggleKillSwitch} className="rounded-xl bg-[#b23a52] px-3 py-2 text-xs font-bold text-white">Resume</button></div>}

            <section id="overview" className="grid gap-5 lg:grid-cols-[1.3fr_0.7fr]">
              <div className="overflow-hidden rounded-3xl border border-[#dfe5ef] bg-[#0d1426] p-6 text-white shadow-[0_20px_70px_rgba(16,22,43,0.16)] sm:p-8">
                <div className="flex flex-wrap items-start justify-between gap-5"><div><div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.06] px-3 py-1.5 text-[10px] font-data uppercase tracking-[0.16em] text-white/60"><Sparkles size={12} />AI revenue recovery</div><h1 className="font-display mt-5 max-w-2xl text-3xl font-extrabold tracking-tight sm:text-4xl">Turn failed payments into <span className="text-[#8ca2ff]">verified recovery.</span></h1><p className="mt-3 max-w-2xl text-sm leading-6 text-white/60">Vasool diagnoses failures, selects a recovery path, applies deterministic controls, and waits for trusted payment evidence before counting revenue as recovered.</p></div><div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-right"><div className="font-data text-[10px] uppercase tracking-[0.18em] text-white/45">Recovery rate</div><div className="font-display mt-1 text-3xl font-extrabold">{recoveryRate.toFixed(1)}%</div><div className="mt-1 text-[11px] text-white/40">verified Outcome value</div></div></div>
                <div className="mt-8 grid gap-3 sm:grid-cols-3"><HeroMetric label="Revenue at risk" value={formatINR(atRisk, { compact: true })} sub={`${metrics?.total_failed_payments ?? 0} failed payments`} /><HeroMetric label="Recovered" value={formatINR(recovered, { compact: true })} sub="verified from recovery outcomes" accent="good" /><HeroMetric label="Needs review" value={String(reviewed)} sub="detected · human · blocked" accent="warn" /></div>
              </div>
              <div id="policy-&-safety" className="rounded-3xl border border-[#dfe5ef] bg-white p-6 shadow-sm">
                <div className="flex items-center justify-between"><div><div className="text-[10px] font-data uppercase tracking-[0.16em] text-[#7a8497]">Control posture</div><h2 className="font-display mt-1 text-lg font-bold">AI proposes. Policy decides.</h2></div><ShieldCheck className="text-[#0e8a5c]" size={21} /></div>
                <div className="mt-5 space-y-2">{["Structured AI output", "Risk escalation", "Consent / opt-out gate", "Confidence floor", "Amount & retry ceilings", "Kill switch + review"].map((item) => <div key={item} className="flex items-center justify-between rounded-2xl bg-[#f7f9fc] px-3 py-2.5"><span className="text-xs font-semibold text-[#364055]">{item}</span><CheckCircle2 size={16} className="text-[#0e8a5c]" /></div>)}</div>
                <div className="mt-4 rounded-2xl border border-[#e4e9f1] p-3"><div className="flex items-center gap-2 text-xs font-bold"><Zap size={14} className="text-[#2b4fd8]" />Outcome verification</div><p className="mt-1 text-xs leading-5 text-[#667085]">Recovered revenue is credited from trusted Razorpay webhook evidence, not from a UI click or an AI prediction.</p></div>
              </div>
            </section>

            <section id="recovery-queue" className="mt-6 rounded-3xl border border-[#dfe5ef] bg-white shadow-sm">
              <div className="border-b border-[#e8edf4] px-5 py-5 sm:px-6"><div className="flex flex-wrap items-start justify-between gap-4"><div><div className="text-[10px] font-data uppercase tracking-[0.16em] text-[#7a8497]">Recovery queue</div><h2 className="font-display mt-1 text-xl font-bold">Cases that need a decision</h2><p className="mt-1 text-xs text-[#7a8497]">Search, inspect, review, and execute only when the current state allows it.</p></div><div className="rounded-full bg-[#edf1ff] px-3 py-1.5 text-[11px] font-bold text-[#2b4fd8]">{filteredCases.length} visible</div></div><div className="mt-4 flex flex-col gap-2 sm:flex-row"><label className="relative min-w-0 flex-1"><Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8a93a5]" /><input aria-label="Search recovery cases" value={query} onChange={(e) => setQuery(e.target.value)} className="h-10 w-full rounded-xl border border-[#dfe5ef] bg-[#fbfcfe] pl-9 pr-3 text-sm outline-none focus:border-[#9daef9]" placeholder="Search case, customer, failure reason…" /></label><label className="relative"><Filter size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#8a93a5]" /><select aria-label="Filter recovery cases" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className="h-10 w-full appearance-none rounded-xl border border-[#dfe5ef] bg-[#fbfcfe] pl-9 pr-9 text-sm outline-none sm:w-52"><option value="all">All statuses</option>{Object.entries(statusMeta).map(([value, meta]) => <option key={value} value={value}>{meta.label}</option>)}</select></label></div></div>
              <div className="divide-y divide-[#eef1f5]">{loading ? Array.from({ length: 5 }).map((_, i) => <div key={i} className="flex animate-pulse items-center gap-4 px-5 py-4 sm:px-6"><div className="h-10 w-10 rounded-xl bg-[#edf1f5]" /><div className="flex-1"><div className="h-3 w-40 rounded bg-[#edf1f5]" /><div className="mt-2 h-2.5 w-56 rounded bg-[#f2f4f8]" /></div><div className="h-7 w-24 rounded-full bg-[#edf1f5]" /></div>) : filteredCases.length === 0 ? <EmptyState hasCases={cases.length > 0} /> : filteredCases.slice(0, 30).map((item) => <CaseRow key={item.id} item={item} selected={selected?.case.id === item.id} loading={busyAction === `open-${item.id}`} onOpen={() => void openCase(item.id)} />)}</div>{filteredCases.length > 30 && <div className="border-t border-[#eef1f5] px-6 py-3 text-center text-xs text-[#7a8497]">Showing the first 30 matches. Narrow the search to inspect more precisely.</div>}
            </section>

            <section id="audit-ledger" className="mt-6 grid gap-5 xl:grid-cols-[minmax(0,1.5fr)_340px]">
              {selected ? <div className="rounded-3xl border border-[#dfe5ef] bg-white shadow-sm"><CaseDetailView detail={selected} busyAction={busyAction} killSwitch={killSwitch} onAnalyze={() => void runAnalysis(selected.case.id)} onReview={handleReview} onExecute={() => void executeSelected()} /></div> : <div className="rounded-3xl border border-dashed border-[#dfe5ef] bg-white p-10 text-center text-sm text-[#7a8497]"><div className="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-[#f1f4f8]"><CircleDot size={19} /></div><p className="mt-4 font-semibold text-[#364055]">Select a case to inspect the decision trail</p><p className="mt-1">The panel will show AI reasoning, policy gates, review state, execution state, and verified recovery.</p></div>}
              <aside className="space-y-5">
                <div className="rounded-3xl border border-[#dfe5ef] bg-white p-5 shadow-sm"><div className="flex items-center justify-between"><div><div className="text-[10px] font-data uppercase tracking-[0.16em] text-[#7a8497]">Guardrails</div><h3 className="font-display mt-1 text-base font-bold">Live safety posture</h3></div><div className={`h-2.5 w-2.5 rounded-full ${killSwitch ? "bg-[#b23a52]" : "bg-[#0e8a5c]"}`} /></div><div className="mt-4 space-y-2">{["Kill switch", "Risk escalation", "Consent gate", "Confidence floor", "Amount ceiling", "Retry ceiling"].map((x) => <div key={x} className="flex items-center justify-between rounded-xl border border-[#e8edf4] px-3 py-2.5"><span className="text-xs font-semibold">{x}</span><span className={`inline-flex items-center gap-1 text-[10px] font-bold ${killSwitch && x === "Kill switch" ? "text-[#b23a52]" : "text-[#0e8a5c]"}`}>{killSwitch && x === "Kill switch" ? <XCircle size={12} /> : <Check size={12} />}{killSwitch && x === "Kill switch" ? "PAUSED" : "ACTIVE"}</span></div>)}</div></div>
                <div className="rounded-3xl border border-[#dfe5ef] bg-white p-5 shadow-sm"><div className="flex items-center justify-between"><div><div className="text-[10px] font-data uppercase tracking-[0.16em] text-[#7a8497]">Audit ledger</div><h3 className="font-display mt-1 text-base font-bold">Recent activity</h3></div><ArrowUpRight size={16} className="text-[#8a93a5]" /></div><div className="mt-4 space-y-3">{audit.slice(0, 8).map((entry) => <AuditItem key={entry.id} entry={entry} />)}{audit.length === 0 && <p className="text-xs text-[#7a8497]">No audit events yet.</p>}</div></div>
              </aside>
            </section>
          </main>
        </div>
      </div>
      {mobileNav && <button className="fixed inset-0 z-30 bg-black/30 lg:hidden" aria-label="Close navigation" onClick={() => setMobileNav(false)} />}
    </div>
  );
}

function HeroMetric({ label, value, sub, accent = "neutral" }: { label: string; value: string; sub: string; accent?: "neutral" | "good" | "warn" }) {
  return <div className="rounded-2xl border border-white/10 bg-white/[0.07] p-4"><div className="text-[10px] font-data uppercase tracking-[0.15em] text-white/45">{label}</div><div className={`font-display mt-2 text-2xl font-extrabold ${accent === "good" ? "text-[#76d8a8]" : accent === "warn" ? "text-[#ffc98d]" : "text-white"}`}>{value}</div><div className="mt-1 text-[11px] text-white/40">{sub}</div></div>;
}

function StatusPill({ tone, label }: { tone: "neutral" | "good" | "warn" | "danger"; label: string }) {
  const cls = tone === "good" ? "bg-[#e7f6ee] text-[#08784e]" : tone === "warn" ? "bg-[#fff1df] text-[#a6560d]" : tone === "danger" ? "bg-[#fdecef] text-[#ac3550]" : "bg-[#eef1f6] text-[#5f687a]";
  return <span className={`rounded-full px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.08em] ${cls}`}>{label}</span>;
}

function CaseRow({ item, selected, loading, onOpen }: { item: CaseSummary; selected: boolean; loading: boolean; onOpen: () => void }) {
  const meta = statusMeta[item.status] ?? { label: item.status.replaceAll("_", " "), tone: "neutral" as const };
  return <button onClick={onOpen} className={`flex w-full items-center gap-4 px-5 py-4 text-left transition sm:px-6 ${selected ? "bg-[#f1f4ff]" : "hover:bg-[#fafbfd]"}`}><div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-[#f0f3f8] text-[#4f5b73]"><CreditCard size={17} /></div><div className="min-w-0 flex-1"><div className="flex items-center gap-2"><span className="font-data text-[10px] uppercase tracking-[0.12em] text-[#8a93a5]">CASE #{item.id}</span><span className="h-1 w-1 rounded-full bg-[#c3cad6]" /><span className="truncate text-[11px] font-semibold capitalize text-[#667085]">{item.failure_reason.replaceAll("_", " ")}</span></div><div className="mt-1 truncate text-sm font-bold text-[#202a3f]">{item.customer_name}</div><div className="mt-0.5 flex flex-wrap gap-x-2 text-xs text-[#7a8497]"><span>{formatINR(item.amount_inr)}</span><span>·</span><span>{item.payment_method}</span><span>·</span><span>attempt {item.attempt_number}</span>{item.outcome_success && <><span>·</span><span className="font-semibold text-[#0e8a5c]">{formatINR(item.outcome_amount_inr)} recovered</span></>}</div></div><div className="flex shrink-0 items-center gap-2"><StatusPill tone={meta.tone} label={meta.label} />{loading ? <Loader2 size={16} className="animate-spin text-[#2b4fd8]" /> : <ChevronRight size={16} className="text-[#a2aaba]" />}</div></button>;
}

function EmptyState({ hasCases }: { hasCases: boolean }) { return <div className="px-6 py-16 text-center"><div className="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-[#f1f4f8] text-[#7a8497]"><Search size={19} /></div><h3 className="mt-4 text-sm font-bold">{hasCases ? "No matching cases" : "No recovery cases found"}</h3><p className="mx-auto mt-1 max-w-sm text-xs leading-5 text-[#7a8497]">{hasCases ? "Try another search term or status filter." : "Seed the backend with failed payments to populate the queue."}</p></div>; }

function AuditItem({ entry }: { entry: AuditEntry }) { const isGood = entry.eventType.includes("succeeded") || entry.eventType.includes("outcome_received"); const isBad = entry.eventType.includes("failed") || entry.eventType.includes("cancelled") || entry.eventType.includes("expired"); const Icon = isGood ? CheckCircle2 : isBad ? XCircle : Activity; const iconClass = isGood ? "text-[#0e8a5c] bg-[#e8f7ef]" : isBad ? "text-[#b23a52] bg-[#fdecef]" : "text-[#2b4fd8] bg-[#edf1ff]"; return <div className="flex gap-3"><div className={`grid h-7 w-7 shrink-0 place-items-center rounded-lg ${iconClass}`}><Icon size={13} /></div><div className="min-w-0"><div className="text-[11px] font-semibold capitalize text-[#3e475a]">{entry.eventType.replaceAll("_", " ")}</div><div className="truncate text-[11px] text-[#7a8497]">Case #{entry.caseId} · {entry.detail}</div><div className="mt-0.5 text-[10px] text-[#a1a9b7]">{formatTime(entry.timestamp)}</div></div></div>; }

function CaseDetailView({ detail, busyAction, killSwitch, onAnalyze, onReview, onExecute }: { detail: CaseDetail; busyAction: string; killSwitch: boolean; onAnalyze: () => void; onReview: (decision: "approve" | "reject") => void; onExecute: () => void }) {
  const { case: item, root_cause: rootCause, strategy, root_cause_meta: rootMeta, strategy_meta: strategyMeta, policy_checks: checks, action, outcome } = detail;
  const meta = statusMeta[item.status] ?? { label: item.status.replaceAll("_", " "), tone: "neutral" as const };
  const reviewReady = item.status === "human_review";
  const actionReady = item.status === "pending_execution";
  const recovered = outcome?.success || item.outcome_success;
  return <div className="p-5 sm:p-7"><div className="flex flex-wrap items-start justify-between gap-4 border-b border-[#e8edf4] pb-5"><div><div className="flex flex-wrap items-center gap-2"><span className="font-data text-[10px] uppercase tracking-[0.15em] text-[#7a8497]">CASE #{item.id}</span><StatusPill tone={meta.tone} label={meta.label} /></div><h2 className="font-display mt-2 text-xl font-bold">{item.customer_name} · {formatINR(item.amount_inr)}</h2><p className="mt-1 text-xs text-[#7a8497]">{item.failure_reason.replaceAll("_", " ")} · {item.payment_method} · attempt {item.attempt_number}</p></div><div className="flex flex-wrap gap-2"><button onClick={onAnalyze} disabled={busyAction.startsWith("analyze-")} className="inline-flex items-center gap-2 rounded-xl border border-[#dfe5ef] bg-white px-3 py-2.5 text-xs font-bold hover:bg-[#f8fafc] disabled:opacity-50">{busyAction.startsWith("analyze-") ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}Analyze</button>{reviewReady && <><button onClick={() => onReview("reject")} disabled={busyAction.startsWith("review-")} className="inline-flex items-center gap-2 rounded-xl border border-[#f1d5db] bg-white px-3 py-2.5 text-xs font-bold text-[#a9344b] disabled:opacity-50">Reject</button><button onClick={() => onReview("approve")} disabled={busyAction.startsWith("review-") || killSwitch} className="inline-flex items-center gap-2 rounded-xl bg-[#2b4fd8] px-3 py-2.5 text-xs font-bold text-white disabled:opacity-50">{busyAction === "review-approve" ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}Approve</button></>}{actionReady && <button onClick={onExecute} disabled={busyAction.startsWith("execute-")} className="inline-flex items-center gap-2 rounded-xl bg-[#0e8a5c] px-3 py-2.5 text-xs font-bold text-white disabled:opacity-50">{busyAction.startsWith("execute-") ? <Loader2 size={14} className="animate-spin" /> : <Zap size={14} />}Execute Test Mode</button>}</div></div>
    <div className="mt-5 grid gap-4 lg:grid-cols-[1.25fr_1fr]"><div className="space-y-4"><div className="grid gap-3 sm:grid-cols-2"><InsightCard icon={<Sparkles size={15} />} label="AI root cause" value={rootCause?.root_cause_category ? rootCause.root_cause_category.replaceAll("_", " ") : "Not analyzed"} sub={rootCause?.reasoning ?? "Run analysis to produce a diagnosis."} meta={rootMeta ? `${Math.round(rootMeta.confidence * 100)}% confidence · ${rootMeta.model_used}` : undefined} /><InsightCard icon={<Zap size={15} />} label="Recommended recovery" value={strategy?.action ? strategy.action.replaceAll("_", " ") : "Not analyzed"} sub={strategy?.reasoning ?? "The recovery strategy will appear after analysis."} meta={strategyMeta ? `${Math.round(strategyMeta.confidence * 100)}% confidence · ${strategyMeta.model_used}` : undefined} /></div><div className="rounded-2xl border border-[#e8edf4] p-4"><div className="flex items-center justify-between"><div><div className="text-[10px] font-data uppercase tracking-[0.15em] text-[#7a8497]">Case context</div><h3 className="mt-1 text-sm font-bold">What Vasool knows before acting</h3></div><UserRound size={16} className="text-[#8a93a5]" /></div><div className="mt-3 grid gap-2 sm:grid-cols-4"><Context value={formatINR(item.amount_inr)} label="Amount" /><Context value={item.payment_method} label="Method" /><Context value={item.customer_opted_out ? "Opted out" : "No opt-out"} label="Consent" /><Context value={`Attempt ${item.attempt_number}`} label="Retry state" /></div></div></div><div className="rounded-2xl border border-[#e8edf4] p-4"><div className="flex items-center gap-2"><ShieldCheck size={15} className="text-[#0e8a5c]" /><div><div className="text-[10px] font-data uppercase tracking-[0.15em] text-[#7a8497]">Policy decision</div><h3 className="mt-1 text-sm font-bold">Every gate is visible</h3></div></div><div className="mt-3 space-y-2">{checks.length ? checks.map((check) => <div key={check.check_name} className={`rounded-xl border px-3 py-2.5 ${check.passed ? "border-[#d8ecdf] bg-[#f7fcf9]" : "border-[#f2d7dc] bg-[#fff8f9]"}`}><div className="flex items-start gap-2">{check.passed ? <CheckCircle2 size={14} className="mt-0.5 shrink-0 text-[#0e8a5c]" /> : <XCircle size={14} className="mt-0.5 shrink-0 text-[#b23a52]" />}<div className="min-w-0"><div className="text-xs font-bold capitalize">{check.check_name.replaceAll("_", " ")}</div><div className="mt-0.5 text-[11px] leading-4 text-[#6e7789]">{check.reason}</div></div></div></div>) : <div className="rounded-xl border border-dashed border-[#dfe5ef] p-4 text-xs text-[#7a8497]">No policy result yet.</div>}</div></div></div>
    {action && <div className="mt-4 rounded-2xl border border-[#dfe5ef] bg-[#fbfcfe] p-4"><div className="flex flex-wrap items-center justify-between gap-3"><div><div className="text-[10px] font-data uppercase tracking-[0.15em] text-[#7a8497]">Recovery action</div><div className="mt-1 text-sm font-bold capitalize">{strategy?.action?.replaceAll("_", " ") ?? "Recovery"} · {action.status.replaceAll("_", " ")}</div></div>{item.payment_link && <a href={item.payment_link} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 rounded-xl border border-[#cfd8f8] bg-white px-3 py-2 text-xs font-bold text-[#2b4fd8]">Open payment link <ArrowUpRight size={13} /></a>}</div>{item.status === "executed" && !recovered && <p className="mt-2 text-xs leading-5 text-[#667085]">Payment Link created. Vasool will count revenue only after trusted Razorpay webhook evidence confirms payment.</p>}</div>}
    {recovered && <div className="mt-4 rounded-2xl border border-[#cfe9da] bg-[#f4fbf6] p-4"><div className="flex items-center gap-3"><CheckCircle2 className="text-[#0e8a5c]" size={20} /><div><div className="text-xs font-bold uppercase tracking-wide text-[#0e8a5c]">Verified recovery</div><div className="mt-1 font-display text-xl font-extrabold text-[#106d49]">{formatINR(item.outcome_amount_inr)} recovered</div><div className="mt-1 text-xs text-[#5e7569]">Credited from webhook-backed outcome data.</div></div></div></div>}
    {item.status === "partially_recovered" && <div className="mt-4 rounded-2xl border border-[#f1dfc6] bg-[#fffaf3] p-4"><div className="text-xs font-bold uppercase tracking-wide text-[#a6560d]">Partial recovery</div><div className="mt-1 font-display text-xl font-extrabold text-[#8d4d12]">{formatINR(item.outcome_amount_inr)} received</div><div className="mt-1 text-xs text-[#7c6a56]">The case remains partially recovered until the final payment state is known.</div></div>}
    <div className="mt-5 rounded-2xl bg-[#f7f9fc] p-4"><div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-[11px] text-[#667085]"><span className="inline-flex items-center gap-1.5"><Clock3 size={13} />Updated {formatTime(item.updated_at)}</span><span className="inline-flex items-center gap-1.5"><Activity size={13} />Status: {meta.label}</span>{actionReady && <span className="inline-flex items-center gap-1.5 font-semibold text-[#0e8a5c]"><Zap size={13} />Policy-approved for Test Mode</span>}{reviewReady && <span className="inline-flex items-center gap-1.5 font-semibold text-[#a6560d]">Human decision required</span>}</div></div>
  </div>;
}

function InsightCard({ icon, label, value, sub, meta }: { icon: ReactNode; label: string; value: string; sub: string; meta?: string }) { return <div className="rounded-2xl border border-[#e8edf4] p-4"><div className="flex items-center gap-2 text-[#2b4fd8]"><span>{icon}</span><span className="text-[10px] font-data uppercase tracking-[0.15em] text-[#7a8497]">{label}</span></div><div className="mt-3 text-sm font-bold capitalize">{value}</div><p className="mt-1 text-xs leading-5 text-[#6e7789]">{sub}</p>{meta && <div className="mt-3 rounded-lg bg-[#f5f7fa] px-2.5 py-1.5 text-[10px] font-data text-[#697386]">{meta}</div>}</div>; }
function Context({ value, label }: { value: string; label: string }) { return <div className="rounded-xl border border-[#e8edf4] bg-white px-3 py-2.5"><div className="text-[10px] uppercase tracking-wide text-[#8a93a5]">{label}</div><div className="mt-1 text-xs font-bold capitalize">{value}</div></div>; }
function formatTime(value: string) { const date = new Date(value); if (Number.isNaN(date.getTime())) return value; return new Intl.DateTimeFormat("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }).format(date); }
