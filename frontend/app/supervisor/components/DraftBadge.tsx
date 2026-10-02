import type { ReactNode } from "react";

type DraftBadgeProps = {
  draftSource?: string | null;
  templateIssueName?: string | null;
};
const LLM_SOURCES = new Set([
  "llm_db_fewshot",
  "llm",
  "llm_format",
  "llm_polish",
]);
const TEMPLATE_SOURCES = new Set([
  "db_template_fallback",
  "fallback",
  "empty_fallback",
]);

export function DraftBadge({ draftSource, templateIssueName }: DraftBadgeProps) {
  if (!draftSource) return null;

  if (LLM_SOURCES.has(draftSource)) {
    return (
      <span className="ml-2 inline-flex items-center rounded-full border border-violet-200 bg-violet-50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-violet-700">
        AI Drafted
      </span>
    );
  }

  if (TEMPLATE_SOURCES.has(draftSource)) {
    const label = templateIssueName
      ? `Template from: ${templateIssueName}`
      : "Template from similar issue";
    return (
      <span className="ml-2 inline-flex items-center rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[10px] font-medium text-amber-800">
        {label}
      </span>
    );
  }

  return null;
}

export function FieldLabel({
  children,
  required,
  draftSource,
  templateIssueName,
}: {
  children: ReactNode;
  required?: boolean;
  draftSource?: string | null;
  templateIssueName?: string | null;
}) {
  return (
    <span className="inline-flex flex-wrap items-center gap-x-1 gap-y-1">
      <span className="text-xs font-medium text-gray-600">
        {children}
        {required ? <span className="text-red-500"> *</span> : null}
      </span>
      <DraftBadge draftSource={draftSource} templateIssueName={templateIssueName} />
    </span>
  );
}
