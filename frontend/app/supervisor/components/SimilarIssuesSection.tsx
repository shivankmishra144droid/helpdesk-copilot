"use client";

import { useState } from "react";
import type { SimilarIssue } from "./types";
import { SectionCard } from "./SectionCard";

type SimilarIssuesSectionProps = {
  issues: SimilarIssue[];
};

function SimilarTag({ issue }: { issue: SimilarIssue }) {
  const [expanded, setExpanded] = useState(false);
  const categoryLabel = issue.category || issue.category_id || "uncategorized";
  const label = `${issue.issue_name} (${categoryLabel})`;

  const details =
    issue.agent_script_preview ||
    issue.problem_statement ||
    (issue.resolution_steps?.length
      ? issue.resolution_steps.join(" → ")
      : null);

  return (
    <div className="inline-flex flex-col max-w-full">
      <button
        type="button"
        onClick={() => setExpanded((open) => !open)}
        className={`inline-flex items-center gap-1 rounded-full border px-3 py-1 text-xs font-medium transition text-left ${
          expanded
            ? "border-brand-border/50 bg-brand-soft/60 text-brand-dark"
            : "border-[rgba(15,23,42,0.1)] bg-white text-[#0F172A] hover:border-brand-border/30 hover:bg-brand-soft/30"
        }`}
      >
        <span className="text-[10px]">{expanded ? "▼" : "▶"}</span>
        <span className="truncate max-w-[280px]">{label}</span>
        {issue.source === "kb" ? (
          <span className="ml-1 text-[9px] uppercase text-[#94A3B8]">KB</span>
        ) : null}
        {issue.source === "lms_faq" ? (
          <span className="ml-1 text-[9px] uppercase text-violet-600">FAQ</span>
        ) : null}
      </button>
      {expanded && details ? (
        <p className="mt-1.5 ml-2 max-w-md rounded-lg border border-[rgba(15,23,42,0.06)] bg-[#F8F6F1] px-3 py-2 text-xs text-[#64748B]">
          {details}
        </p>
      ) : null}
    </div>
  );
}

export function SimilarIssuesSection({ issues }: SimilarIssuesSectionProps) {
  if (!issues.length) return null;

  return (
    <SectionCard title="Similar Issues from KB">
      <div className="flex flex-wrap gap-2">
        {issues.map((issue, index) => (
          <SimilarTag
            key={`${issue.issue_name}-${issue.branch_id ?? index}`}
            issue={issue}
          />
        ))}
      </div>
    </SectionCard>
  );
}
