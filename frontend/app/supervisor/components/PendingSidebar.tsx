import type { PendingIssue } from "./types";
import { pendingKey } from "./types";
import { formatTime, truncate } from "./utils";
import { CallerBadge, StatusBadge } from "./StatusBadge";
import { QueueSkeleton } from "./LoadingSkeleton";
import { BatchActionBar } from "./BatchActionBar";

type QueueFilterMode = "all" | "my_clusters";

type PendingSidebarProps = {
  queue: PendingIssue[];
  selectedKey: string | null;
  selectedPendingIds: Set<string>;
  isLoading: boolean;
  mobileOpen: boolean;
  batchBusy: boolean;
  filterMode: QueueFilterMode;
  clusterFilterId: number | null;
  clusterOptions: { cluster_id: number; topic_label: string; count: number }[];
  onFilterModeChange: (mode: QueueFilterMode) => void;
  onClusterFilterChange: (clusterId: number | null) => void;
  onSelect: (key: string) => void;
  onToggleSelect: (pendingId: string) => void;
  onSelectAll: () => void;
  onClearSelection: () => void;
  onBatchApprove: () => void;
  onBatchReject: () => void;
  onCloseMobile: () => void;
};

export function PendingSidebar({
  queue,
  selectedKey,
  selectedPendingIds,
  isLoading,
  mobileOpen,
  batchBusy,
  filterMode,
  clusterFilterId,
  clusterOptions,
  onFilterModeChange,
  onClusterFilterChange,
  onSelect,
  onToggleSelect,
  onSelectAll,
  onClearSelection,
  onBatchApprove,
  onBatchReject,
  onCloseMobile,
}: PendingSidebarProps) {
  const selectableIds = queue
    .map((item) => item.pending_id)
    .filter((id): id is string => Boolean(id));
  const allSelected =
    selectableIds.length > 0 &&
    selectableIds.every((id) => selectedPendingIds.has(id));

  return (
    <>
      <aside
        className={`brand-supervisor-slide-left brand-supervisor-sidebar fixed bottom-0 left-0 top-[4.5rem] z-30 flex w-[85vw] max-w-sm flex-col shadow-2xl backdrop-blur-md transition-transform duration-300 ease-out lg:static lg:max-w-none lg:min-h-full lg:w-[30%] lg:translate-x-0 lg:shadow-none ${
          mobileOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0"
        }`}
      >
        <div className="shrink-0 border-b border-[rgba(15,23,42,0.08)] bg-gradient-to-r from-brand-soft/40 to-white px-4 py-4">
          <div className="flex items-center justify-between gap-2">
            <div>
              <p className="brand-supervisor-section-title text-brand-dark">
                Pending Queue
              </p>
              <p className="mt-0.5 text-xs tracking-wide text-[#64748B]">
                {queue.length} awaiting review · auto-refresh 10s
              </p>
            </div>
            {queue.length > 0 ? (
              <label className="flex shrink-0 cursor-pointer items-center gap-1.5 text-xs font-medium text-[#64748B]">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={onSelectAll}
                  disabled={batchBusy || selectableIds.length === 0}
                  className="rounded border-[rgba(15,23,42,0.12)] text-brand-dark focus:ring-brand/20"
                />
                All
              </label>
            ) : null}
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <div className="inline-flex rounded-lg border border-[rgba(15,23,42,0.12)] bg-white p-0.5 text-[10px] font-semibold">
              <button
                type="button"
                onClick={() => onFilterModeChange("all")}
                className={`rounded-md px-2 py-1 ${
                  filterMode === "all"
                    ? "bg-[#0F172A] text-brand"
                    : "text-[#64748B] hover:text-[#0F172A]"
                }`}
              >
                All
              </button>
              <button
                type="button"
                onClick={() => onFilterModeChange("my_clusters")}
                className={`rounded-md px-2 py-1 ${
                  filterMode === "my_clusters"
                    ? "bg-[#0F172A] text-brand"
                    : "text-[#64748B] hover:text-[#0F172A]"
                }`}
              >
                My clusters
              </button>
            </div>
            {clusterOptions.length > 0 ? (
              <select
                value={clusterFilterId ?? ""}
                onChange={(e) => {
                  const value = e.target.value;
                  onClusterFilterChange(value === "" ? null : Number(value));
                }}
                className="max-w-[10rem] rounded-lg border border-[rgba(15,23,42,0.12)] bg-white px-2 py-1 text-[10px] text-[#475569]"
                aria-label="Filter by topic cluster"
              >
                <option value="">All topics</option>
                {clusterOptions.map((cluster) => (
                  <option key={cluster.cluster_id} value={cluster.cluster_id}>
                    {cluster.topic_label} ({cluster.count})
                  </option>
                ))}
              </select>
            ) : null}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-3">
          {isLoading && queue.length === 0 ? (
            <QueueSkeleton />
          ) : queue.length === 0 ? (
            <div className="brand-supervisor-scale-in px-4 py-12 text-center">
              <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-[#0F172A] to-[#1e293b] text-brand shadow-md">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-5 w-5" aria-hidden>
                  <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" /><path d="m9 11 3 3L22 4" />
                </svg>
              </div>
              <p className="text-sm font-semibold text-[#0F172A]">Queue is clear</p>
              <p className="mt-1 text-xs text-[#64748B]">No pending issues right now</p>
            </div>
          ) : (
            <div className="space-y-2">
              {queue.map((item, index) => {
                const key = pendingKey(item);
                const isSelected = key === selectedKey;
                const pid = item.pending_id;
                const checked = pid ? selectedPendingIds.has(pid) : false;
                return (
                  <div
                    key={key}
                    className={`brand-supervisor-fade-in flex items-start gap-2 rounded-2xl px-2.5 py-2.5 ${
                      isSelected
                        ? "brand-supervisor-queue-selected"
                        : "brand-supervisor-queue-item"
                    }`}
                    style={{ animationDelay: `${Math.min(index * 50, 300)}ms` }}
                  >
                    {pid ? (
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => onToggleSelect(pid)}
                        disabled={batchBusy}
                        className="mt-1 shrink-0 rounded border-[rgba(15,23,42,0.12)] text-brand-dark"
                        aria-label={`Select ${item.query || item.issue_name}`}
                      />
                    ) : (
                      <span className="w-4 shrink-0" />
                    )}
                    <button
                      type="button"
                      onClick={() => {
                        onSelect(key);
                        onCloseMobile();
                      }}
                      className="min-w-0 flex-1 text-left"
                    >
                      <div className="mb-1.5 flex items-start justify-between gap-2">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <CallerBadge callerType={item.caller_type} />
                          <StatusBadge status={item.status} />
                          {item.topic_label ? (
                            <span className="rounded-full bg-violet-50 px-2 py-0.5 text-[10px] font-medium text-violet-700">
                              {truncate(item.topic_label, 28)}
                            </span>
                          ) : null}
                        </div>
                        <span className="shrink-0 text-[10px] tracking-wide text-[#94A3B8]">
                          {formatTime(item.created_at)}
                        </span>
                      </div>
                      <p className="text-sm leading-snug text-[#0F172A]">
                        {truncate(item.query || item.issue_name, 100)}
                      </p>
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        <BatchActionBar
          selectedCount={selectedPendingIds.size}
          busy={batchBusy}
          onApprove={onBatchApprove}
          onReject={onBatchReject}
          onClear={onClearSelection}
        />
      </aside>

      {mobileOpen ? (
        <button
          type="button"
          aria-label="Close queue drawer"
          className="fixed inset-0 top-[4.5rem] z-20 bg-[#0F172A]/40 backdrop-blur-[2px] transition-opacity lg:hidden"
          onClick={onCloseMobile}
        />
      ) : null}
    </>
  );
}
