import type { IssueForm } from "./types";

export function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export function formatApiError(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== "object") return fallback;
  const detail = (payload as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => String(item)).join(", ");
  }
  return fallback;
}

export function pipeSplit(value: string): string[] {
  return value
    .split(/[|\n]/)
    .map((part) => part.trim())
    .filter(Boolean);
}

/** Keep multi-line paragraphs intact; split only on explicit `|` separators. */
export function resolutionStepsSplit(value: string): string[] {
  const trimmed = value.trim();
  if (!trimmed) return [];
  if (!trimmed.includes("|")) return [trimmed];
  return trimmed
    .split("|")
    .map((part) => part.trim())
    .filter(Boolean);
}

export function resolutionStepsToText(value: string[] | undefined): string {
  if (!value?.length) return "";
  if (value.length === 1) return value[0];
  return value.join(" | ");
}

export function listToPipe(value: string[] | undefined): string {
  return (value ?? []).join(" | ");
}

export function formToEntry(form: IssueForm): Record<string, unknown> {
  return {
    issue_name: form.issue_name,
    category: form.category,
    topic_category: form.category,
    problem_statement: form.problem_statement,
    policy: form.policy,
    resolution_steps: form.resolution_steps,
    required_documents: form.required_documents,
    l1_team: form.l1_team,
    l1_person: form.l1_person,
    trigger_keywords: form.trigger_keywords,
  };
}

export function entryToForm(
  entry: Partial<IssueForm & { topic_category?: string }> | undefined,
  query = ""
): IssueForm {
  const category = entry?.category ?? entry?.topic_category ?? "";
  return {
    issue_name: entry?.issue_name ?? query.slice(0, 80),
    category,
    problem_statement: entry?.problem_statement ?? query,
    policy: entry?.policy ?? "",
    resolution_steps: [...(entry?.resolution_steps ?? [])],
    required_documents: [...(entry?.required_documents ?? [])],
    l1_team: entry?.l1_team ?? "",
    l1_person: entry?.l1_person ?? "",
    trigger_keywords: [...(entry?.trigger_keywords ?? [])],
  };
}

export function auditLabel(action: string): string {
  const labels: Record<string, string> = {
    queued_by_agent: "Submitted by agent",
    parsed_from_manual: "Parsed from manual",
    draft_generated: "LLM auto-draft generated",
    draft_failed: "Draft fallback — template used",
    llm_drafted: "LLM auto-draft",
    llm_unavailable: "AI provider offline — template used",
    approved_send_only: "Approved → sent to agent",
    approved_and_added: "Approved & added to KB",
    rejected: "Rejected",
  };
  return labels[action] ?? action.replaceAll("_", " ");
}

export function truncate(text: string, max = 80): string {
  const trimmed = text.trim();
  if (trimmed.length <= max) return trimmed;
  return `${trimmed.slice(0, max)}…`;
}
