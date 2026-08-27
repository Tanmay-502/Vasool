import type { LucideIcon } from "lucide-react";
import {
  AlertTriangle,
  CreditCard,
  Repeat2,
  ShoppingCart,
  CalendarClock,
  Building2,
  ListOrdered,
  Mic,
  HandCoins,
  FlaskConical,
} from "lucide-react";

type Props = { pendingReview: number };

type RoadmapItem = {
  title: string;
  blurb: string;
  metric: string;
  icon: LucideIcon;
};

// Everything here is explicitly out of v1 scope per the PRD ("checkout
// abandonment recovery, B2B receivables chasing" and friends are called
// out as not-built). Rendered as mock queue cards with sample counts and a
// "Demo data" badge on every single one — a judge mistaking a mocked
// number for a real one is worse than the card not existing at all, so
// nothing here is allowed to look live.
const ROADMAP: RoadmapItem[] = [
  {
    title: "Checkout drop-off recovery",
    blurb: "Cart abandoned before payment even started — nudge before it's forgotten.",
    metric: "18 sample carts queued",
    icon: ShoppingCart,
  },
  {
    title: "Failed-subscription retry",
    blurb: "Recurring charge fails silently — catch it before the subscription lapses.",
    metric: "9 sample renewals queued",
    icon: CalendarClock,
  },
  {
    title: "B2B receivables chasing",
    blurb: "Invoice overdue, not a gateway failure — a different playbook entirely.",
    metric: "6 sample invoices queued",
    icon: Building2,
  },
  {
    title: "Mandate retry sequencer",
    blurb: "UPI Autopay / NACH mandate bounced — needs its own retry cadence.",
    metric: "4 sample mandates queued",
    icon: ListOrdered,
  },
  {
    title: "Hinglish voice recovery",
    blurb: "Voice-call nudges in Hinglish for customers who never check email.",
    metric: "Prototype script only",
    icon: Mic,
  },
  {
    title: "Promise-to-pay tracker",
    blurb: 'Customer says "kal kar dunga" — track it, don\'t just trust it.',
    metric: "11 sample promises tracked",
    icon: HandCoins,
  },
];

function DemoDataBadge() {
  return (
    <span className="inline-flex shrink-0 items-center gap-1 rounded-full border border-dashed border-[#C7CCDA] bg-white px-2 py-0.5 font-data text-[9px] font-semibold uppercase tracking-widest text-[#4B5468]">
      <FlaskConical size={9} />
      Demo data
    </span>
  );
}

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

      <div className="mt-6">
        <p className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-widest text-[#4B5468]">
          <Repeat2 size={12} /> Beyond v1 — simulated queues
        </p>
        <p className="mt-1 text-[11px] text-[#4B5468]">
          Same recovery philosophy, different failure surface. Not wired to Razorpay — every card
          below runs on sample data only.
        </p>

        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
          {ROADMAP.map((item) => {
            const Icon = item.icon;
            return (
              <div
                key={item.title}
                className="flex flex-col gap-2 rounded-xl border border-dashed border-[#E4E7EE] bg-[#FAFAFB] p-4"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <div className="rounded-lg bg-[#E4E7EE] p-1.5 text-[#4B5468]">
                      <Icon size={14} />
                    </div>
                    <p className="font-display text-xs font-semibold text-[#10162B]">
                      {item.title}
                    </p>
                  </div>
                  <DemoDataBadge />
                </div>
                <p className="text-[11px] leading-snug text-[#4B5468]">{item.blurb}</p>
                <p className="font-data text-[10px] font-medium text-[#4B5468]">{item.metric}</p>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}