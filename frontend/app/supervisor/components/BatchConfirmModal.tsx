type BatchConfirmModalProps = {
  open: boolean;
  action: "approve" | "reject";
  count: number;
  busy: boolean;
  rejectReason?: string;
  onRejectReasonChange?: (value: string) => void;
  onConfirm: () => void;
  onCancel: () => void;
};

export function BatchConfirmModal({
  open,
  action,
  count,
  busy,
  rejectReason = "",
  onRejectReasonChange,
  onConfirm,
  onCancel,
}: BatchConfirmModalProps) {
  if (!open) return null;

  const isApprove = action === "approve";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button
        type="button"
        aria-label="Close batch confirmation"
        className="absolute inset-0 bg-black/40"
        onClick={onCancel}
      />
      <div className="relative w-full max-w-md rounded-xl bg-white border border-gray-200 shadow-xl p-5">
        <h3 className="text-base font-semibold text-gray-900">
          {isApprove ? "Approve selected issues" : "Reject selected issues"}
        </h3>
        <p className="text-sm text-gray-600 mt-1">
          {isApprove
            ? `Approve and add ${count} issue${count === 1 ? "" : "s"} to the knowledge base using each draft?`
            : `Reject ${count} selected issue${count === 1 ? "" : "s"}?`}
        </p>

        {!isApprove && onRejectReasonChange ? (
          <textarea
            value={rejectReason}
            onChange={(e) => onRejectReasonChange(e.target.value)}
            disabled={busy}
            rows={3}
            placeholder="Rejection reason (optional)…"
            className="mt-4 w-full text-sm border border-gray-300 rounded-lg px-3 py-2 resize-y focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-60"
          />
        ) : null}

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
            className={`text-sm px-4 py-2 rounded-lg text-white font-semibold disabled:opacity-50 ${
              isApprove
                ? "bg-green-600 hover:bg-green-500"
                : "bg-red-600 hover:bg-red-500"
            }`}
          >
            {busy
              ? isApprove
                ? "Approving…"
                : "Rejecting…"
              : isApprove
                ? `Approve ${count}`
                : `Reject ${count}`}
          </button>
        </div>
      </div>
    </div>
  );
}
