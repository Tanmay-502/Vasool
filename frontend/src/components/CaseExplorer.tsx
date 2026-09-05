"use client";

import { useState } from "react";
import { CheckCircle2, ChevronRight, CircleAlert, Loader2, Play, ShieldCheck, XCircle } from "lucide-react";
import { analyzeCase, evaluatePolicy, formatINR, getCase, type CaseDetail, type CaseSummary } from "@/lib/api";

export function CaseExplorer({ initialCases }: { initialCases: CaseSummary[] }) {
  const [cases, setCases] = useState(initialCases);
  const [selected, setSelected] = useState<CaseDetail | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");

  const openCase = async (id: number) => {
    setError("");
    const detail = await getCase(id);
    if (!detail) setError("Could not load this case.");
    else setSelected(detail);
  };

  const runDemo = async (id: number) => {
    setRunning(true);
    setError("");
    try {
      await analyzeCase(id);
      await evaluatePolicy(id);
      const detail = await getCase(id);
      if (!detail) throw new Error("The case was processed but its details could not be loaded.");
      setSelected(detail);
      setCases((current) => current.map((item) => item.id === id ? { ...item, status: detail.case.status, updated_at: detail.case.updated_at } : item));
    } catch (err) {
      setError(err instanceof Error ? err.message : "The demo run failed.");
    } finally {
      setRunning(false);
    }
  };

  const activeCase = selected?.case;
  return (
    <section className="rounded-2xl border border-[#E4E7EE] bg-white p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="font-data text-xs uppercase tracking-[0.16em] text-[#4B5468]">Live case room</p>
          <h2 className="font-display mt-1 text-xl font-semibold text-[#10162B]">Explainability & review queue</h2>
          <p className="mt-1 text-sm text-[#4B5468]">Run one case through agents and see every safety decision.</p>
        </div>
        {cases[0] && (
          <button onClick={() => runDemo(cases[0].id)} disabled={running} className="inline-flex items-center gap-2 rounded-lg bg-[#2B4FD8] px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-[#203ca8] disabled:cursor-wait disabled:opacity-60">
            {running ? <Loader2 size={15} className="animate-spin" /> : <Play size={15} />}
            {running ? "Running pipeline…" : "Run demo case"}
          </button>
        )}
      </div>
      {error && <p className="mt-4 rounded-lg bg-[#FBE7EC] px-3 py-2 text-sm text-[#B23A52]">{error}</p>}
      <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(220px,0.75fr)_minmax(0,1.6fr)]">
        <div className="space-y-2">
          {cases.length === 0 ? <p className="rounded-lg border border-dashed border-[#E4E7EE] p-5 text-sm text-[#4B5468]">No recovery cases found.</p> : cases.map((item) => (
            <button key={item.id} onClick={() => openCase(item.id)} className={`flex w-full items-center justify-between rounded-xl border p-3 text-left transition ${activeCase?.id === item.id ? "border-[#2B4FD8] bg-[#E8ECFC]" : "border-[#E4E7EE] hover:border-[#AAB5D8]"}`}>
              <span className="min-w-0">
                <span className="block font-data text-xs text-[#4B5468]">CASE #{item.id} · {item.failure_reason}</span>
                <span className="mt-1 block truncate text-sm font-medium text-[#10162B]">{item.customer_name} · {formatINR(item.amount_inr)}</span>
              </span>
              <span className="ml-2 flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wide text-[#4B5468]">{item.status.replace("_", " ")} <ChevronRight size={14} /></span>
            </button>
          ))}
        </div>
        {activeCase ? <CaseDetailPanel detail={selected!} /> : <div className="flex min-h-56 items-center justify-center rounded-xl border border-dashed border-[#E4E7EE] text-center text-sm text-[#4B5468]"><span>Select a case or run the demo to inspect the decision trail.</span></div>}
      </div>
    </section>
  );
}

function CaseDetailPanel({ detail }: { detail: CaseDetail }) {
  const { case: item, root_cause: rootCause, strategy, policy_checks: checks } = detail;
  const verdict = item.status === "pending_execution" ? "EXECUTE" : item.status === "blocked" ? "BLOCK" : item.status === "human_review" ? "HUMAN REVIEW" : "NOT EVALUATED";
  return (
    <div className="min-w-0">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#E4E7EE] pb-4">
        <div><p className="font-data text-xs text-[#4B5468]">CASE #{item.id} · {item.payment_method.toUpperCase()}</p><p className="mt-1 text-lg font-semibold text-[#10162B]">{item.failure_reason.replaceAll("_", " ")}</p></div>
        <span className={`rounded-full px-3 py-1 font-data text-xs font-semibold ${verdict === "EXECUTE" ? "bg-[#E4F5EC] text-[#0E8A5C]" : verdict === "BLOCK" ? "bg-[#FBE7EC] text-[#B23A52]" : "bg-[#FBEEDF] text-[#B4590B]"}`}>{verdict}</span>
      </div>
      <div className="grid gap-3 py-4 sm:grid-cols-2">
        <Insight label="Root cause" value={rootCause?.root_cause_category?.replaceAll("_", " ") ?? "Not analyzed"} />
        <Insight label="Recommended action" value={strategy?.action?.replaceAll("_", " ") ?? "Not analyzed"} />
        <Insight label="Agent reasoning" value={rootCause?.reasoning ?? strategy?.reasoning ?? "Run analysis to generate reasoning."} />
        <Insight label="Amount at risk" value={formatINR(item.amount_inr)} />
      </div>
      {checks.length > 0 && <div><div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-[#4B5468]"><ShieldCheck size={14} /> Policy checks</div><div className="grid gap-2 sm:grid-cols-2">{checks.map((check) => <div key={check.check_name} className="rounded-lg border border-[#E4E7EE] p-2.5"><div className="flex items-center gap-2 text-xs font-semibold text-[#10162B]">{check.passed ? <CheckCircle2 size={14} className="text-[#0E8A5C]" /> : <XCircle size={14} className="text-[#B23A52]" />}{check.check_name.replaceAll("_", " ")}</div><p className="mt-1 text-[11px] leading-4 text-[#4B5468]">{check.reason}</p></div>)}</div></div>}
      {!rootCause && <div className="mt-3 flex items-center gap-2 text-sm text-[#B4590B]"><CircleAlert size={15} /> This case has not been analyzed yet.</div>}
    </div>
  );
}

function Insight({ label, value }: { label: string; value: string }) {
  return <div className="rounded-lg bg-[#F5F6F8] p-3"><p className="text-[11px] uppercase tracking-wide text-[#4B5468]">{label}</p><p className="mt-1 text-sm font-medium capitalize text-[#10162B]">{value}</p></div>;
}
