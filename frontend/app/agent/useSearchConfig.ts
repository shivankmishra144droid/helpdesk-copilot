"use client";

import { useEffect, useState } from "react";

import { apiFetch } from "../lib/api";
import {
  DEFAULT_SYNONYM_GROUPS,
  MIN_MATCH_THRESHOLD,
  WEAK_MATCH_THRESHOLD,
} from "./constants";
import type { CallerType } from "./types";

export type SearchConfig = {
  synonymGroups: string[][];
  minMatchScore: number;
  weakMatchScore: number;
};

const FALLBACK: SearchConfig = {
  synonymGroups: DEFAULT_SYNONYM_GROUPS,
  minMatchScore: MIN_MATCH_THRESHOLD,
  weakMatchScore: WEAK_MATCH_THRESHOLD,
};

/** Synonyms + score thresholds from GET /search/config; built-in defaults until it loads. */
export function useSearchConfig(callerType: CallerType | null): SearchConfig {
  const [config, setConfig] = useState<SearchConfig>(FALLBACK);

  useEffect(() => {
    if (!callerType) return;
    let cancelled = false;
    apiFetch(`/search/config?caller_type=${callerType}`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (cancelled || !data) return;
        setConfig({
          synonymGroups: Array.isArray(data.synonym_groups)
            ? data.synonym_groups
            : FALLBACK.synonymGroups,
          minMatchScore:
            typeof data.min_match_score === "number"
              ? data.min_match_score
              : FALLBACK.minMatchScore,
          weakMatchScore:
            typeof data.weak_match_score === "number"
              ? data.weak_match_score
              : FALLBACK.weakMatchScore,
        });
      })
      .catch(() => {
        /* keep defaults */
      });
    return () => {
      cancelled = true;
    };
  }, [callerType]);

  return config;
}
