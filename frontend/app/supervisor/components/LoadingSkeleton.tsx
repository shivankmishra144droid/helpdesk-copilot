export function QueueSkeleton() {
  return (
    <div className="space-y-2 p-1">
      {Array.from({ length: 5 }).map((_, i) => (
        <div
          key={i}
          className="space-y-2 rounded-2xl border border-[rgba(15,23,42,0.06)] p-3"
        >
          <div className="flex justify-between gap-2">
            <div className="brand-supervisor-shimmer h-4 w-16 rounded-full" />
            <div className="brand-supervisor-shimmer h-3 w-12 rounded" />
          </div>
          <div className="brand-supervisor-shimmer h-4 w-full rounded" />
          <div className="brand-supervisor-shimmer h-3 w-2/3 rounded" />
        </div>
      ))}
    </div>
  );
}

export function DetailSkeleton() {
  return (
    <div className="space-y-5">
      <div className="brand-supervisor-shimmer h-5 w-48 rounded" />
      <div className="space-y-3 rounded-2xl border border-[rgba(15,23,42,0.06)] p-5">
        <div className="brand-supervisor-shimmer h-4 w-32 rounded" />
        <div className="brand-supervisor-shimmer h-20 w-full rounded-xl" />
      </div>
      <div className="space-y-2 rounded-2xl border border-[rgba(15,23,42,0.06)] p-5">
        <div className="brand-supervisor-shimmer h-4 w-40 rounded" />
        <div className="flex flex-wrap gap-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="brand-supervisor-shimmer h-7 w-28 rounded-full" />
          ))}
        </div>
      </div>
      <div className="space-y-3 rounded-2xl border border-[rgba(15,23,42,0.06)] p-5">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="space-y-1">
            <div className="brand-supervisor-shimmer h-3 w-24 rounded" />
            <div className="brand-supervisor-shimmer h-10 w-full rounded-xl" />
          </div>
        ))}
      </div>
    </div>
  );
}
