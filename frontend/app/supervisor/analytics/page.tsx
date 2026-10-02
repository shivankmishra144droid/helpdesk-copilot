"use client";

import { apiFetch } from "../../lib/api";
import { useCallback, useEffect, useState } from "react";
import { API_BASE, POLL_MS } from "../components/types";
import { SupervisorHeader } from "../components/SupervisorHeader";
import { SupervisorAnalytics } from "../components/analytics/SupervisorAnalytics";
import type { SupervisorStats } from "../components/analytics/statsTypes";

export default function SupervisorAnalyticsPage() {
  const [stats, setStats] = useState<SupervisorStats | null>(null);
  const [isLoadingStats, setIsLoadingStats] = useState(true);
  const [statsError, setStatsError] = useState<string | null>(null);
  const [pendingCount, setPendingCount] = useState(0);

  const fetchStats = useCallback(async (silent = false) => {
    if (!silent) setIsLoadingStats(true);
    try {
      const res = await apiFetch(`${API_BASE}/supervisor/stats`);
      if (!res.ok) throw new Error("stats");
      const data: SupervisorStats = await res.json();
      setStats(data);
      setStatsError(null);
    } catch {
      setStatsError("Unable to load analytics right now.");
    } finally {
      if (!silent) setIsLoadingStats(false);
    }
  }, []);

  const fetchPendingCount = useCallback(async () => {
    try {
      const res = await apiFetch(`${API_BASE}/supervisor/issues/pending`);
      if (!res.ok) return;
      const data = await res.json();
      setPendingCount((data.issues ?? []).length);
    } catch {
      /* ignore — badge is optional */
    }
  }, []);

  useEffect(() => {
    void fetchStats();
    void fetchPendingCount();
    const intervalId = window.setInterval(() => {
      void fetchStats(true);
      void fetchPendingCount();
    }, POLL_MS);
    return () => window.clearInterval(intervalId);
  }, [fetchStats, fetchPendingCount]);

  return (
    <div className="brand-supervisor-bg flex min-h-screen flex-col text-[#0F172A]">
      <SupervisorHeader
        pendingCount={pendingCount}
        subtitle="Helpdesk Copilot · Performance & trends"
      />

      <main className="mx-auto w-full max-w-[1600px] flex-1 p-4 sm:p-6">
        <SupervisorAnalytics
          stats={stats}
          loading={isLoadingStats}
          error={statsError}
        />
      </main>
    </div>
  );
}
