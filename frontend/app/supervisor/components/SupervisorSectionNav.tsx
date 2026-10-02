"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

type Props = {
  pendingCount?: number;
};

export function SupervisorSectionNav({ pendingCount }: Props) {
  const pathname = usePathname();
  const onAnalytics = pathname === "/supervisor/analytics";
  const onQueries = pathname === "/supervisor";

  const tabClass = (active: boolean) =>
    [
      "inline-flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold transition-all duration-300",
      active
        ? "brand-supervisor-nav-tab-active"
        : "brand-supervisor-nav-tab-inactive",
    ].join(" ");

  return (
    <nav
      className="brand-supervisor-nav flex flex-wrap items-center gap-1 rounded-2xl p-1"
      aria-label="Supervisor sections"
    >
      <Link href="/supervisor" className={tabClass(onQueries)}>
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="h-4 w-4"
          aria-hidden
        >
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
        </svg>
        Query Review
        {typeof pendingCount === "number" && pendingCount > 0 ? (
          <span
            className={[
              "rounded-full px-2 py-0.5 text-xs font-bold",
              onQueries
                ? "bg-brand/25 text-brand"
                : "bg-brand-soft text-brand-dark",
            ].join(" ")}
          >
            {pendingCount}
          </span>
        ) : null}
      </Link>
      <Link href="/supervisor/analytics" className={tabClass(onAnalytics)}>
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="h-4 w-4"
          aria-hidden
        >
          <path d="M3 3v18h18" />
          <path d="M18 17V9" />
          <path d="M13 17V5" />
          <path d="M8 17v-3" />
        </svg>
        Analytics
      </Link>
    </nav>
  );
}
