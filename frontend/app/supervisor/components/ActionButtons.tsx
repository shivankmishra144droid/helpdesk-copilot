type ActionButtonsProps = {
  editable: boolean;
  busy: boolean;
  targetKb: "seller" | "buyer";
  llmRedraftRecommended?: boolean;
  llmAvailable?: boolean;
  onTargetKbChange: (kb: "seller" | "buyer") => void;
  onApproveAndAdd: () => void;
  onRejectClick: () => void;
  onRegenerateDraft?: () => void;
};

export function ActionButtons({
  editable,
  busy,
  targetKb,
  llmRedraftRecommended,
  llmAvailable,
  onTargetKbChange,
  onApproveAndAdd,
  onRejectClick,
  onRegenerateDraft,
}: ActionButtonsProps) {
  if (!editable) return null;

  return (
    <div className="space-y-4 border-t border-[rgba(15,23,42,0.08)] pt-5">
      <div>
        <p className="brand-supervisor-label mb-2">
          Target knowledge base
        </p>
        <div className="flex gap-2">
          {(["seller", "buyer"] as const).map((kb) => (
            <button
              key={kb}
              type="button"
              onClick={() => onTargetKbChange(kb)}
              disabled={busy}
              className={`rounded-xl border px-5 py-2.5 text-sm font-semibold capitalize transition-all duration-300 focus:outline-none focus-visible:ring-4 focus-visible:ring-brand/15 disabled:opacity-50 ${
                targetKb === kb
                  ? "border-brand-border/50 bg-brand-soft/60 text-brand-dark shadow-sm"
                  : "brand-supervisor-btn-ghost border-[rgba(15,23,42,0.08)] text-[#64748B]"
              }`}
            >
              {kb}
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        {onRegenerateDraft ? (
          <button
            type="button"
            onClick={onRegenerateDraft}
            disabled={busy || llmAvailable === false}
            title={
              llmAvailable === false
                ? "Configure an AI provider to format resolution with AI"
                : "Format or polish your written resolution with AI"
            }
            className="brand-supervisor-btn-primary rounded-xl px-5 py-2.5 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? "Formatting…" : "Generate with AI"}
          </button>
        ) : null}
        <button
          type="button"
          onClick={onApproveAndAdd}
          disabled={busy}
          className="brand-supervisor-btn-gold rounded-xl px-5 py-2.5 text-sm font-semibold disabled:opacity-50"
        >
          {busy ? "Saving…" : "Approve & Add to KB"}
        </button>
        <button
          type="button"
          onClick={onRejectClick}
          disabled={busy}
          className="rounded-xl border border-red-200/80 bg-white px-5 py-2.5 text-sm font-semibold text-red-600 transition hover:bg-red-50/80 disabled:opacity-50"
        >
          Reject
        </button>
      </div>
      {llmRedraftRecommended && llmAvailable === false ? (
        <p className="rounded-xl border border-amber-200/80 bg-amber-50/80 px-3 py-2 text-xs text-amber-900">
          Write your resolution notes below, then configure an AI provider and use Generate with AI to
          format them.
        </p>
      ) : null}
    </div>
  );
}
