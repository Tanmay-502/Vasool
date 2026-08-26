import { Receipt } from "lucide-react";

export type AuditEntry = {
  id: number | string;
  timestamp: string; // ISO 8601
  caseId: number;
  eventType: "execution_started" | "execution_succeeded" | "execution_failed" | string;
  detail: string;
};

const STAMP: Record<string, { label: string; className: string }> = {
  execution_succeeded: { label: "RECOVERED", className: "text-[#0E8A5C] border-[#0E8A5C]/40" },
  execution_failed: { label: "FAILED", className: "text-[#B23A52] border-[#B23A52]/40" },
  execution_started: { label: "IN PROGRESS", className: "text-[#B4590B] border-[#B4590B]/40" },
};

export function AuditLedger({ entries }: { entries: AuditEntry[] }) {
  return (
    <div className="ledger-perforation rounded-2xl border border-[#E4E7EE] bg-white p-6 pt-8">
      <div className="flex items-center gap-2">
        <Receipt size={16} className="text-[#10162B]" />
        <h2 className="font-display text-sm font-semibold text-[#10162B]">Audit ledger</h2>
      </div>
      <p className="mt-1 text-xs text-[#4B5468]">Every action Vasool takes, append-only</p>

      {entries.length === 0 ? (
        <div className="mt-8 rounded-xl border border-dashed border-[#E4E7EE] px-4 py-8 text-center">
          <p className="text-sm text-[#4B5468]">No actions logged yet.</p>
          <p className="mt-1 text-xs text-[#4B5468]">
            The ledger fills in as cases move through analysis and execution.
          </p>
        </div>
      ) : (
        <ul className="mt-5 divide-y divide-dashed divide-[#E4E7EE]">
          {entries.map((entry) => {
            const stamp =
              STAMP[entry.eventType] ?? { label: entry.eventType, className: "text-[#4B5468] border-[#E4E7EE]" };
            return (
              <li key={entry.id} className="flex items-center justify-between gap-3 py-3">
                <div className="min-w-0">
                  <p className="font-data text-xs text-[#4B5468]">
                    {new Date(entry.timestamp).toLocaleString("en-IN")} · case #{entry.caseId}
                  </p>
                  <p className="mt-0.5 truncate text-sm text-[#10162B]">{entry.detail}</p>
                </div>
                <span
                  className={`shrink-0 rounded border px-2 py-0.5 font-data text-[10px] font-semibold tracking-wide ${stamp.className}`}
                >
                  {stamp.label}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}