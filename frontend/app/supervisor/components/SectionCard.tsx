import type { ReactNode } from "react";

type SectionCardProps = {
  title: string;
  children: ReactNode;
  collapsible?: boolean;
  open?: boolean;
  onToggle?: () => void;
};

export function SectionCard({
  title,
  children,
  collapsible = false,
  open = true,
  onToggle,
}: SectionCardProps) {
  return (
    <section className="brand-supervisor-card overflow-hidden transition-shadow duration-300 hover:shadow-md">
      <div className="flex items-center justify-between gap-2 border-b border-[rgba(15,23,42,0.06)] bg-gradient-to-r from-[#F8F6F1] to-white px-4 py-3">
        {collapsible ? (
          <button
            type="button"
            onClick={onToggle}
            className="flex w-full items-center gap-2 text-left"
          >
            <span className="text-xs text-brand-dark">{open ? "▼" : "▶"}</span>
            <h2 className="brand-supervisor-section-title">{title}</h2>
          </button>
        ) : (
          <h2 className="brand-supervisor-section-title">{title}</h2>
        )}
        <div className="h-px w-8 bg-gradient-to-r from-brand/60 to-transparent" aria-hidden />
      </div>
      {open ? <div className="p-4 sm:p-5">{children}</div> : null}
    </section>
  );
}
