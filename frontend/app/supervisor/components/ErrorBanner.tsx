type ErrorBannerProps = {
  message: string;
  onDismiss?: () => void;
};

export function ErrorBanner({ message, onDismiss }: ErrorBannerProps) {
  return (
    <div
      role="alert"
      className="flex items-start justify-between gap-3 border-b border-red-200/60 bg-red-50/90 px-4 py-3 backdrop-blur-sm"
    >
      <p className="text-sm text-red-800">{message}</p>
      {onDismiss ? (
        <button
          type="button"
          onClick={onDismiss}
          className="shrink-0 text-xs font-medium text-red-600 transition hover:text-red-800"
        >
          Dismiss
        </button>
      ) : null}
    </div>
  );
}
