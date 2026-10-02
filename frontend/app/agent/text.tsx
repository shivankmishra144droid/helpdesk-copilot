import type { ReactNode } from "react";

import { DEFAULT_SYNONYM_GROUPS } from "./constants";
import type { SearchResult, UnifiedDraftEntry } from "./types";

export function formatUnifiedEntryText(entry: UnifiedDraftEntry | string | undefined): string {
  if (!entry) return "";
  if (typeof entry === "string") return entry;

  const steps = (entry.resolution_steps ?? [])
    .map((step, index) => `${index + 1}. ${step}`)
    .join("\n");
  const docs = (entry.required_documents ?? [])
    .map((doc) => `- ${doc}`)
    .join("\n");

  return [
    entry.issue_name,
    entry.category ? `Category: ${entry.category}` : null,
    entry.problem_statement ? `Problem: ${entry.problem_statement}` : null,
    entry.policy ? `Policy: ${entry.policy}` : null,
    steps ? `Steps:\n${steps}` : null,
    docs ? `Documents:\n${docs}` : null,
    entry.l1_team || entry.l1_person
      ? `L1: ${entry.l1_team ?? ""} | ${entry.l1_person ?? ""}`
      : null,
  ]
    .filter(Boolean)
    .join("\n\n");
}

export function newId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

export function getQueryWords(query: string): string[] {
  return query
    .trim()
    .toLowerCase()
    .split(/\s+/)
    .filter((w) => w.length >= 2);
}

export function getExpandedQueryTerms(
  queryWords: string[],
  synonymGroups: string[][] = DEFAULT_SYNONYM_GROUPS
): string[] {
  const terms = new Set(queryWords);
  for (const word of queryWords) {
    for (const group of synonymGroups) {
      const inGroup = group.some(
        (term) =>
          term === word || term.includes(word) || word.includes(term)
      );
      if (inGroup) {
        group.forEach((t) => terms.add(t));
      }
    }
  }
  return [...terms];
}

export function textWordMatchesQuery(textWord: string, queryTerms: string[]): boolean {
  const lower = textWord.toLowerCase();
  if (lower.length < 2) return false;

  return queryTerms.some((term) => {
    if (lower === term) return true;
    if (lower.includes(term) || term.includes(lower)) return true;
    if (term.length >= 3 && lower.length >= 3) {
      if (lower.startsWith(term) || term.startsWith(lower)) return true;
    }
    return false;
  });
}

export function highlightMatchingWords(
  text: string,
  query: string,
  synonymGroups: string[][] = DEFAULT_SYNONYM_GROUPS
): ReactNode {
  const queryWords = getQueryWords(query);
  if (!queryWords.length) return text;

  const queryTerms = getExpandedQueryTerms(queryWords, synonymGroups);
  const tokens = text.split(/(\s+|[^\w]+)/);

  return tokens.map((token, index) => {
    if (!/\w/.test(token)) return token;
    if (textWordMatchesQuery(token, queryTerms)) {
      return (
        <span
          key={`${index}-${token}`}
          className="bg-blue-100 text-blue-700 rounded px-1"
        >
          {token}
        </span>
      );
    }
    return token;
  });
}

export function getResultScore(result: SearchResult): number {
  return result.final_score ?? result.score ?? 0;
}

export function getMatchReason(result: SearchResult): string {
  const semantic = result.semantic_score ?? result.score ?? 0;
  const keyword = result.keyword_score ?? 0;
  const strongSemantic = semantic > 0.7;
  const strongKeyword = keyword > 0.5;

  if (strongSemantic && strongKeyword) return "Strong semantic + keyword match";
  if (strongSemantic) return "Strong semantic match";
  if (strongKeyword) return "Keyword match";
  return "Related topic";
}
