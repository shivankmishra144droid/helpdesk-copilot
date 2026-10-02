"use client";

import { useState } from "react";
import type { AuditEntry } from "./types";
import { auditLabel, formatTime } from "./utils";
import { SectionCard } from "./SectionCard";

type AuditTrailProps = {
  history: AuditEntry[];
  isLoading: boolean;
};

export function AuditTrail({ history, isLoading }: AuditTrailProps) {
  const [open, setOpen] = useState(false);

  return (
    <SectionCard
      title="Audit Trail"
      collapsible
      open={open}
      onToggle={() => setOpen((value) => !value)}
    >
      {isLoading ? (
        <p className="animate-pulse text-sm text-[#64748B]">Loading history…</p>
      ) : history.length === 0 ? (
        <p className="text-sm text-[#64748B]">No audit entries yet.</p>
      ) : (
        <ol className="relative ml-2 space-y-4 border-l border-brand-border/30">
          {history.map((entry) => (
            <li key={entry.id} className="ml-4">
              <span className="absolute -left-1.5 mt-1.5 h-3 w-3 rounded-full border-2 border-white bg-brand-dark" />
              <p className="text-sm font-medium text-[#0F172A]">
                {auditLabel(entry.action)}
              </p>
              <p className="mt-0.5 text-xs text-[#64748B]">
                {entry.supervisor_name ? (
                  <span className="font-medium text-[#0F172A]">
                    {entry.supervisor_name}
                  </span>
                ) : (
                  <span className="text-[#94A3B8]">System</span>
                )}
                {" · "}
                {formatTime(entry.timestamp)}
              </p>
              {entry.notes ? (
                <p className="mt-1 rounded border border-[rgba(15,23,42,0.06)] bg-[#F8F6F1] px-2 py-1 text-xs text-[#64748B]">
                  {entry.notes}
                </p>
              ) : null}
            </li>
          ))}
        </ol>
      )}
    </SectionCard>
  );
}
