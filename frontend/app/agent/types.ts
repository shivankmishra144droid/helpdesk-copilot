// Shared types for the agent console (app/page.tsx).

export interface Branch {
  branch_id: string;
  branch_name: string;
  category_id?: string;
  category_name?: string;
  path?: string[];
  agent_script: string;
  steps: string[];
  documents: string[];
  escalation: string;
  escalation_person: string;
}

export interface SearchResult {
  branch_id: string;
  branch_name: string;
  score: number;
  semantic_score?: number;
  keyword_score?: number;
  final_score?: number;
  path: string[];
  agent_script_preview: string;
  keywords_preview: string[];
}

export type CallerType = "buyer" | "seller";

export type AppView = "caller_gate" | "chat" | "stepper";

export type ChatMessage =
  | { id: string; role: "user"; content: string }
  | { id: string; role: "assistant"; kind: "welcome" }
  | { id: string; role: "assistant"; kind: "loading"; query: string }
  | { id: string; role: "assistant"; kind: "results"; query: string; results: SearchResult[] }
  | { id: string; role: "assistant"; kind: "error"; query: string }
  | { id: string; role: "assistant"; kind: "no_results"; query: string }
  | {
      id: string;
      role: "assistant";
      kind: "outlier";
      query: string;
      message: string;
      suggestedQueries: string[];
    }
  | {
      id: string;
      role: "assistant";
      kind: "supervisor_submitted";
      pendingId: string;
      query: string;
    }
  | {
      id: string;
      role: "assistant";
      kind: "supervisor_approved";
      pendingId: string;
      query: string;
      branchId?: string | null;
      branchName: string;
      resolutionText: string;
      addedToKb: boolean;
      resolutionSteps?: string[];
    }
  | {
      id: string;
      role: "assistant";
      kind: "supervisor_rejected";
      pendingId: string;
      query: string;
      reason?: string | null;
    }
  | { id: string; role: "assistant"; kind: "browse_categories" }
  | {
      id: string;
      role: "assistant";
      kind: "category_topics";
      categoryId: string;
      categoryName: string;
      branches: BranchListItem[];
    }
  | { id: string; role: "assistant"; kind: "category_empty"; categoryName: string };

export type PendingSupervisorItem = {
  pendingId: string;
  query: string;
};

export type SupervisorPendingSummary = {
  pending_id: string;
  query: string;
  status: string;
  created_at: string;
};

export type UnifiedDraftEntry = {
  issue_name?: string;
  category?: string;
  problem_statement?: string;
  policy?: string;
  resolution_steps?: string[];
  required_documents?: string[];
  l1_team?: string;
  l1_person?: string;
};

export type SupervisorPendingDetail = SupervisorPendingSummary & {
  draft?: UnifiedDraftEntry | string;
  final_entry?: UnifiedDraftEntry | null;
  examples_used?: string[];
  branch_id?: string | null;
  added_to_kb?: boolean;
  reject_reason?: string | null;
};

export type BranchListItem = {
  branch_id: string;
  branch_name: string;
  topic_category?: string;
};

export type TopicCategory = {
  id: string;
  name: string;
  branch_count: number;
};
