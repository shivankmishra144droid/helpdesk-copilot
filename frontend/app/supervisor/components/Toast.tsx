import type { Toast as ToastType } from "./types";

type ToastProps = {
  toast: ToastType;
};

export function Toast({ toast }: ToastProps) {
  return (
    <div
      className={`brand-toast-in fixed bottom-6 right-6 z-50 max-w-sm rounded-2xl border px-5 py-3.5 text-sm font-semibold shadow-xl ${
        toast.type === "success"
          ? "border-emerald-200/80 bg-white text-emerald-800 shadow-emerald-500/10"
          : "border-red-200/80 bg-white text-red-800 shadow-red-500/10"
      }`}
      style={{ animationDuration: "0.5s" }}
    >
      {toast.message}
    </div>
  );
}
