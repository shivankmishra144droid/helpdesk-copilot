import type { TopicCluster } from "./types";

type TopicSpecializationPickerProps = {
  clusters: TopicCluster[];
  selectedClusterIds: number[];
  supervisorId: string;
  saving: boolean;
  onSupervisorIdChange: (id: string) => void;
  onToggleCluster: (clusterId: number) => void;
  onSave: () => void;
};

export function TopicSpecializationPicker({
  clusters,
  selectedClusterIds,
  supervisorId,
  saving,
  onSupervisorIdChange,
  onToggleCluster,
  onSave,
}: TopicSpecializationPickerProps) {
  return (
    <section className="rounded-2xl border border-[#E5EAF2] bg-[#F8FAFC] p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-bold uppercase tracking-wider text-[#2563EB]">
            Topic specializations
          </p>
          <p className="mt-0.5 text-xs text-[#64748B]">
            Pick clusters you handle — the queue can filter to your topics.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs font-medium text-[#64748B]" htmlFor="supervisor-id">
            ID
          </label>
          <input
            id="supervisor-id"
            type="text"
            value={supervisorId}
            onChange={(e) => onSupervisorIdChange(e.target.value.trim() || "supervisor")}
            className="w-28 rounded-lg border border-[#E5EAF2] bg-white px-2 py-1 text-xs text-[#0F172A]"
          />
          <button
            type="button"
            onClick={onSave}
            disabled={saving}
            className="rounded-lg bg-[#2563EB] px-3 py-1 text-xs font-semibold text-white disabled:opacity-60"
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>

      {clusters.length === 0 ? (
        <p className="mt-3 text-xs text-[#64748B]">
          No topic clusters yet — submit pending queries to see clusters.
        </p>
      ) : (
        <div className="mt-3 flex flex-wrap gap-2">
          {clusters.map((cluster) => {
            const selected = selectedClusterIds.includes(cluster.cluster_id);
            return (
              <button
                key={cluster.cluster_id}
                type="button"
                onClick={() => onToggleCluster(cluster.cluster_id)}
                className={`rounded-full border px-3 py-1.5 text-left text-xs transition-colors ${
                  selected
                    ? "border-[#2563EB] bg-[#EFF6FF] text-[#1D4ED8]"
                    : "border-[#E5EAF2] bg-white text-[#475569] hover:border-[#2563EB]/40"
                }`}
              >
                <span className="font-semibold">{cluster.topic_label}</span>
                <span className="ml-1.5 text-[#94A3B8]">({cluster.count})</span>
              </button>
            );
          })}
        </div>
      )}
    </section>
  );
}
