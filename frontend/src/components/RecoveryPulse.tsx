import { ArrowUpRight, CheckCircle2, ShieldCheck, Zap } from "lucide-react";

type RecoveryPulseProps = {
  recoveryRate: number;
  atRisk: number;
  recovered: number;
  reviewed: number;
  failed: number;
};

export default function RecoveryPulse({
  recoveryRate,
  atRisk,
  recovered,
  reviewed,
  failed,
}: RecoveryPulseProps) {
  const safeRate = Math.max(0, Math.min(100, recoveryRate));
  const circumference = 2 * Math.PI * 52;
  const offset = circumference - (safeRate / 100) * circumference;

  return (
    <div className="relative flex min-h-[300px] items-center justify-center overflow-hidden rounded-[28px] border border-white/10 bg-white/[0.045] p-5">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_50%_40%,rgba(104,128,255,.20),transparent_54%)]" />
      <div className="vasool-ring absolute h-56 w-56" />
      <div className="vasool-ring absolute h-72 w-72 opacity-60" style={{ animationDirection: "reverse" }} />

      <div className="relative z-10 flex w-full items-center justify-between gap-5">
        <div className="relative mx-auto grid h-36 w-36 shrink-0 place-items-center">
          <svg className="absolute inset-0 h-full w-full -rotate-90" viewBox="0 0 120 120" aria-label={`Recovery rate ${safeRate.toFixed(1)} percent`}>
            <circle cx="60" cy="60" r="52" fill="none" stroke="rgba(255,255,255,.08)" strokeWidth="6" />
            <circle
              cx="60"
              cy="60"
              r="52"
              fill="none"
              stroke="rgba(140,162,255,.95)"
              strokeWidth="6"
              strokeLinecap="round"
              strokeDasharray={circumference}
              strokeDashoffset={offset}
            />
          </svg>
          <div className="vasool-orb absolute h-20 w-20" />
          <div className="relative text-center">
            <div className="font-data text-[9px] uppercase tracking-[0.18em] text-white/45">Verified</div>
            <div className="font-display mt-1 text-2xl font-extrabold text-white">{safeRate.toFixed(1)}%</div>
          </div>
        </div>

        <div className="hidden min-w-0 flex-1 space-y-3 sm:block">
          <PulseStat icon={<ShieldCheck size={13} />} label="Protected surface" value={`${reviewed} review`} />
          <PulseStat icon={<Zap size={13} />} label="Recovered value" value={formatCompactINR(recovered)} good />
          <PulseStat icon={<ArrowUpRight size={13} />} label="At-risk value" value={formatCompactINR(atRisk)} />
          <PulseStat icon={<CheckCircle2 size={13} />} label="Failed payments" value={String(failed)} />
        </div>
      </div>

      <div className="absolute bottom-4 left-5 right-5 flex items-center justify-between border-t border-white/10 pt-3 text-[10px] text-white/40">
        <span className="font-data uppercase tracking-[0.14em]">Recovery engine</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-1.5 w-1.5 rounded-full bg-[#76d8a8] shadow-[0_0_12px_rgba(118,216,168,.8)]" />live signal</span>
      </div>
    </div>
  );
}

function PulseStat({ icon, label, value, good = false }: { icon: React.ReactNode; label: string; value: string; good?: boolean }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-black/10 px-3 py-2.5">
      <div className="flex items-center gap-1.5 text-[9px] uppercase tracking-[0.14em] text-white/40">{icon}{label}</div>
      <div className={`font-data mt-1 text-xs font-semibold ${good ? "text-[#8be2b6]" : "text-white/80"}`}>{value}</div>
    </div>
  );
}

function formatCompactINR(value: number) {
  if (value >= 1_000_000) return `₹${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 100_000) return `₹${(value / 100_000).toFixed(1)}L`;
  if (value >= 1_000) return `₹${(value / 1_000).toFixed(1)}K`;
  return `₹${Math.round(value)}`;
}
