import type { ReactNode } from "react";

export function DashboardCard({
  title,
  subtitle,
  children,
  className = "",
}: {
  title?: string;
  subtitle?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-2xl border border-[#E4E7EE] bg-white p-6 ${className}`}>
      {title && <h2 className="font-display text-sm font-semibold text-[#10162B]">{title}</h2>}
      {subtitle && <p className="mt-1 text-xs text-[#4B5468]">{subtitle}</p>}
      {children}
    </section>
  );
}