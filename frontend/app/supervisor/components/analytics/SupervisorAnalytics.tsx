"use client";

import type { SupervisorStats } from "./statsTypes";
import { StatsCard } from "./StatsCard";
import { QueryTrendChart } from "./QueryTrendChart";
import { StatusPieChart } from "./StatusPieChart";
import { CategoryBarChart } from "./CategoryBarChart";
import { KbGrowthChart } from "./KbGrowthChart";
import { ResolutionFunnel } from "./ResolutionFunnel";
import { InsightsPanel } from "./InsightsPanel";

type Props = {
  stats: SupervisorStats | null;
  loading: boolean;
  error: string | null;
};

export function SupervisorAnalytics({ stats, loading, error }: Props) {
  if (loading) {
    return (
      <section className="brand-supervisor-fade-in brand-supervisor-card p-6">
        <div className="flex items-center gap-3">
          <div className="h-5 w-5 animate-spin rounded-full border-2 border-brand-soft border-t-brand-dark" />
          <p className="text-sm text-[#64748B]">Loading supervisor analytics…</p>
        </div>
      </section>
    );
  }

  if (error) {
    return (
      <section className="brand-supervisor-fade-in rounded-2xl border border-amber-200/80 bg-amber-50/80 p-6 shadow-sm">
        <p className="text-sm text-amber-900">{error}</p>
      </section>
    );
  }

  if (!stats) {
    return null;
  }

  const { summary } = stats;
  const hasData = summary.total_submitted > 0;

  if (!hasData) {
    return (
      <section className="brand-supervisor-scale-in brand-supervisor-card-elevated p-6 sm:p-8">
        <h2 className="text-lg font-bold tracking-tight text-[#0F172A]">
          Supervisor Analytics
        </h2>
        <p className="mt-2 text-sm text-[#64748B]">
          Track how unresolved agent queries move through review and become
          reusable knowledge-base entries.
        </p>
        <p className="mt-4 rounded-2xl border border-dashed border-[rgba(15,23,42,0.1)] bg-[#F8F6F1] p-5 text-sm text-[#64748B]">
          No analytics yet. As agents submit queries and supervisors approve or
          reject them, charts and insights will appear here.
        </p>
      </section>
    );
  }

  return (
    <section className="brand-supervisor-fade-in space-y-6">
      <div className="border-b border-[rgba(15,23,42,0.06)] pb-4">
        <p className="brand-supervisor-label mb-1">Performance Overview</p>
        <h2 className="text-xl font-bold tracking-tight text-[#0F172A]">
          Supervisor Analytics
        </h2>
        <p className="mt-1 text-sm text-[#64748B]">
          Query volume, approval rate, category trends, and KB growth.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <StatsCard
          label="Total Queries"
          value={summary.total_submitted}
          subtitle="Agent-submitted unresolved queries"
          icon="📥"
          accent="navy"
          delay={50}
        />
        <StatsCard
          label="Pending Review"
          value={summary.pending}
          subtitle="Waiting for supervisor action"
          icon="⏳"
          accent="amber"
          delay={100}
        />
        <StatsCard
          label="Resolved"
          value={summary.approved}
          subtitle="Approved by supervisor"
          icon="✅"
          accent="green"
          delay={150}
        />
        <StatsCard
          label="Rejected"
          value={summary.rejected}
          subtitle="Not added to KB"
          icon="✕"
          accent="red"
          delay={200}
        />
        <StatsCard
          label="Added to KB"
          value={summary.added_to_kb}
          subtitle="Reusable approved answers"
          icon="📚"
          accent="gold"
          delay={250}
        />
        <StatsCard
          label="Approval Rate"
          value={`${summary.approval_rate}%`}
          subtitle={
            summary.avg_review_time_minutes != null
              ? `Avg review ${summary.avg_review_time_minutes} min · ${summary.kb_total_issues} KB branches`
              : `${summary.kb_total_issues} KB branches indexed`
          }
          icon="📈"
          accent="slate"
          delay={300}
        />
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <QueryTrendChart data={stats.daily_trend} />
        <StatusPieChart data={stats.status_breakdown} />
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <CategoryBarChart data={stats.category_counts} />
        <KbGrowthChart data={stats.kb_growth} />
      </div>

      {(stats.topic_cluster_counts?.length ?? 0) > 0 ? (
        <CategoryBarChart
          data={(stats.topic_cluster_counts ?? []).map((item) => ({
            category: item.topic_label,
            count: item.count,
          }))}
          title="Pending topic clusters"
          subtitle="Auto-grouped from query text in the review queue"
        />
      ) : null}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <ResolutionFunnel data={stats.resolution_funnel} />
        <InsightsPanel
          insights={stats.insights}
          topQueries={stats.top_repeated_queries}
        />
      </div>
    </section>
  );
}
