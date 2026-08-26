"use client";

import { useEffect, useState } from "react";
import { ShieldAlert, ShieldCheck, Wifi, WifiOff } from "lucide-react";
import { getHealth, getKillSwitchStatus } from "@/lib/api";

type Props = {
  initialOnline: boolean;
  initialKillSwitch: boolean;
};

export function CommandBar({ initialOnline, initialKillSwitch }: Props) {
  const [online, setOnline] = useState(initialOnline);
  const [killSwitch, setKillSwitch] = useState(initialKillSwitch);

  useEffect(() => {
    const poll = async () => {
      const [health, kill] = await Promise.all([getHealth(), getKillSwitchStatus()]);
      setOnline(health?.status === "ok");
      if (kill) setKillSwitch(kill.kill_switch_engaged);
    };
    const id = setInterval(poll, 8000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="flex items-center gap-2">
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
      <span
        className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 font-data text-xs font-medium ${
          killSwitch
            ? "border-[#B4590B]/25 bg-[#FBEEDF] text-[#B4590B]"
            : "border-[#2B4FD8]/20 bg-[#E8ECFC] text-[#2B4FD8]"
        }`}
      >
        {killSwitch ? <ShieldAlert size={13} /> : <ShieldCheck size={13} />}
        {killSwitch ? "Kill switch engaged" : "Kill switch armed"}
      </span>
    </div>
  );
}