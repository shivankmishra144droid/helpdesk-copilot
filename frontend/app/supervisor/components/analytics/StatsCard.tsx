type StatsCardProps = {
  label: string;
  value: string | number;
  subtitle: string;
  icon?: string;
  accent?: "navy" | "amber" | "green" | "red" | "gold" | "slate";
  delay?: number;
};

const accentBadgeStyles = {
  navy: "from-[#0F172A] to-[#1e293b] text-brand",
  amber: "from-amber-700 to-amber-600 text-amber-100",
  green: "from-emerald-800 to-emerald-700 text-emerald-100",
  red: "from-red-800 to-red-700 text-red-100",
  gold: "from-[#134e4a] to-brand-dark text-brand-light",
  slate: "from-slate-700 to-slate-600 text-slate-100",
};

export function StatsCard({
  label,
  value,
  subtitle,
  icon,
  accent = "navy",
  delay = 0,
}: StatsCardProps) {
  const badgeStyle = accentBadgeStyles[accent];

  return (
    <div
      className="brand-supervisor-fade-in brand-supervisor-stat-card p-5"
      style={{ animationDelay: `${delay}ms` }}
    >
      <div className="flex items-start justify-between gap-3">
        <p className="brand-supervisor-label">{label}</p>
        {icon ? (
          <span
            className={`brand-supervisor-icon-badge bg-gradient-to-br ${badgeStyle}`}
            aria-hidden
          >
            {icon}
          </span>
        ) : null}
      </div>
      <p className="mt-3 text-3xl font-bold tracking-tight text-[#0F172A]">
        {value}
      </p>
      <p className="mt-1.5 text-xs leading-relaxed text-[#64748B]">{subtitle}</p>
    </div>
  );
}
