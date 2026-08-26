import { AlertTriangle, CreditCard, Repeat2 } from "lucide-react";

type Props = { pendingReview: number };

// Everything here is explicitly out of v1 scope per the PRD ("checkout
// abandonment recovery, B2B receivables chasing" and friends are called
// out as not-built). Shown as a labelled roadmap, not as working queues —
// a judge clicking into a card that does nothing is worse than not
// showing the card at all.
const ROADMAP = [
  "Checkout drop-off recovery",
  "Failed-subscription retry",
  "B2B receivables chasing",
  "Mandate retry sequencer",
  "Hinglish voice recovery",
  "Promise-to-pay tracker",
];

export function AgentQueueGrid({ pendingReview }: Props) {
  return (
    <div className="rounded-2xl border border-[#E4E7EE] bg-white p-6">
      <div>
        <h2 className="font-display text-sm font-semibold text-[#10162B]">Recovery workflow</h2>
        <p className="mt-1 text-xs text-[#4B5468]">v1 scope, per the PRD — one flow, fully wired</p>
      </div>

      <div className="mt-5 rounded-xl border border-[#2B4FD8]/20 bg-[#E8ECFC]/40 p-5">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <div className="rounded-lg bg-[#2B4FD8] p-2 text-white">
              <CreditCard size={18} />
            </div>
            <div>
              <p className="font-display text-sm font-semibold text-[#10162B]">
                Failed payment recovery
              </p>
              <p className="mt-1 max-w-md text-xs text-[#4B5468]">
                Root cause → recovery strategy → policy gate → Razorpay Test Mode execution.
                Gemini → Groq → deterministic rules fallback on every call.
              </p>
            </div>
          </div>
          <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-[#0E8A5C]/10 px-2.5 py-1 font-data text-[11px] font-semibold text-[#0E8A5C]">
            LIVE
          </span>
        </div>
        <div className="mt-4 flex items-center gap-2 border-t border-[#2B4FD8]/15 pt-4">
          <AlertTriangle size={14} className="text-[#B4590B]" />
          <p className="font-data text-xs text-[#10162B]">
            <span className="font-semibold">{pendingReview}</span> cases awaiting human review
          </p>
        </div>
      </div>

      <div className="mt-5">
        <p className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-[0.1em] text-[#4B5468]">
          <Repeat2 size={12} /> Roadmap — not built in v1
        </p>
        <div className="mt-2.5 flex flex-wrap gap-2">
          {ROADMAP.map((item) => (
            <span
              key={item}
              className="rounded-full border border-dashed border-[#E4E7EE] px-3 py-1.5 text-xs text-[#4B5468]"
            >
              {item}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}