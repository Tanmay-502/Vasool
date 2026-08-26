import { formatINR, type FailureReasonBreakdown } from "@/lib/api";

export function FailureReasonBars({ data }: { data: FailureReasonBreakdown[] }) {
  if (data.length === 0) {
    return (
      <div className="rounded-2xl border border-[#E4E7EE] bg-white p-6">
        <h2 className="font-display text-sm font-semibold text-[#10162B]">
          Failure reasons in this batch
        </h2>
        <p className="mt-3 text-xs text-[#4B5468]">
          No failed payments in the database yet — run the synthetic data generator.
        </p>
      </div>
    );
  }

  const max = Math.max(...data.map((d) => d.count), 1);

  return (
    <div className="rounded-2xl border border-[#E4E7EE] bg-white p-6">
      <h2 className="font-display text-sm font-semibold text-[#10162B]">
        Failure reasons in this batch
      </h2>
      <p className="mt-1 text-xs text-[#4B5468]">By volume, from the seeded evaluation dataset</p>

      <div className="mt-5 space-y-3">
        {data.map((row) => (
          <div key={row.reason} className="flex items-center gap-3">
            <span className="w-36 shrink-0 truncate text-xs text-[#4B5468]">
              {row.reason.replaceAll("_", " ")}
            </span>
            <div className="h-2 flex-1 overflow-hidden rounded-full bg-[#F5F6F8]">
              <div
                className="h-full rounded-full bg-[#2B4FD8]"
                style={{ width: `${(row.count / max) * 100}%` }}
              />
            </div>
            <span className="font-data w-10 shrink-0 text-right text-xs font-semibold text-[#10162B]">
              {row.count}
            </span>
            <span className="font-data w-24 shrink-0 text-right text-[11px] text-[#4B5468]">
              {formatINR(row.amount_at_risk_paise / 100, { compact: true })}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}