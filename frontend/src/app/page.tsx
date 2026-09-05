import { getCases, getHealth, getKillSwitchStatus, getMetrics, getRecentCases } from "@/lib/api";
import { CommandBar } from "@/components/CommandBar";
import { RecoveryLedgerHero } from "@/components/RecoveryLedgerHero";
import { GuardrailChips } from "@/components/GuardrailChips";
import { FailureReasonBars } from "@/components/FailureReasonBars";
import { AgentQueueGrid } from "@/components/AgentQueueGrid";
import { AuditLedger } from "@/components/AuditLedger";
import { CaseExplorer } from "@/components/CaseExplorer";

export default async function Home() {
  const [metrics, health, killSwitch, recentCases, cases] = await Promise.all([
    getMetrics(),
    getHealth(),
    getKillSwitchStatus(),
    getRecentCases(),
    getCases(),
  ]);

  return (
    <main className="bg-dot-grid min-h-screen">
      <div className="mx-auto max-w-6xl px-6 py-10">
        <header className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="font-data text-xs uppercase tracking-[0.2em] text-[#4B5468]">
              Razorpay AI Buildathon · Track 03
            </p>
            <h1 className="font-display mt-1 text-3xl font-bold text-[#10162B]">Vasool</h1>
            <p className="mt-1 max-w-xl text-sm text-[#4B5468]">Explainable, policy-gated recovery for failed payments — with a human in control.</p>
          </div>
          <CommandBar
            initialOnline={health?.status === "ok"}
            initialKillSwitch={killSwitch?.kill_switch_engaged ?? false}
          />
        </header>

        <div className="mt-8">
          <RecoveryLedgerHero metrics={metrics} />
        </div>

        <div className="mt-6">
          <GuardrailChips killSwitchEngaged={killSwitch?.kill_switch_engaged ?? false} />
        </div>

        <div className="mt-6">
          <CaseExplorer initialCases={cases?.cases ?? []} />
        </div>

        <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-[1.4fr_1fr]">
          <div className="flex flex-col gap-6">
            <AgentQueueGrid pendingReview={metrics?.cases_pending_review ?? 0} />
            <FailureReasonBars data={metrics?.by_failure_reason ?? []} />
          </div>
          <AuditLedger entries={recentCases} />
        </div>
      </div>
    </main>
  );
}