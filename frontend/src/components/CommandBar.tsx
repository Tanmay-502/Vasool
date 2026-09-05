"use client";

import { useEffect, useState } from "react";
import { RefreshCw, ShieldAlert, ShieldCheck, Wifi, WifiOff } from "lucide-react";
import { getHealth, getKillSwitchStatus, setKillSwitch as updateKillSwitch } from "@/lib/api";

type Props = {
  initialOnline: boolean;
  initialKillSwitch: boolean;
};

export function CommandBar({ initialOnline, initialKillSwitch }: Props) {
  const [online, setOnline] = useState(initialOnline);
  const [killSwitch, setKillSwitchState] = useState(initialKillSwitch);
  const [updating, setUpdating] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const poll = async () => {
      const [health, kill] = await Promise.all([getHealth(), getKillSwitchStatus()]);
      setOnline(health?.status === "ok");
      if (kill) setKillSwitchState(kill.kill_switch_engaged);
    };
    const id = setInterval(poll, 8000);
    return () => clearInterval(id);
  }, []);

  const toggleKillSwitch = async () => {
    const message = killSwitch
      ? "Disengage the kill switch and allow policy-approved automation again?"
      : "Engage the kill switch? All new auto-execution decisions will be routed to human review.";
    if (!window.confirm(message)) return;

    setUpdating(true);
    setError("");
    try {
      const result = await updateKillSwitch(!killSwitch);
      setKillSwitchState(result.kill_switch_engaged);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update the kill switch.");
    } finally {
      setUpdating(false);
    }
  };

  return (
    <div className="flex flex-wrap items-center justify-end gap-2">
      <button
        onClick={() => window.location.reload()}
        title="Refresh dashboard data"
        aria-label="Refresh dashboard data"
        className="inline-flex items-center gap-1.5 rounded-full border border-[#E4E7EE] bg-white px-3 py-1 font-data text-xs font-medium text-[#4B5468] transition hover:border-[#AAB5D8] hover:text-[#10162B]"
      >
        <RefreshCw size={13} />
        Refresh
      </button>
      <span
        className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 font-data text-xs font-medium ${
          online
            ? "border-[#0E8A5C]/25 bg-[#E4F5EC] text-[#0E8A5C]"
            : "border-[#B23A52]/25 bg-[#FBE7EC] text-[#B23A52]"
        }`}
      >
        {online ? <Wifi size={13} /> : <WifiOff size={13} />}
        {online ? "Pipeline online" : "Backend unreachable"}
      </span>
      <button
        onClick={toggleKillSwitch}
        disabled={updating}
        title={killSwitch ? "Disengage kill switch" : "Engage kill switch"}
        className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 font-data text-xs font-medium ${
          killSwitch
            ? "border-[#B4590B]/25 bg-[#FBEEDF] text-[#B4590B]"
            : "border-[#2B4FD8]/20 bg-[#E8ECFC] text-[#2B4FD8]"
        } disabled:opacity-60`}
      >
        {killSwitch ? <ShieldAlert size={13} /> : <ShieldCheck size={13} />}
        {killSwitch ? "Kill switch engaged" : "Kill switch armed"}
      </button>
      <span className="hidden text-[11px] text-[#4B5468] xl:inline">Safety controls</span>
      {error && <span className="basis-full text-right text-[11px] text-[#B23A52]">{error}</span>}
    </div>
  );
}