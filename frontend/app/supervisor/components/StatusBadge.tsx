import type { PendingStatus } from "./types";

const styles: Record<PendingStatus, string> = {
  drafted: "bg-amber-50/90 text-amber-900 border-amber-200/70",
  approved: "bg-emerald-50/90 text-emerald-800 border-emerald-200/70",
  rejected: "bg-red-50/90 text-red-700 border-red-200/70",
};

export function StatusBadge({ status }: { status: PendingStatus }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ${styles[status]}`}
    >
      {status}
    </span>
  );
}

export function CallerBadge({ callerType }: { callerType: string }) {
  const isSeller = callerType.toLowerCase() === "seller";
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ${
        isSeller
          ? "border-[rgba(15,23,42,0.12)] bg-[#F8F6F1] text-[#0F172A]"
          : "border-brand-border/30 bg-brand-soft/50 text-brand-dark"
      }`}
    >
      {isSeller ? "Seller" : "Buyer"}
    </span>
  );
}
