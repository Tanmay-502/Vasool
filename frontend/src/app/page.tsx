import VasoolConsole from "@/components/VasoolConsole";

export default function Home() {
  return (
    <div className="vasool-app-shell">
      <div className="vasool-app-orb vasool-app-orb-one" aria-hidden="true" />
      <div className="vasool-app-orb vasool-app-orb-two" aria-hidden="true" />
      <div className="relative z-10">
        <VasoolConsole />
      </div>
    </div>
  );
}
