export type SummaryStats = {
  total_submitted: number;
  pending: number;
  approved: number;
  rejected: number;
  added_to_kb: number;
  reviewed: number;
  approval_rate: number;
  rejection_rate: number;
  kb_total_issues: number;
  seller_kb_count: number;
  buyer_kb_count: number;
  avg_review_time_minutes: number | null;
};

export type StatusBreakdownItem = {
  status: string;
  count: number;
};

export type DailyTrendItem = {
  date: string;
  submitted: number;
  approved: number;
  rejected: number;
  pending: number;
};

export type CategoryCountItem = {
  category: string;
  count: number;
};

export type TopicClusterCountItem = {
  cluster_id: number;
  topic_label: string;
  count: number;
};

export type KbGrowthItem = {
  date: string;
  kb_size: number;
  added: number;
};

export type FunnelItem = {
  stage: string;
  count: number;
};

export type TopRepeatedQuery = {
  query: string;
  count: number;
  category: string;
};

export type SupervisorStats = {
  summary: SummaryStats;
  status_breakdown: StatusBreakdownItem[];
  daily_trend: DailyTrendItem[];
  category_counts: CategoryCountItem[];
  topic_cluster_counts?: TopicClusterCountItem[];
  kb_growth: KbGrowthItem[];
  resolution_funnel: FunnelItem[];
  top_repeated_queries: TopRepeatedQuery[];
  insights: string[];
};
