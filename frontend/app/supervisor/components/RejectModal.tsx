type RejectModalProps = {
  open: boolean;
  reason: string;
  busy: boolean;
  onReasonChange: (value: string) => void;
  onConfirm: () => void;
  onCancel: () => void;
};

export function RejectModal({
  open,
  reason,
  busy,
  onReasonChange,
  onConfirm,
  onCancel,
}: RejectModalProps) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button
        type="button"
        aria-label="Close reject dialog"
        className="absolute inset-0 bg-black/40"
        onClick={onCancel}
      />
      <div className="relative w-full max-w-md rounded-xl bg-white border border-gray-200 shadow-xl p-5">
        <h3 className="text-base font-semibold text-gray-900">Reject issue</h3>
        <p className="text-sm text-gray-600 mt-1">
          Provide a reason for rejection (optional). The agent will see this message.
        </p>
        <textarea
          value={reason}
          onChange={(e) => onReasonChange(e.target.value)}
          disabled={busy}
          rows={4}
          placeholder="Reason for rejection…"
          className="mt-4 w-full text-sm border border-gray-300 rounded-lg px-3 py-2 resize-y focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-60"
          autoFocus
        />
        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="text-sm px-4 py-2 rounded-lg border border-gray-300 text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={busy}
            className="text-sm px-4 py-2 rounded-lg bg-red-600 hover:bg-red-500 text-white font-semibold disabled:opacity-50"
          >
            {busy ? "Rejecting…" : "❌ Reject"}
          </button>
        </div>
      </div>
    </div>
  );
}
