"use client";

import Link from "next/link";
import { SupervisorSectionNav } from "./SupervisorSectionNav";

type Props = {
  pendingCount?: number;
  onMobileQueueToggle?: () => void;
  subtitle?: string;
};

export function SupervisorHeader({
  pendingCount,
  onMobileQueueToggle,
  subtitle = "Helpdesk Copilot · Supervisor workspace",
}: Props) {
  return (
    <header className="brand-supervisor-header sticky top-0 z-40">
      <div className="mx-auto max-w-[1600px] space-y-4 px-4 py-4 sm:px-6">
        <div className="flex items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            <div className="relative flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-[#0F172A] to-[#1e293b] text-brand shadow-lg shadow-slate-900/20">
              <div className="absolute inset-0 rounded-2xl ring-1 ring-inset ring-brand/20" />
              <svg
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="relative h-5 w-5"
                aria-hidden
              >
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10" />
                <path d="m9 12 2 2 4-4" />
              </svg>
            </div>
            <div className="min-w-0">
              <h1 className="truncate text-lg font-bold tracking-tight text-[#0F172A] sm:text-xl">
                Supervisor Dashboard
              </h1>
              <p className="truncate text-xs tracking-wide text-[#64748B] sm:text-sm">
                {subtitle}
              </p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {onMobileQueueToggle && typeof pendingCount === "number" ? (
              <button
                type="button"
                onClick={onMobileQueueToggle}
                className="brand-supervisor-btn-primary rounded-xl px-3 py-2 text-sm font-semibold lg:hidden"
              >
                Queue ({pendingCount})
              </button>
            ) : null}
            <Link
              href="/supervisor/categories"
              className="brand-supervisor-btn-ghost rounded-xl px-3 py-2 text-sm font-medium"
            >
              Categories
            </Link>
            <Link
              href="/"
              className="brand-supervisor-btn-ghost rounded-xl px-3 py-2 text-sm font-medium"
            >
              Agent Chat
            </Link>
          </div>
        </div>
        <SupervisorSectionNav pendingCount={pendingCount} />
      </div>
    </header>
  );
}
