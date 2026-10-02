import type { ReactNode } from "react";

type ChartCardProps = {
  title: string;
  subtitle: string;
  children: ReactNode;
  empty?: boolean;
  emptyMessage?: string;
};

export function ChartCard({
  title,
  subtitle,
  children,
  empty,
  emptyMessage = "No data yet",
}: ChartCardProps) {
  return (
    <div className="brand-supervisor-stat-card p-5">
      <div className="border-b border-[rgba(15,23,42,0.06)] pb-3">
        <h3 className="text-sm font-bold tracking-tight text-[#0F172A]">{title}</h3>
        <p className="mt-1 text-xs tracking-wide text-[#64748B]">{subtitle}</p>
      </div>
      <div className="mt-4 h-72 w-full">
        {empty ? (
          <div className="flex h-full items-center justify-center rounded-xl border border-dashed border-[rgba(15,23,42,0.1)] bg-[#F8F6F1] text-sm text-[#64748B]">
            {emptyMessage}
          </div>
        ) : (
          children
        )}
      </div>
    </div>
  );
}
