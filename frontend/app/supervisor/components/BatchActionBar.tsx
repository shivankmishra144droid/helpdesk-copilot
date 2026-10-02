type BatchActionBarProps = {
  selectedCount: number;
  busy: boolean;
  onApprove: () => void;
  onReject: () => void;
  onClear: () => void;
};

export function BatchActionBar({
  selectedCount,
  busy,
  onApprove,
  onReject,
  onClear,
}: BatchActionBarProps) {
  if (selectedCount === 0) return null;

  return (
    <div className="brand-supervisor-slide-right shrink-0 space-y-2 border-t border-[rgba(15,23,42,0.08)] bg-gradient-to-t from-brand-soft/30 to-[#F8F6F1] px-3 py-3">
      <p className="brand-supervisor-label">
        {selectedCount} selected
      </p>
      <div className="flex flex-wrap gap-1.5">
        <button
          type="button"
          onClick={onApprove}
          disabled={busy}
          className="brand-supervisor-btn-gold rounded-xl px-3 py-2 text-xs font-semibold disabled:opacity-50"
        >
          Approve ({selectedCount})
        </button>
        <button
          type="button"
          onClick={onReject}
          disabled={busy}
          className="rounded-xl border border-red-200/80 bg-white px-3 py-2 text-xs font-semibold text-red-600 transition hover:bg-red-50/80 disabled:opacity-50"
        >
          Reject ({selectedCount})
        </button>
        <button
          type="button"
          onClick={onClear}
          disabled={busy}
          className="px-2 py-2 text-xs font-medium text-[#64748B] transition hover:text-[#0F172A] disabled:opacity-50"
        >
          Clear
        </button>
      </div>
    </div>
  );
}
