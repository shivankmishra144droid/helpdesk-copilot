import type { AuditEntry, IssueDetail, IssueForm, TopicCategory } from "./types";
import { formatTime } from "./utils";
import { StatusBadge } from "./StatusBadge";
import { SectionCard } from "./SectionCard";
import { DetailSkeleton } from "./LoadingSkeleton";
import { OriginalQuerySection } from "./OriginalQuerySection";
import { SimilarIssuesSection } from "./SimilarIssuesSection";
import { IssueForm as IssueFormFields } from "./IssueForm";
import { ActionButtons } from "./ActionButtons";
import { AuditTrail } from "./AuditTrail";

type DetailPanelProps = {
  selectedKey: string | null;
  detail: IssueDetail | null;
  form: IssueForm;
  categories: TopicCategory[];
  auditHistory: AuditEntry[];
  isLoadingDetail: boolean;
  isLoadingAudit: boolean;
  actionBusy: boolean;
  targetKb: "seller" | "buyer";
  onFormChange: (form: IssueForm) => void;
  onTargetKbChange: (kb: "seller" | "buyer") => void;
  onApproveAndAdd: () => void;
  onRejectClick: () => void;
  onRegenerateDraft?: () => void;
};

export function DetailPanel({
  selectedKey,
  detail,
  form,
  categories,
  auditHistory,
  isLoadingDetail,
  isLoadingAudit,
  actionBusy,
  targetKb,
  onFormChange,
  onTargetKbChange,
  onApproveAndAdd,
  onRejectClick,
  onRegenerateDraft,
}: DetailPanelProps) {
  if (!selectedKey) {
    return (
      <div className="brand-supervisor-scale-in flex min-h-[320px] flex-col items-center justify-center px-6 py-16 text-center">
        <div className="relative mb-5 flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-[#0F172A] to-[#1e293b] text-brand shadow-lg shadow-slate-900/20">
          <div className="absolute inset-0 rounded-2xl ring-1 ring-inset ring-brand/25" />
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="relative h-7 w-7" aria-hidden>
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6" /><path d="M16 13H8" /><path d="M16 17H8" /><path d="M10 9H8" />
          </svg>
        </div>
        <h2 className="mb-2 text-lg font-bold tracking-tight text-[#0F172A]">
          Select a pending issue
        </h2>
        <p className="max-w-md text-sm leading-relaxed text-[#64748B]">
          Choose an item from the queue to review the draft, edit resolution
          fields, and approve or reject.
        </p>
      </div>
    );
  }

  if (isLoadingDetail || !detail) {
    return <DetailSkeleton />;
  }

  return (
    <div className="space-y-5 pb-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="brand-supervisor-label">Review</p>
          <p className="mt-0.5 text-sm text-[#0F172A]">
            Issue #{detail.issue_id} · {formatTime(detail.created_at)} ·{" "}
            <span className="capitalize">{detail.caller_type}</span>
          </p>
        </div>
        <StatusBadge status={detail.status} />
      </div>

      {detail.llm_redraft_recommended &&
      detail.draft_source?.includes("kb") &&
      !detail.draft_source?.includes("llm") ? (
        <div className="rounded-2xl border border-brand-border/30 bg-brand-soft/50 px-4 py-3 text-sm text-brand-dark">
          Edit the resolution fields below — write steps as a paragraph or pipe-separated
          list — then use <strong>Generate with AI</strong> to format or polish them.
        </div>
      ) : null}

      {detail.draft_error ? (
        <div className="rounded-2xl border border-amber-200/80 bg-amber-50/80 px-4 py-3 text-sm text-amber-950">
          Draft note: {detail.draft_error}
          {detail.draft_source ? ` (${detail.draft_source})` : ""}
        </div>
      ) : null}

      <OriginalQuerySection detail={detail} />
      <SimilarIssuesSection issues={detail.similar_issues ?? []} />

      <SectionCard title="Resolution Form">
        {detail.draft_source ? (
          <p className="mb-3 text-xs text-[#64748B]">
            Draft source:{" "}
            <span className="font-medium text-[#0F172A]">{detail.draft_source}</span>
          </p>
        ) : null}
        <IssueFormFields
          form={form}
          categories={categories}
          disabled={!detail.editable || actionBusy}
          draftSource={detail.draft_source}
          templateIssueName={detail.template_issue_name}
          onChange={onFormChange}
        />
        <ActionButtons
          editable={detail.editable}
          busy={actionBusy}
          targetKb={targetKb}
          llmRedraftRecommended={detail.llm_redraft_recommended}
          llmAvailable={detail.llm_available}
          onTargetKbChange={onTargetKbChange}
          onApproveAndAdd={onApproveAndAdd}
          onRejectClick={onRejectClick}
          onRegenerateDraft={onRegenerateDraft}
        />
      </SectionCard>

      <AuditTrail history={auditHistory} isLoading={isLoadingAudit} />
    </div>
  );
}
