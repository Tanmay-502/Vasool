import { Gauge, IndianRupee, Repeat, Power } from "lucide-react";

type Props = { killSwitchEngaged: boolean };

const GUARDRAILS = [
  { icon: Gauge, label: "Confidence floor", value: "≥ 0.75" },
  { icon: IndianRupee, label: "Auto-execute ceiling", value: "₹5,000" },
  { icon: Repeat, label: "Retry ceiling", value: "3 attempts" },
];

export function GuardrailChips({ killSwitchEngaged }: Props) {
  return (
    <div className="flex flex-wrap gap-3">
      {GUARDRAILS.map(({ icon: Icon, label, value }) => (
        <div
          key={label}
          className="flex items-center gap-2 rounded-xl border border-[#E4E7EE] bg-white px-3.5 py-2.5"
        >
          <Icon size={15} className="text-[#2B4FD8]" />
          <div className="leading-tight">
            <p className="text-[11px] text-[#4B5468]">{label}</p>
            <p className="font-data text-sm font-semibold text-[#10162B]">{value}</p>
          </div>
        </div>
      ))}
      <div
        className={`flex items-center gap-2 rounded-xl border px-3.5 py-2.5 ${
          killSwitchEngaged ? "border-[#B4590B]/30 bg-[#FBEEDF]" : "border-[#E4E7EE] bg-white"
        }`}
      >
        <Power size={15} className={killSwitchEngaged ? "text-[#B4590B]" : "text-[#0E8A5C]"} />
        <div className="leading-tight">
          <p className="text-[11px] text-[#4B5468]">Global stop</p>
          <p className="font-data text-sm font-semibold text-[#10162B]">
            {killSwitchEngaged ? "Halted" : "Live"}
          </p>
        </div>
      </div>
    </div>
  );
}