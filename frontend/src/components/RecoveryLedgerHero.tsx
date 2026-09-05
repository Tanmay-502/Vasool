import { formatINR, type MetricsResponse } from "@/lib/api";

export function RecoveryLedgerHero({ metrics }: { metrics: MetricsResponse | null }) {
  const recovered = metrics?.revenue_recovered_inr ?? 0;
  const atRisk = metrics?.revenue_at_risk_inr ?? 0;
  const recoveryRate = metrics?.recovery_rate_pct ?? 0;
  const remaining = Math.max(atRisk - recovered, 0);
  const recoveredPct = atRisk > 0 ? Math.min((recovered / atRisk) * 100, 100) : 0;

  return (
    <section className="rounded-2xl border border-[#E4E7EE] bg-white p-8">
      <div className="flex flex-wrap items-end justify-between gap-6">
        <div>
          <p className="font-data text-xs uppercase tracking-[0.18em] text-[#4B5468]">
            Revenue reclaimed · held-out batch
          </p>
          <p className="font-data mt-2 text-6xl font-semibold leading-none text-[#10162B]">
            {formatINR(recovered)}
          </p>
          <p className="mt-2 text-sm text-[#4B5468]">
            of {formatINR(atRisk)} flagged at risk —{" "}
            <span className="font-data font-semibold text-[#0E8A5C]">{recoveryRate}%</span> recovered
          </p>
        </div>

        <div className="grid grid-cols-3 gap-4 sm:gap-8">
          <MiniStat label="Failed payments" value={metrics?.total_failed_payments ?? "—"} />
          <MiniStat label="Failure rate" value={metrics ? `${metrics.failure_rate_pct}%` : "—"} />
          <MiniStat label="Awaiting review" value={metrics?.cases_pending_review ?? "—"} accent="risk" />
        </div>
      </div>

      <div className="mt-6">
        <div className="h-3 w-full overflow-hidden rounded-full bg-[#F5F6F8]">
          <div
            className="h-full rounded-full bg-[#0E8A5C] transition-[width] duration-700"
            style={{ width: `${recoveredPct}%` }}
          />
        </div>
        <div className="mt-2 flex justify-between font-data text-[11px] text-[#4B5468]">
          <span>{formatINR(recovered, { compact: true })} recovered</span>
          <span>{formatINR(remaining, { compact: true })} still at risk</span>
        </div>
      </div>
    </section>
  );
}

function MiniStat({
  label,
  value,
  accent = "default",
}: {
  label: string;
  value: string | number;
  accent?: "default" | "risk";
}) {
  return (
    <div className="text-right">
      <p className="font-data text-xs uppercase tracking-[0.14em] text-[#4B5468]">{label}</p>
      <p
        className={`font-data mt-1 text-2xl font-semibold ${
          accent === "risk" ? "text-[#B4590B]" : "text-[#10162B]"
        }`}
      >
        {value}
      </p>
    </div>
  );
}