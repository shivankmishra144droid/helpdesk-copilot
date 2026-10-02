"use client";

import { apiFetch } from "../lib/api";
import { useCallback, useEffect, useState } from "react";
import {
  API_BASE,
  EMPTY_FORM,
  POLL_MS,
  SUPERVISOR_ID_KEY,
  type AuditEntry,
  type IssueDetail,
  type IssueForm,
  type PendingIssue,
  type Toast,
  type TopicCategory,
  type TopicCluster,
} from "./components/types";
import { entryToForm, formatApiError, formToEntry } from "./components/utils";
import { ErrorBanner } from "./components/ErrorBanner";
import { PendingSidebar } from "./components/PendingSidebar";
import { DetailPanel } from "./components/DetailPanel";
import { RejectModal } from "./components/RejectModal";
import { BatchConfirmModal } from "./components/BatchConfirmModal";
import { Toast as ToastNotification } from "./components/Toast";
import { SupervisorHeader } from "./components/SupervisorHeader";
import { TopicSpecializationPicker } from "./components/TopicSpecializationPicker";

type QueueFilterMode = "all" | "my_clusters";

export default function SupervisorDashboard() {
  const [queue, setQueue] = useState<PendingIssue[]>([]);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [detail, setDetail] = useState<IssueDetail | null>(null);
  const [form, setForm] = useState<IssueForm>(EMPTY_FORM);
  const [auditHistory, setAuditHistory] = useState<AuditEntry[]>([]);
  const [topicCategories, setTopicCategories] = useState<TopicCategory[]>([]);
  const [targetKb, setTargetKb] = useState<"seller" | "buyer">("seller");
  const [rejectReason, setRejectReason] = useState("");
  const [rejectModalOpen, setRejectModalOpen] = useState(false);
  const [isLoadingQueue, setIsLoadingQueue] = useState(true);
  const [isLoadingDetail, setIsLoadingDetail] = useState(false);
  const [isLoadingAudit, setIsLoadingAudit] = useState(false);
  const [actionBusy, setActionBusy] = useState(false);
  const [toast, setToast] = useState<Toast | null>(null);
  const [mobileQueueOpen, setMobileQueueOpen] = useState(false);
  const [apiError, setApiError] = useState<string | null>(null);
  const [selectedPendingIds, setSelectedPendingIds] = useState<Set<string>>(new Set());
  const [batchBusy, setBatchBusy] = useState(false);
  const [batchModal, setBatchModal] = useState<"approve" | "reject" | null>(null);
  const [batchRejectReason, setBatchRejectReason] = useState("");
  const [supervisorId, setSupervisorId] = useState("supervisor");
  const [topicClusters, setTopicClusters] = useState<TopicCluster[]>([]);
  const [selectedClusterIds, setSelectedClusterIds] = useState<number[]>([]);
  const [filterMode, setFilterMode] = useState<QueueFilterMode>("all");
  const [clusterFilterId, setClusterFilterId] = useState<number | null>(null);
  const [savingSpecs, setSavingSpecs] = useState(false);
  const showToast = useCallback((next: Toast) => {
    setToast(next);
    window.setTimeout(() => setToast(null), 4500);
  }, []);

  const fetchTopicCategories = useCallback(async (callerType: "seller" | "buyer") => {
    try {
      const res = await apiFetch(
        `${API_BASE}/topic-categories?caller_type=${callerType}`
      );
      if (!res.ok) throw new Error("categories");
      const data = await res.json();
      setTopicCategories(data.categories ?? []);
    } catch {
      setTopicCategories([]);
    }
  }, []);

  const fetchTopicClusters = useCallback(async () => {
    try {
      const res = await apiFetch(`${API_BASE}/supervisor/topic-clusters`);
      if (!res.ok) throw new Error("clusters");
      const data = await res.json();
      setTopicClusters(data.clusters ?? []);
    } catch {
      setTopicClusters([]);
    }
  }, []);

  const fetchSpecializations = useCallback(async (id: string) => {
    try {
      const res = await apiFetch(
        `${API_BASE}/supervisor/specializations/${encodeURIComponent(id)}`
      );
      if (!res.ok) throw new Error("specializations");
      const data = await res.json();
      setSelectedClusterIds(data.cluster_ids ?? []);
    } catch {
      setSelectedClusterIds([]);
    }
  }, []);

  const fetchQueue = useCallback(async (silent = false) => {
    if (!silent) setIsLoadingQueue(true);
    try {
      const params = new URLSearchParams();
      if (filterMode === "my_clusters") {
        params.set("my_clusters_only", "true");
        params.set("supervisor_id", supervisorId);
      }
      if (clusterFilterId !== null) {
        params.set("cluster_id", String(clusterFilterId));
      }
      const query = params.toString();
      const url = `${API_BASE}/supervisor/issues/pending${query ? `?${query}` : ""}`;
      const res = await apiFetch(url);
      if (!res.ok) throw new Error("queue");
      const data = await res.json();
      setQueue(data.issues ?? []);
      setApiError(null);
    } catch {
      setApiError("Could not reach supervisor API. Is the backend running on port 8000?");
    } finally {
      if (!silent) setIsLoadingQueue(false);
    }
  }, [filterMode, clusterFilterId, supervisorId]);

  const saveSpecializations = useCallback(async () => {
    setSavingSpecs(true);
    try {
      const res = await apiFetch(`${API_BASE}/supervisor/specializations`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          supervisor_id: supervisorId,
          cluster_ids: selectedClusterIds,
        }),
      });
      if (!res.ok) throw new Error("save specializations");
      window.localStorage.setItem(SUPERVISOR_ID_KEY, supervisorId);
      showToast({ type: "success", message: "Topic specializations saved." });
      await fetchQueue(true);
    } catch {
      showToast({ type: "error", message: "Could not save specializations." });
    } finally {
      setSavingSpecs(false);
    }
  }, [supervisorId, selectedClusterIds, showToast, fetchQueue]);

  const fetchAudit = useCallback(async (key: string) => {
    setIsLoadingAudit(true);
    try {
      const res = await apiFetch(
        `${API_BASE}/supervisor/issues/pending/${encodeURIComponent(key)}/history`
      );
      if (!res.ok) throw new Error("history");
      const data = await res.json();
      setAuditHistory(data.history ?? []);
    } catch {
      setAuditHistory([]);
    } finally {
      setIsLoadingAudit(false);
    }
  }, []);

  const clearSelection = useCallback(() => {
    setSelectedKey(null);
    setDetail(null);
    setForm(EMPTY_FORM);
    setAuditHistory([]);
    setRejectReason("");
    setRejectModalOpen(false);
  }, []);

  const fetchDetail = useCallback(
    async (key: string) => {
      setIsLoadingDetail(true);
      try {
        const res = await apiFetch(
          `${API_BASE}/supervisor/issues/pending/${encodeURIComponent(key)}`
        );
        if (!res.ok) throw new Error("detail");
        const data: IssueDetail = await res.json();
        setDetail(data);
        const entry = data.form ?? data.draft;
        setForm(entryToForm(entry, data.query));
        setTargetKb(data.caller_type === "buyer" ? "buyer" : "seller");
        setApiError(null);
        void fetchAudit(key);
      } catch {
        setApiError("Failed to load issue details from the database.");
        setDetail(null);
      } finally {
        setIsLoadingDetail(false);
      }
    },
    [fetchAudit]
  );

  useEffect(() => {
    const storedId = window.localStorage.getItem(SUPERVISOR_ID_KEY);
    if (storedId) {
      setSupervisorId(storedId);
      void fetchSpecializations(storedId);
    } else {
      void fetchSpecializations("supervisor");
    }
    void fetchTopicClusters();
  }, [fetchSpecializations, fetchTopicClusters]);

  useEffect(() => {
    void fetchQueue();
    const intervalId = window.setInterval(() => {
      void fetchQueue(true);
      void fetchTopicClusters();
    }, POLL_MS);
    return () => window.clearInterval(intervalId);
  }, [fetchQueue, fetchTopicClusters]);

  useEffect(() => {
    void fetchTopicCategories(targetKb);
  }, [targetKb, fetchTopicCategories]);

  useEffect(() => {
    if (!selectedKey) {
      setDetail(null);
      setAuditHistory([]);
      return;
    }
    void fetchDetail(selectedKey);
  }, [selectedKey, fetchDetail]);

  useEffect(() => {
    if (!selectedKey || isLoadingQueue) return;
    const stillPending = queue.some(
      (item) => (item.pending_id ?? `issue-${item.issue_id}`) === selectedKey
    );
    if (!stillPending && queue.length > 0) {
      clearSelection();
    }
  }, [queue, selectedKey, isLoadingQueue, clearSelection]);

  const handleRegenerateDraft = async () => {
    if (!detail?.editable || actionBusy) return;
    const hasSteps = form.resolution_steps.some((step) => step.trim());
    if (!hasSteps && !form.problem_statement.trim()) {
      showToast({
        type: "error",
        message: "Write resolution steps or a problem statement first.",
      });
      return;
    }
    setActionBusy(true);
    try {
      const res = await apiFetch(`${API_BASE}/supervisor/regenerate-draft`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          pending_id: detail.pending_id ?? undefined,
          issue_id: detail.issue_id,
          edited_entry: formToEntry(form),
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => null);
        throw new Error(formatApiError(err, "AI formatting failed"));
      }
      const data: IssueDetail = await res.json();
      setDetail(data);
      const entry = data.form ?? data.draft;
      setForm(entryToForm(entry, data.query));
      showToast({ type: "success", message: "Resolution formatted with AI." });
      if (selectedKey) void fetchAudit(selectedKey);
    } catch (error) {
      showToast({
        type: "error",
        message: error instanceof Error ? error.message : "AI formatting failed.",
      });
    } finally {
      setActionBusy(false);
    }
  };

  const handleApproveAndAdd = async () => {
    if (!detail?.editable) return;
    if (!form.issue_name.trim()) {
      showToast({ type: "error", message: "issue_name is required." });
      return;
    }
    if (!form.category) {
      showToast({ type: "error", message: "Select a category before adding to KB." });
      return;
    }

    setActionBusy(true);
    try {
      const res = await apiFetch(`${API_BASE}/supervisor/approve-and-add`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          issue_id: detail.issue_id,
          pending_id: detail.pending_id ?? undefined,
          edited_entry: formToEntry(form),
          target_kb: targetKb,
          topic_category: form.category || undefined,
          approved_by: "supervisor",
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => null);
        throw new Error(formatApiError(err, "Approve failed"));
      }
      showToast({ type: "success", message: "Approved and added to knowledge base." });
      clearSelection();
      await fetchQueue(true);
    } catch (error) {
      showToast({
        type: "error",
        message: error instanceof Error ? error.message : "Approve failed.",
      });
    } finally {
      setActionBusy(false);
    }
  };

  const handleReject = async () => {
    if (!detail?.editable) return;
    setActionBusy(true);
    try {
      const res = await apiFetch(`${API_BASE}/supervisor/reject`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          issue_id: detail.issue_id,
          pending_id: detail.pending_id ?? undefined,
          reason: rejectReason.trim(),
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => null);
        throw new Error(formatApiError(err, "Reject failed"));
      }
      showToast({ type: "success", message: "Issue rejected." });
      clearSelection();
      await fetchQueue(true);
    } catch (error) {
      showToast({
        type: "error",
        message: error instanceof Error ? error.message : "Reject failed.",
      });
    } finally {
      setActionBusy(false);
    }
  };

  const togglePendingSelect = useCallback((pendingId: string) => {
    setSelectedPendingIds((prev) => {
      const next = new Set(prev);
      if (next.has(pendingId)) next.delete(pendingId);
      else next.add(pendingId);
      return next;
    });
  }, []);

  const handleSelectAll = useCallback(() => {
    const ids = queue
      .map((item) => item.pending_id)
      .filter((id): id is string => Boolean(id));
    setSelectedPendingIds((prev) => {
      const allSelected = ids.length > 0 && ids.every((id) => prev.has(id));
      return allSelected ? new Set() : new Set(ids);
    });
  }, [queue]);

  const clearBatchSelection = useCallback(() => {
    setSelectedPendingIds(new Set());
  }, []);

  const toggleClusterSelection = useCallback((clusterId: number) => {
    setSelectedClusterIds((prev) =>
      prev.includes(clusterId)
        ? prev.filter((id) => id !== clusterId)
        : [...prev, clusterId]
    );
  }, []);

  const handleSupervisorIdChange = useCallback(
    (id: string) => {
      setSupervisorId(id);
      void fetchSpecializations(id);
    },
    [fetchSpecializations]
  );

  const runBatchAction = async (action: "approve" | "reject") => {
    const ids = Array.from(selectedPendingIds);
    if (ids.length === 0) return;

    setBatchBusy(true);
    const verb = action === "approve" ? "Approving" : "Rejecting";
    showToast({ type: "success", message: `${verb} ${ids.length} issues…` });

    try {
      const endpoint =
        action === "approve"
          ? `${API_BASE}/supervisor/batch-approve`
          : `${API_BASE}/supervisor/batch-reject`;
      const body =
        action === "approve"
          ? { pending_ids: ids, supervisor_id: supervisorId }
          : {
              pending_ids: ids,
              supervisor_id: supervisorId,
              reason: batchRejectReason.trim(),
            };

      const res = await apiFetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(formatApiError(data, "Batch action failed"));
      }

      const succeeded =
        action === "approve" ? (data.approved ?? 0) : (data.rejected ?? 0);
      const failed = data.failed ?? 0;
      showToast({
        type: failed > 0 && succeeded === 0 ? "error" : "success",
        message: `Done: ${succeeded} ${action === "approve" ? "approved" : "rejected"}, ${failed} failed`,
      });

      if (selectedKey && ids.some((id) => detail?.pending_id === id)) {
        clearSelection();
      }
      clearBatchSelection();
      setBatchModal(null);
      setBatchRejectReason("");
      await fetchQueue(true);
    } catch (error) {
      showToast({
        type: "error",
        message: error instanceof Error ? error.message : "Batch action failed.",
      });
    } finally {
      setBatchBusy(false);
    }
  };

  return (
    <div className="brand-supervisor-bg flex min-h-screen flex-col text-[#0F172A]">
      <SupervisorHeader
        pendingCount={queue.length}
        onMobileQueueToggle={() => setMobileQueueOpen((open) => !open)}
        subtitle="Helpdesk Copilot · Review pending queries"
      />

      {apiError ? (
        <ErrorBanner message={apiError} onDismiss={() => setApiError(null)} />
      ) : null}

      <div className="relative mx-auto flex min-h-[calc(100vh-7.5rem)] w-full max-w-[1600px] flex-1 gap-0">
        <PendingSidebar
          queue={queue}
          selectedKey={selectedKey}
          selectedPendingIds={selectedPendingIds}
          isLoading={isLoadingQueue}
          mobileOpen={mobileQueueOpen}
          batchBusy={batchBusy}
          filterMode={filterMode}
          clusterFilterId={clusterFilterId}
          clusterOptions={topicClusters}
          onFilterModeChange={setFilterMode}
          onClusterFilterChange={setClusterFilterId}
          onSelect={setSelectedKey}
          onToggleSelect={togglePendingSelect}
          onSelectAll={handleSelectAll}
          onClearSelection={clearBatchSelection}
          onBatchApprove={() => setBatchModal("approve")}
          onBatchReject={() => setBatchModal("reject")}
          onCloseMobile={() => setMobileQueueOpen(false)}
        />

        <main className="max-h-[calc(100vh-7.5rem)] min-w-0 flex-1 overflow-y-auto p-4 sm:p-6 lg:w-[70%]">
          <div className="mb-4">
            <TopicSpecializationPicker
              clusters={topicClusters}
              selectedClusterIds={selectedClusterIds}
              supervisorId={supervisorId}
              saving={savingSpecs}
              onSupervisorIdChange={handleSupervisorIdChange}
              onToggleCluster={toggleClusterSelection}
              onSave={() => void saveSpecializations()}
            />
          </div>
          <div
            key={selectedKey ?? "empty"}
            className="brand-supervisor-slide-right brand-supervisor-card-elevated p-5 sm:p-6"
          >
            <DetailPanel
              selectedKey={selectedKey}
              detail={detail}
              form={form}
              categories={topicCategories}
              auditHistory={auditHistory}
              isLoadingDetail={isLoadingDetail}
              isLoadingAudit={isLoadingAudit}
              actionBusy={actionBusy}
              targetKb={targetKb}
              onFormChange={setForm}
              onTargetKbChange={setTargetKb}
              onApproveAndAdd={() => void handleApproveAndAdd()}
              onRejectClick={() => setRejectModalOpen(true)}
              onRegenerateDraft={() => void handleRegenerateDraft()}
            />
          </div>
        </main>
      </div>

      <RejectModal
        open={rejectModalOpen}
        reason={rejectReason}
        busy={actionBusy}
        onReasonChange={setRejectReason}
        onConfirm={() => void handleReject()}
        onCancel={() => {
          setRejectModalOpen(false);
          setRejectReason("");
        }}
      />

      <BatchConfirmModal
        open={batchModal !== null}
        action={batchModal ?? "approve"}
        count={selectedPendingIds.size}
        busy={batchBusy}
        rejectReason={batchRejectReason}
        onRejectReasonChange={setBatchRejectReason}
        onConfirm={() => void runBatchAction(batchModal ?? "approve")}
        onCancel={() => {
          if (!batchBusy) {
            setBatchModal(null);
            setBatchRejectReason("");
          }
        }}
      />

      {toast ? <ToastNotification toast={toast} /> : null}
    </div>
  );
}
