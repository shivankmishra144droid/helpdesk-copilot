import type { IssueDetail } from "./types";
import { formatTime } from "./utils";
import { CallerBadge } from "./StatusBadge";
import { SectionCard } from "./SectionCard";

type OriginalQuerySectionProps = {
  detail: IssueDetail;
};

export function OriginalQuerySection({ detail }: OriginalQuerySectionProps) {
  return (
    <SectionCard title="Original Query">
      <div className="space-y-2 rounded-2xl border border-brand-border/20 bg-gradient-to-br from-brand-soft/30 to-[#F8F6F1] px-4 py-4">
        <p className="whitespace-pre-wrap text-sm leading-relaxed text-[#0F172A]">
          {detail.query}
        </p>
        <div className="flex flex-wrap items-center gap-2 border-t border-brand-border/15 pt-3">
          <CallerBadge callerType={detail.caller_type} />
          <span className="text-xs text-[#64748B]">
            Submitted {formatTime(detail.submitted_at || detail.created_at)}
          </span>
          {detail.source_document ? (
            <span className="text-xs font-medium text-brand-dark">
              · {detail.source_document}
            </span>
          ) : null}
        </div>
      </div>
    </SectionCard>
  );
}
