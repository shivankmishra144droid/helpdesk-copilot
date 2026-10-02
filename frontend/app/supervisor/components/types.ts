export { API_BASE } from "../../lib/api";
export const POLL_MS = 10_000;
export const SUPERVISOR_ID_KEY = "copilot_supervisor_id";

export type PendingStatus = "drafted" | "approved" | "rejected";

export type TopicCategory = {
  id: string;
  name: string;
  branch_count: number;
};

export type TopicCluster = {
  cluster_id: number;
  topic_label: string;
  count: number;
  sample_queries: string[];
};

export type SupervisorSpecializations = {
  supervisor_id: string;
  cluster_ids: number[];
  updated_at?: string | null;
};

export type PendingIssue = {
  id: number;
  issue_id: number;
  pending_id?: string | null;
  query: string;
  issue_name: string;
  caller_type: string;
  status: PendingStatus;
  created_at: string;
  source_document?: string;
  category_id?: string;
  topic_cluster_id?: number | null;
  topic_label?: string | null;
};

export type IssueForm = {
  issue_name: string;
  category: string;
  problem_statement: string;
  policy: string;
  resolution_steps: string[];
  required_documents: string[];
  l1_team: string;
  l1_person: string;
  trigger_keywords: string[];
};

export type SimilarIssue = {
  source: "database" | "kb" | "lms_faq";
  issue_name: string;
  category_id: string;
  category: string;
  branch_id?: string;
  problem_statement?: string;
  resolution_steps?: string[];
  agent_script_preview?: string;
};

export type IssueDetail = {
  issue_id: number;
  pending_id?: string | null;
  query: string;
  caller_type: string;
  source_document?: string;
  status: PendingStatus;
  created_at: string;
  updated_at: string;
  submitted_at: string;
  draft: IssueForm & { topic_category?: string };
  form: IssueForm & { topic_category?: string };
  similar_issues: SimilarIssue[];
  draft_error?: string | null;
  draft_source?: string | null;
  template_issue_name?: string | null;
  examples_used?: string[];
  editable: boolean;
  reject_reason?: string | null;
  llm_redraft_recommended?: boolean;
  llm_available?: boolean;
};

export type AuditEntry = {
  id: number;
  action: string;
  timestamp: string;
  notes?: string | null;
  supervisor_name?: string | null;
};

export type Toast = { type: "success" | "error"; message: string };

export const EMPTY_FORM: IssueForm = {
  issue_name: "",
  category: "",
  problem_statement: "",
  policy: "",
  resolution_steps: [],
  required_documents: [],
  l1_team: "",
  l1_person: "",
  trigger_keywords: [],
};

export function pendingKey(item: Pick<PendingIssue, "pending_id" | "issue_id">): string {
  return item.pending_id ?? `issue-${item.issue_id}`;
}
