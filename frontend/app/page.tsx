"use client";

import {
  useState,
  useCallback,
  useEffect,
  useRef,
} from "react";

import { API_BASE, apiFetch } from "./lib/api";
import {
  MAX_CHAT_RESULTS,
  SELLER_CALLER_LABEL,
  SUPERVISOR_POLL_MS,
} from "./agent/constants";
import { backendAlert, readApiError, showSubmitError } from "./agent/errors";
import {
  ArrowRightIcon,
  BotIcon,
  Building2Icon,
  CheckCircle2Icon,
  ShieldCheckIcon,
  ShoppingCartIcon,
} from "./agent/icons";
import {
  formatUnifiedEntryText,
  getMatchReason,
  getResultScore,
  highlightMatchingWords,
  newId,
} from "./agent/text";
import type {
  AppView,
  Branch,
  BranchListItem,
  CallerType,
  ChatMessage,
  PendingSupervisorItem,
  SearchResult,
  SupervisorPendingDetail,
  SupervisorPendingSummary,
  TopicCategory,
} from "./agent/types";
import {
  AgentAvatar,
  CategoryGrid,
  NewCallButton,
  PathBreadcrumb,
  TypingIndicator,
} from "./agent/ui";
import { useSearchConfig } from "./agent/useSearchConfig";
import { useStepper } from "./agent/useStepper";

export default function Home() {
  const [view, setView] = useState<AppView>("caller_gate");
  const [callerType, setCallerType] = useState<CallerType | null>(null);
  const [callerId, setCallerId] = useState("");
  const [gateSelectedType, setGateSelectedType] = useState<CallerType | null>(
    null
  );
  const [inputValue, setInputValue] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [isLoadingBranch, setIsLoadingBranch] = useState(false);
  const [sessionResolved, setSessionResolved] = useState(false);
  const [branchCount, setBranchCount] = useState(0);
  const [topicCategories, setTopicCategories] = useState<TopicCategory[]>([]);
  const [scopedCategoryId, setScopedCategoryId] = useState<string | null>(null);
  const stepper = useStepper({
    callerType,
    onResolved: () => setSessionResolved(true),
  });
  const {
    activeBranch,
    activePath,
    currentStepIndex,
    completedSteps,
    collectedDocs,
    stepperMode,
    stepPulse,
    blockedInfo,
    isVerifying,
    markDone: handleStepDone,
    markBlocked: handleStepBlocked,
    toggleDoc,
  } = stepper;
  const [copied, setCopied] = useState(false);
  const searchConfig = useSearchConfig(callerType);
  const [supervisorDrawerOpen, setSupervisorDrawerOpen] = useState(false);
  const [lastUserQuery, setLastUserQuery] = useState("");
  const [supervisorDraft, setSupervisorDraft] = useState("");
  const [supervisorDrawerStep, setSupervisorDrawerStep] = useState<1 | 2>(1);
  const [supervisorRelatedMatches, setSupervisorRelatedMatches] = useState<
    SearchResult[]
  >([]);
  const [isLoadingSupervisorMatches, setIsLoadingSupervisorMatches] =
    useState(false);
  const [isSubmittingSupervisor, setIsSubmittingSupervisor] = useState(false);
  const [isCheckingSupervisor, setIsCheckingSupervisor] = useState(false);
  const [trackedPending, setTrackedPending] =
    useState<PendingSupervisorItem | null>(null);
  const [outlierCheck, setOutlierCheck] = useState<{
    is_outlier: boolean;
    message: string;
    suggested_queries: string[];
    anomaly_score: number;
  } | null>(null);
  const [searchCorrection, setSearchCorrection] = useState<{
    original: string;
    corrected: string;
    confidence: number;
  } | null>(null);
  const [predictedCategory, setPredictedCategory] = useState<{
    id: string;
    name: string;
    confidence: number;
  } | null>(null);

  const inputRef = useRef<HTMLTextAreaElement>(null);

  const refreshBranches = useCallback((type: CallerType = "seller") => {
    apiFetch(`${API_BASE}/branches?caller_type=${type}`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data?.branches && Array.isArray(data.branches)) {
          setBranchCount(data.total ?? data.branches.length);
        }
      })
      .catch(() => {
        /* keep cached list */
      });
  }, []);

  const refreshTopicCategories = useCallback((type: CallerType = "seller") => {
    apiFetch(`${API_BASE}/topic-categories?caller_type=${type}`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data?.categories && Array.isArray(data.categories)) {
          setTopicCategories(data.categories);
        }
      })
      .catch(() => {
        /* keep cached list */
      });
  }, []);

  useEffect(() => {
    if (view !== "chat" || sessionResolved) {
      setOutlierCheck(null);
      return;
    }

    const trimmed = inputValue.trim();
    if (trimmed.length < 3) {
      setOutlierCheck(null);
      return;
    }

    const timer = window.setTimeout(() => {
      const params = new URLSearchParams({
        query: trimmed,
        caller_type: callerType ?? "seller",
      });
      apiFetch(`${API_BASE}/search/check-query?${params.toString()}`)
        .then((res) => (res.ok ? res.json() : null))
        .then((data) => {
          if (!data?.is_outlier) {
            setOutlierCheck(null);
            return;
          }
          setOutlierCheck({
            is_outlier: true,
            message:
              data.message ??
              "This query may be off-topic for marketplace support topics.",
            suggested_queries: data.suggested_queries ?? [],
            anomaly_score: data.anomaly_score ?? 0,
          });
        })
        .catch(() => setOutlierCheck(null));
    }, 400);

    return () => window.clearTimeout(timer);
  }, [inputValue, callerType, view, sessionResolved]);

  useEffect(() => {
    if (callerType) {
      refreshBranches(callerType);
      refreshTopicCategories(callerType);
    }
  }, [callerType, refreshBranches, refreshTopicCategories]);

  const initStepper = (branch: Branch, path: string[]) => {
    stepper.start(branch, path);
    setView("stepper");
  };

  const handleSelectResult = useCallback(
    async (result: SearchResult) => {
      if (isLoadingBranch || sessionResolved) return;

      setIsLoadingBranch(true);
      try {
        const res = await apiFetch(`${API_BASE}/select-branch`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            branch_id: result.branch_id,
            caller_type: callerType ?? "seller",
          }),
        });
        if (res.status === 404) {
          alert("This issue is no longer in the knowledge base. Please try another result.");
          return;
        }
        if (!res.ok) throw new Error("Select branch failed");

        const data = await res.json();
        if (data.status === "diagnosed" && data.branch) {
          initStepper(data.branch, data.path || data.branch.path || result.path);
        } else {
          alert("Could not load issue details. Please try another result.");
        }
      } catch {
        backendAlert();
      } finally {
        setIsLoadingBranch(false);
      }
    },
    [isLoadingBranch, sessionResolved, callerType]
  );

  const handleSelectBranchById = useCallback(
    async (branchId: string) => {
      if (isLoadingBranch || sessionResolved) return;

      setIsLoadingBranch(true);
      try {
        const res = await apiFetch(`${API_BASE}/select-branch`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            branch_id: branchId,
            caller_type: callerType ?? "seller",
          }),
        });
        if (res.status === 404) {
          alert("This issue is no longer in the knowledge base. Please try another result.");
          return;
        }
        if (!res.ok) throw new Error("Select branch failed");

        const data = await res.json();
        if (data.status === "diagnosed" && data.branch) {
          initStepper(data.branch, data.path || data.branch.path || []);
        } else {
          alert("Could not load issue details. Please try another branch.");
        }
      } catch {
        backendAlert();
      } finally {
        setIsLoadingBranch(false);
      }
    },
    [isLoadingBranch, sessionResolved, callerType]
  );

  const sendMessage = useCallback(
    async (text: string) => {
      const query = text.trim();
      if (!query || isSearching || sessionResolved || view !== "chat") return;

      const userMsg: ChatMessage = { id: newId(), role: "user", content: query };
      const loadingId = newId();

      setInputValue("");
      setIsSearching(true);
      setLastUserQuery(query);
      setMessages((prev) => [
        ...prev,
        userMsg,
        { id: loadingId, role: "assistant", kind: "loading", query },
      ]);

      try {
        const res = await apiFetch(`${API_BASE}/search`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            query,
            caller_type: callerType ?? "seller",
            topic_category: scopedCategoryId,
          }),
        });
        if (!res.ok) throw new Error("Search failed");

        const data = await res.json();

        if (data.correction_applied && data.corrected_query) {
          setSearchCorrection({
            original: data.original_query ?? query,
            corrected: data.corrected_query,
            confidence: data.correction_confidence ?? 1,
          });
        } else {
          setSearchCorrection(null);
        }

        if (
          data.predicted_category &&
          !scopedCategoryId &&
          (data.intent_confidence ?? 0) >= 0.55
        ) {
          setPredictedCategory({
            id: data.predicted_category,
            name:
              data.predicted_category_name ??
              data.predicted_category.replace(/_/g, " "),
            confidence: data.intent_confidence ?? 0,
          });
        } else if (!scopedCategoryId) {
          setPredictedCategory(null);
        }

        if (data.status === "outlier") {
          setMessages((prev) => {
            const withoutLoading = prev.filter((m) => m.id !== loadingId);
            return [
              ...withoutLoading,
              {
                id: newId(),
                role: "assistant",
                kind: "outlier",
                query,
                message:
                  data.message ??
                  "This query doesn't look related to marketplace support topics.",
                suggestedQueries: data.suggested_queries ?? [],
              },
            ];
          });
          return;
        }

        const results: SearchResult[] = (data.results || []).slice(
          0,
          MAX_CHAT_RESULTS
        );

        setMessages((prev) => {
          const withoutLoading = prev.filter((m) => m.id !== loadingId);
          const matched = results.filter(
            (r) => getResultScore(r) >= searchConfig.minMatchScore
          );
          if (matched.length === 0) {
            return [
              ...withoutLoading,
              { id: newId(), role: "assistant", kind: "no_results", query },
            ];
          }
          return [
            ...withoutLoading,
            {
              id: newId(),
              role: "assistant",
              kind: "results",
              query,
              results: matched.slice(0, MAX_CHAT_RESULTS),
            },
          ];
        });
      } catch {
        setMessages((prev) => {
          const withoutLoading = prev.filter((m) => m.id !== loadingId);
          return [
            ...withoutLoading,
            { id: newId(), role: "assistant", kind: "error", query },
          ];
        });
      } finally {
        setIsSearching(false);
        inputRef.current?.focus();
      }
    },
    [isSearching, sessionResolved, view, callerType, scopedCategoryId, searchConfig]
  );

  const handleSupervisorApproved = useCallback(
    async (detail: SupervisorPendingDetail) => {
      const entry =
        detail.final_entry ??
        (typeof detail.draft === "object" ? detail.draft : undefined);

      let branchName = entry?.issue_name ?? "Supervisor resolution";

      if (detail.branch_id) {
        try {
          const res = await apiFetch(`${API_BASE}/select-branch`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              branch_id: detail.branch_id,
              caller_type: callerType ?? "seller",
            }),
          });
          if (res.ok) {
            const data = await res.json();
            if (data.branch?.branch_name) {
              branchName = data.branch.branch_name;
            }
          }
        } catch {
          /* use parsed title */
        }
      }

      const resolutionText = formatUnifiedEntryText(entry) || "";
      const resolutionSteps = entry?.resolution_steps ?? [];

      setMessages((prev) => {
        if (
          prev.some(
            (message) =>
              message.role === "assistant" &&
              message.kind === "supervisor_approved" &&
              message.pendingId === detail.pending_id
          )
        ) {
          return prev;
        }

        return [
          ...prev,
          {
            id: newId(),
            role: "assistant",
            kind: "supervisor_approved",
            pendingId: detail.pending_id,
            query: detail.query,
            branchId: detail.branch_id ?? null,
            branchName,
            resolutionText,
            addedToKb: Boolean(detail.added_to_kb),
            resolutionSteps,
          },
        ];
      });

      if (detail.added_to_kb && callerType) {
        refreshBranches(callerType);
        refreshTopicCategories(callerType);
      }
      setTrackedPending(null);
    },
    [callerType, refreshBranches, refreshTopicCategories]
  );

  const checkSupervisorStatus = useCallback(
    async (pendingId: string, options?: { silent?: boolean }) => {
      if (!options?.silent) {
        setIsCheckingSupervisor(true);
      }

      try {
        const res = await apiFetch(`${API_BASE}/supervisor/pending/${pendingId}`);
        if (!res.ok) throw new Error("Status check failed");

        const detail: SupervisorPendingDetail = await res.json();
        if (detail.status === "approved") {
          await handleSupervisorApproved(detail);
          return detail;
        }

        if (detail.status === "rejected") {
          setMessages((prev) => {
            if (
              prev.some(
                (message) =>
                  message.role === "assistant" &&
                  message.kind === "supervisor_rejected" &&
                  message.pendingId === detail.pending_id
              )
            ) {
              return prev;
            }
            return [
              ...prev,
              {
                id: newId(),
                role: "assistant",
                kind: "supervisor_rejected",
                pendingId: detail.pending_id,
                query: detail.query,
                reason: detail.reject_reason,
              },
            ];
          });
          if (!options?.silent) {
            alert(
              detail.reject_reason
                ? `Supervisor rejected this query: ${detail.reject_reason}`
                : "Supervisor rejected this query."
            );
          }
          setTrackedPending(null);
          return detail;
        }

        return detail;
      } catch {
        if (!options?.silent) {
          backendAlert();
        }
        return null;
      } finally {
        if (!options?.silent) {
          setIsCheckingSupervisor(false);
        }
      }
    },
    [handleSupervisorApproved]
  );

  const checkSupervisorStatusByQuery = useCallback(
    async (query: string) => {
      setIsCheckingSupervisor(true);
      try {
        const res = await apiFetch(`${API_BASE}/supervisor/pending`);
        if (!res.ok) throw new Error("Status check failed");

        const items: SupervisorPendingSummary[] = await res.json();
        const normalized = query.trim().toLowerCase();
        const match =
          items.find(
            (item) =>
              item.query.trim().toLowerCase() === normalized &&
              item.status === "drafted"
          ) ||
          items.find(
            (item) => item.query.trim().toLowerCase() === normalized
          );

        if (!match) {
          alert("No supervisor submission found for this query yet.");
          return null;
        }

        return checkSupervisorStatus(match.pending_id);
      } catch {
        backendAlert();
        return null;
      } finally {
        setIsCheckingSupervisor(false);
      }
    },
    [checkSupervisorStatus]
  );

  const closeSupervisorDrawer = useCallback(() => {
    setSupervisorDrawerOpen(false);
    setSupervisorDrawerStep(1);
    setSupervisorRelatedMatches([]);
  }, []);

  const openSupervisorPanel = useCallback((query?: string) => {
    const prefill = (query ?? lastUserQuery ?? inputValue).trim();
    setSupervisorDraft(prefill);
    setSupervisorDrawerStep(1);
    setSupervisorRelatedMatches([]);
    setSupervisorDrawerOpen(true);
  }, [lastUserQuery, inputValue]);

  const continueToRelatedMatches = useCallback(async () => {
    const query = supervisorDraft.trim();
    if (!query || isLoadingSupervisorMatches || sessionResolved) return;

    setIsLoadingSupervisorMatches(true);
    try {
      const params = new URLSearchParams({
        query,
        caller_type: callerType ?? "seller",
      });
      const res = await apiFetch(`${API_BASE}/supervisor/check-kb?${params}`);
      if (!res.ok) {
        throw new Error(await readApiError(res, "KB check failed"));
      }

      const data = await res.json();
      const matches: SearchResult[] = (data.possible_matches || data.kb_matches || []).slice(
        0,
        3
      );
      setSupervisorRelatedMatches(matches);
      setSupervisorDrawerStep(2);
    } catch (error) {
      showSubmitError(error, "Could not check related KB matches.");
    } finally {
      setIsLoadingSupervisorMatches(false);
    }
  }, [supervisorDraft, isLoadingSupervisorMatches, sessionResolved, callerType]);

  const submitSupervisorQuery = useCallback(async () => {
    const query = supervisorDraft.trim();
    if (!query || isSubmittingSupervisor || sessionResolved) return;

    setIsSubmittingSupervisor(true);
    try {
      const res = await apiFetch(`${API_BASE}/supervisor/queue`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query,
          caller_type: callerType ?? "seller",
          possible_matches:
            supervisorRelatedMatches.length > 0 ? supervisorRelatedMatches : undefined,
        }),
      });
      if (!res.ok) {
        throw new Error(await readApiError(res, "Supervisor queue failed"));
      }

      const data = await res.json();

      setSupervisorDraft("");
      setSupervisorDrawerStep(1);
      setSupervisorRelatedMatches([]);
      setMessages((prev) => [
        ...prev,
        {
          id: newId(),
          role: "assistant",
          kind: "supervisor_submitted",
          pendingId: data.pending_id,
          query,
        },
      ]);
      setTrackedPending({ pendingId: data.pending_id, query });
      setSupervisorDrawerOpen(false);
    } catch (error) {
      showSubmitError(error, "Could not submit to supervisor.");
    } finally {
      setIsSubmittingSupervisor(false);
    }
  }, [supervisorDraft, isSubmittingSupervisor, sessionResolved, callerType]);

  const handleSelectResultFromDrawer = useCallback(
    async (result: SearchResult) => {
      await handleSelectResult(result);
      closeSupervisorDrawer();
    },
    [handleSelectResult, closeSupervisorDrawer]
  );

  useEffect(() => {
    if (!trackedPending || view !== "chat") return;

    let cancelled = false;

    const poll = async () => {
      if (cancelled) return;
      await checkSupervisorStatus(trackedPending.pendingId, { silent: true });
    };

    const intervalId = window.setInterval(() => {
      void poll();
    }, SUPERVISOR_POLL_MS);

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [trackedPending, view, checkSupervisorStatus]);

  const showBrowseCategories = useCallback(() => {
    setMessages((prev) => [
      ...prev,
      { id: newId(), role: "assistant", kind: "browse_categories" },
    ]);
  }, []);

  const handleCategorySelect = useCallback(
    async (category: TopicCategory) => {
      if (!callerType || sessionResolved || isLoadingBranch) return;

      setScopedCategoryId(category.id);
      setMessages((prev) => [
        ...prev,
        { id: newId(), role: "user", content: category.name },
      ]);

      if (category.branch_count === 0) {
        setMessages((prev) => [
          ...prev,
          {
            id: newId(),
            role: "assistant",
            kind: "category_empty",
            categoryName: category.name,
          },
        ]);
        return;
      }

      try {
        const res = await apiFetch(
          `${API_BASE}/branches?caller_type=${callerType}&topic_category=${encodeURIComponent(category.id)}`
        );
        if (!res.ok) throw new Error("Failed to load category");

        const data = await res.json();
        const branches: BranchListItem[] = data.branches ?? [];

        setMessages((prev) => [
          ...prev,
          {
            id: newId(),
            role: "assistant",
            kind: "category_topics",
            categoryId: category.id,
            categoryName: category.name,
            branches,
          },
        ]);
      } catch {
        backendAlert();
      }
    },
    [callerType, sessionResolved, isLoadingBranch]
  );

  const handleCallerTypeClick = (option: string) => {
    if (option === SELLER_CALLER_LABEL) {
      setCallerType("seller");
      setScopedCategoryId(null);
      refreshBranches("seller");
      refreshTopicCategories("seller");
      setMessages([{ id: newId(), role: "assistant", kind: "welcome" }]);
      setView("chat");
      return;
    }

    if (option === "Buyer") {
      setCallerType("buyer");
      setScopedCategoryId(null);
      refreshBranches("buyer");
      refreshTopicCategories("buyer");
      setMessages([{ id: newId(), role: "assistant", kind: "welcome" }]);
      setView("chat");
    }
  };


  const handleCopySummary = async () => {
    if (!activeBranch) return;

    const stepsText = activeBranch.steps
      .map((s, i) => `${completedSteps[i] ? "✅" : "❌"} ${i + 1}. ${s}`)
      .join("\n");
    const docsText = activeBranch.documents
      .map((d) => `${collectedDocs.has(d) ? "✅" : "□"} ${d}`)
      .join("\n");

    const text = [
      activeBranch.branch_name,
      "",
      activeBranch.agent_script,
      "",
      "STEPS:",
      stepsText,
      "",
      "DOCUMENTS:",
      docsText,
      "",
      `ESCALATION: ${activeBranch.escalation} (${activeBranch.escalation_person})`,
    ]
      .filter(Boolean)
      .join("\n");

    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleContinueToCopilot = () => {
    if (!callerId.trim() || !gateSelectedType) return;
    handleCallerTypeClick(
      gateSelectedType === "buyer" ? "Buyer" : SELLER_CALLER_LABEL
    );
  };

  const handleNewCall = () => {
    setView("caller_gate");
    setCallerType(null);
    setCallerId("");
    setGateSelectedType(null);
    setInputValue("");
    setMessages([]);
    setIsSearching(false);
    setIsLoadingBranch(false);
    setSessionResolved(false);
    stepper.reset();
    setCopied(false);
    setScopedCategoryId(null);
    setTopicCategories([]);
    setSupervisorDrawerOpen(false);
    setLastUserQuery("");
    setSupervisorDraft("");
    setIsSubmittingSupervisor(false);
    setIsCheckingSupervisor(false);
    setTrackedPending(null);
  };

  const handleBackToChat = () => {
    setView("chat");
    stepper.clearBranch();
    inputRef.current?.focus();
  };

  const handleInputKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void sendMessage(inputValue);
    }
  };

  const renderDocumentsChecklist = (
    branch: Branch,
    heading: string,
    hint?: string
  ) => {
    if (!branch.documents.length) return null;

    return (
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-3">
        <p className="text-blue-700 text-xs font-bold uppercase mb-1">
          📎 {heading}
        </p>
        {hint && <p className="text-xs text-gray-500 mb-2">{hint}</p>}
        <ul className="space-y-1.5 max-h-48 overflow-y-auto">
          {branch.documents.map((doc) => {
            const checked = collectedDocs.has(doc);
            return (
              <li key={doc}>
                <button
                  type="button"
                  onClick={() => toggleDoc(doc)}
                  className="flex items-start gap-2 w-full text-left"
                >
                  <span className={checked ? "text-green-600" : "text-blue-600"}>
                    {checked ? "✅" : "□"}
                  </span>
                  <span
                    className={`text-sm ${
                      checked ? "text-green-600 line-through" : "text-gray-700"
                    }`}
                  >
                    {doc}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
        <p className="text-xs text-gray-500 mt-2">
          Collected {collectedDocs.size} of {branch.documents.length}
        </p>
      </div>
    );
  };

  const renderResultCard = (
    result: SearchResult,
    query: string,
    index: number,
    onSelect?: (result: SearchResult) => void
  ) => {
    const select = onSelect ?? handleSelectResult;
    return (
      <button
        key={result.branch_id}
        type="button"
        onClick={() => void select(result)}
        disabled={isLoadingBranch || sessionResolved}
        className="group w-full rounded-2xl border border-[#E5EAF2] bg-white p-4 text-left shadow-sm transition-all duration-200 hover:-translate-y-0.5 hover:border-[#2563EB]/40 hover:shadow-lg hover:shadow-blue-500/10 disabled:cursor-not-allowed disabled:opacity-50"
      >
        <div className="flex items-start gap-3">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-[#EFF6FF] text-xs font-bold text-[#2563EB] transition group-hover:bg-[#2563EB] group-hover:text-white">
            {index + 1}
          </span>
          <div className="flex-1 min-w-0">
            <div className="mb-1">
              <p className="text-sm font-semibold leading-snug text-[#0F172A]">
                {highlightMatchingWords(result.branch_name, query, searchConfig.synonymGroups)}
              </p>
            </div>
            <p className="mb-1.5 line-clamp-1 text-xs text-[#64748B]">
              {result.agent_script_preview}
            </p>
            <p className="text-xs text-[#94A3B8]">
              {getMatchReason(result)} · Click to view steps
            </p>
          </div>
        </div>
      </button>
    );
  };

  const renderSupervisorDrawer = () => (
    <>
      {supervisorDrawerOpen ? (
        <button
          type="button"
          aria-label="Close new query panel"
          className="fixed inset-0 z-30 bg-black/25 lg:bg-black/10"
          onClick={closeSupervisorDrawer}
        />
      ) : null}

      <button
        type="button"
        onClick={() => openSupervisorPanel()}
        disabled={sessionResolved || isSubmittingSupervisor}
        aria-label="Submit a new query"
        className={`fixed right-0 top-1/2 z-30 -translate-y-1/2 rounded-l-lg border border-r-0 border-amber-300 bg-amber-500 hover:bg-amber-400 text-white shadow-lg transition-all duration-300 disabled:opacity-50 ${
          supervisorDrawerOpen
            ? "pointer-events-none translate-x-full opacity-0"
            : "translate-x-0 opacity-100"
        }`}
      >
        <span className="flex items-center gap-1.5 px-2.5 py-3 text-xs font-semibold [writing-mode:vertical-rl] rotate-180">
          New query
        </span>
      </button>

      <aside
        className={`fixed top-16 right-0 z-40 flex h-[calc(100vh-4rem)] w-[min(20rem,90vw)] flex-col border-l border-amber-200 bg-white shadow-2xl transition-transform duration-300 ease-in-out ${
          supervisorDrawerOpen ? "translate-x-0" : "translate-x-full"
        }`}
        aria-hidden={!supervisorDrawerOpen}
      >
        <div className="flex items-center justify-between border-b border-amber-200 bg-amber-50 px-4 py-3 shrink-0">
          <p className="text-sm font-bold text-amber-900">Submit new query</p>
          <button
            type="button"
            onClick={closeSupervisorDrawer}
            className="text-gray-500 hover:text-gray-800 p-1 rounded-md hover:bg-amber-100"
            aria-label="Collapse panel"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-5 h-5">
              <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
            </svg>
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          <div className="flex items-center gap-2 text-xs">
            <span
              className={`rounded-full px-2 py-0.5 font-semibold ${
                supervisorDrawerStep === 1
                  ? "bg-amber-500 text-white"
                  : "bg-gray-100 text-gray-500"
              }`}
            >
              1. Enter
            </span>
            <span className="text-gray-300">→</span>
            <span
              className={`rounded-full px-2 py-0.5 font-semibold ${
                supervisorDrawerStep === 2
                  ? "bg-amber-500 text-white"
                  : "bg-gray-100 text-gray-500"
              }`}
            >
              2. Related
            </span>
            <span className="text-gray-300">→</span>
            <span className="rounded-full bg-gray-100 px-2 py-0.5 font-semibold text-gray-500">
              3. Supervisor
            </span>
          </div>

          {supervisorDrawerStep === 1 ? (
            <>
              <p className="text-xs text-gray-600">
                Describe the issue. We will check the knowledge base for similar
                problems before sending to supervisor.
              </p>
              <label className="block text-xs font-semibold text-gray-700">
                Describe the issue in detail
              </label>
              <textarea
                value={supervisorDraft}
                onChange={(e) => setSupervisorDraft(e.target.value)}
                rows={8}
                disabled={
                  sessionResolved ||
                  isLoadingSupervisorMatches ||
                  isSubmittingSupervisor
                }
                className="w-full text-sm border border-gray-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-amber-400 resize-none bg-white disabled:opacity-60 min-h-[140px]"
                placeholder="Include symptoms, error messages, and what the caller already tried..."
              />
              <button
                type="button"
                onClick={() => void continueToRelatedMatches()}
                disabled={
                  !supervisorDraft.trim() ||
                  isLoadingSupervisorMatches ||
                  sessionResolved
                }
                className="w-full text-sm bg-amber-500 hover:bg-amber-400 text-white font-semibold px-3 py-2.5 rounded-lg transition disabled:opacity-50"
              >
                {isLoadingSupervisorMatches ? "Checking…" : "Continue"}
              </button>
            </>
          ) : (
            <>
              <p className="text-xs text-gray-600">
                This might be the problem you are looking for. Open one if it
                fits, or skip to supervisor.
              </p>
              <div className="rounded-lg border border-blue-100 bg-blue-50/50 p-2 text-xs text-blue-900">
                <span className="font-medium">Your query:</span>{" "}
                {supervisorDraft}
              </div>

              {supervisorRelatedMatches.length > 0 ? (
                <div className="space-y-2">
                  {supervisorRelatedMatches.map((result, index) =>
                    renderResultCard(
                      result,
                      supervisorDraft,
                      index,
                      handleSelectResultFromDrawer
                    )
                  )}
                </div>
              ) : (
                <p className="text-xs text-gray-500 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2">
                  No close matches in the knowledge base.
                </p>
              )}

              <button
                type="button"
                onClick={() => void submitSupervisorQuery()}
                disabled={isSubmittingSupervisor || sessionResolved}
                className="w-full text-sm bg-amber-500 hover:bg-amber-400 text-white font-semibold px-3 py-2.5 rounded-lg transition disabled:opacity-50"
              >
                {isSubmittingSupervisor
                  ? "Submitting…"
                  : "Skip and submit to supervisor"}
              </button>

              <button
                type="button"
                onClick={() => setSupervisorDrawerStep(1)}
                disabled={isSubmittingSupervisor}
                className="w-full text-xs bg-white border border-gray-300 hover:bg-gray-50 text-gray-700 font-medium px-3 py-2 rounded-lg transition disabled:opacity-50"
              >
                Back to edit query
              </button>
            </>
          )}

          {trackedPending ? (
            <button
              type="button"
              onClick={() =>
                void checkSupervisorStatus(trackedPending.pendingId).catch(
                  () => undefined
                )
              }
              disabled={isCheckingSupervisor}
              className="w-full text-xs bg-white border border-amber-300 hover:bg-amber-50 text-amber-900 font-medium px-3 py-2 rounded-lg transition disabled:opacity-50"
            >
              {isCheckingSupervisor ? "Checking…" : "Check submission status"}
            </button>
          ) : null}
        </div>
      </aside>
    </>
  );

  const renderChatMessage = (msg: ChatMessage) => {
    if (msg.role === "user") {
      return (
        <div key={msg.id} className="mb-4 flex justify-end">
          <div className="max-w-[85%] rounded-2xl rounded-br-md bg-gradient-to-r from-[#2563EB] to-[#1D4ED8] px-4 py-3 text-sm leading-relaxed text-white shadow-lg shadow-blue-500/15">
            {msg.content}
          </div>
        </div>
      );
    }

    if (msg.kind === "welcome") {
      const isBuyer = callerType === "buyer";

      return (
        <div key={msg.id} className="mb-6 flex justify-start">
          <div className="w-full max-w-[95%]">
            <div className="flex items-start gap-3">
              <AgentAvatar callerType={callerType} />
              <div className="rounded-2xl rounded-tl-md border border-[#E5EAF2] bg-white px-5 py-4 text-sm leading-relaxed text-[#0F172A] shadow-sm">
                <p className="mb-2 font-medium">
                  Welcome to Northwind {isBuyer ? "Buyer" : "Seller"} Support
                </p>
                <p className="mb-1 text-[#64748B]">
                  Browse by category or search below — {branchCount} approved
                  issues loaded for this session.
                </p>
                <p className="text-xs text-[#94A3B8]">
                  Step 1: pick a category · Step 2: choose the specific issue
                </p>
              </div>
            </div>
            <div className="ml-12 mt-4">
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-[#64748B]">
                {isBuyer ? "Buyer" : "Seller"} categories
              </p>
              <CategoryGrid
                categories={topicCategories}
                onSelect={(category) => void handleCategorySelect(category)}
                disabled={isSearching || sessionResolved || isLoadingBranch}
                callerType={callerType}
              />
            </div>
          </div>
        </div>
      );
    }

    if (msg.kind === "loading") {
      return (
        <div key={msg.id} className="flex justify-start mb-4">
          <div className="flex items-start gap-3">
            <AgentAvatar callerType={callerType} />
            <div className="bg-white rounded-2xl rounded-tl-md border border-[#E5EAF2] shadow-sm px-4 py-3 text-sm text-gray-600">
              <p className="mb-1">Searching {branchCount} branches…</p>
              <TypingIndicator />
            </div>
          </div>
        </div>
      );
    }

    if (msg.kind === "error") {
      return (
        <div key={msg.id} className="flex justify-start mb-4">
          <div className="flex items-start gap-3 max-w-[90%]">
            <AgentAvatar callerType={callerType} />
            <div className="bg-red-50 border border-red-200 rounded-2xl rounded-tl-md px-4 py-3 text-sm">
              <p className="text-red-700 font-medium mb-2">
                Search failed. Check backend connection.
              </p>
              <button
                type="button"
                onClick={() => void sendMessage(msg.query)}
                disabled={isSearching}
                className="text-xs bg-red-600 hover:bg-red-500 text-white font-medium px-3 py-1.5 rounded-lg transition disabled:opacity-50"
              >
                Retry
              </button>
            </div>
          </div>
        </div>
      );
    }

    if (msg.kind === "no_results") {
      return (
        <div key={msg.id} className="flex justify-start mb-4">
          <div className="flex items-start gap-3 max-w-[90%] w-full">
            <AgentAvatar callerType={callerType} />
            <div className="flex-1 bg-white rounded-2xl rounded-tl-md border border-[#E5EAF2] shadow-sm px-4 py-3 text-sm text-gray-800">
              <p className="mb-3">
                No matching issues found in our knowledge base.
              </p>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => openSupervisorPanel(msg.query)}
                  disabled={sessionResolved || isSubmittingSupervisor}
                  className="rounded-xl bg-gradient-to-r from-amber-500 to-orange-500 px-4 py-2 text-xs font-semibold text-white shadow-md shadow-amber-500/20 transition hover:shadow-lg disabled:opacity-50"
                >
                  Submit a new query
                </button>
                <button
                  type="button"
                  onClick={showBrowseCategories}
                  className="rounded-xl border border-[#E5EAF2] bg-white px-4 py-2 text-xs font-semibold text-[#0F172A] transition hover:border-[#2563EB]/30 hover:bg-[#F8FAFC]"
                >
                  Browse by category
                </button>
              </div>
            </div>
          </div>
        </div>
      );
    }

    if (msg.kind === "outlier") {
      return (
        <div key={msg.id} className="flex justify-start mb-4">
          <div className="flex items-start gap-3 max-w-[90%] w-full">
            <AgentAvatar callerType={callerType} />
            <div className="flex-1 bg-amber-50 border border-amber-200 rounded-2xl rounded-tl-md px-4 py-3 text-sm text-amber-950">
              <p className="font-medium mb-2">{msg.message}</p>
              {msg.suggestedQueries.length > 0 ? (
                <div className="flex flex-wrap gap-2">
                  <span className="text-xs text-amber-800 w-full">
                    Try one of these:
                  </span>
                  {msg.suggestedQueries.map((suggestion) => (
                    <button
                      key={suggestion}
                      type="button"
                      onClick={() => {
                        setInputValue(suggestion);
                        inputRef.current?.focus();
                      }}
                      className="text-xs bg-white border border-amber-300 hover:bg-amber-100 text-amber-900 font-medium px-3 py-1.5 rounded-lg transition"
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          </div>
        </div>
      );
    }

    if (msg.kind === "supervisor_submitted") {
      return (
        <div key={msg.id} className="flex justify-start mb-4">
          <div className="flex items-start gap-3 max-w-[90%] w-full">
            <AgentAvatar callerType={callerType} />
            <div className="bg-green-50 border border-green-200 rounded-2xl rounded-tl-md px-4 py-3 text-sm text-gray-800">
              <p className="mb-3 text-green-800">
                Your query has been submitted to the supervisor team. A new
                draft will be created from the unified knowledge base.
              </p>
              <button
                type="button"
                onClick={() =>
                  void checkSupervisorStatus(msg.pendingId).catch(() => undefined)
                }
                disabled={isCheckingSupervisor}
                className="text-xs bg-white border border-green-300 hover:bg-green-100 text-green-800 font-medium px-3 py-1.5 rounded-lg transition disabled:opacity-50"
              >
                {isCheckingSupervisor ? "Checking…" : "Check Status"}
              </button>
            </div>
          </div>
        </div>
      );
    }

    if (msg.kind === "supervisor_approved") {
      return (
        <div key={msg.id} className="flex justify-start mb-4">
          <div className="flex items-start gap-3 max-w-[90%] w-full">
            <AgentAvatar callerType={callerType} />
            <div className="bg-emerald-50 border border-emerald-200 rounded-2xl rounded-tl-md px-4 py-3 text-sm text-gray-800">
              <p className="font-medium text-emerald-800 mb-1">
                Supervisor approved: {msg.branchName}
              </p>
              <p className="text-xs text-emerald-700 mb-2">
                {msg.addedToKb
                  ? "Added to knowledge base and sent to you."
                  : "Resolution sent to you for this call (not saved to KB)."}
              </p>
              {msg.resolutionText ? (
                <pre className="whitespace-pre-wrap text-xs text-gray-700 bg-white border border-emerald-100 rounded-lg p-3 mb-3 max-h-48 overflow-y-auto font-sans">
                  {msg.resolutionText}
                </pre>
              ) : null}
              {msg.resolutionSteps && msg.resolutionSteps.length > 0 ? (
                <ol className="list-decimal list-inside space-y-1 text-xs text-gray-700 mb-3 bg-white border border-emerald-100 rounded-lg p-3">
                  {msg.resolutionSteps.map((step, index) => (
                    <li key={`${step}-${index}`}>{step}</li>
                  ))}
                </ol>
              ) : null}
              <div className="flex flex-wrap gap-2">
                {msg.branchId ? (
                  <button
                    type="button"
                    onClick={() => void handleSelectBranchById(msg.branchId!)}
                    disabled={isLoadingBranch || sessionResolved}
                    className="text-xs bg-emerald-600 hover:bg-emerald-500 text-white font-medium px-3 py-1.5 rounded-lg transition disabled:opacity-50"
                  >
                    Open resolution steps
                  </button>
                ) : null}
                <button
                  type="button"
                  onClick={() => void checkSupervisorStatusByQuery(msg.query)}
                  disabled={isCheckingSupervisor}
                  className="text-xs bg-white border border-emerald-300 hover:bg-emerald-100 text-emerald-800 font-medium px-3 py-1.5 rounded-lg transition disabled:opacity-50"
                >
                  Check Status
                </button>
              </div>
            </div>
          </div>
        </div>
      );
    }

    if (msg.kind === "supervisor_rejected") {
      return (
        <div key={msg.id} className="flex justify-start mb-4">
          <div className="flex items-start gap-3 max-w-[90%] w-full">
            <AgentAvatar callerType={callerType} />
            <div className="bg-red-50 border border-red-200 rounded-2xl rounded-tl-md px-4 py-3 text-sm text-gray-800">
              <p className="font-medium text-red-800 mb-1">
                Supervisor rejected this query
              </p>
              {msg.reason ? (
                <p className="text-xs text-red-700">{msg.reason}</p>
              ) : (
                <p className="text-xs text-red-700">
                  Please rephrase or browse categories.
                </p>
              )}
            </div>
          </div>
        </div>
      );
    }

    if (msg.kind === "browse_categories") {
      return (
        <div key={msg.id} className="flex justify-start mb-4">
          <div className="flex items-start gap-3 max-w-[95%] w-full">
            <AgentAvatar callerType={callerType} />
            <div className="flex-1 bg-white rounded-2xl rounded-tl-md border border-[#E5EAF2] shadow-sm px-4 py-3 text-sm">
              <p className="text-gray-700 font-medium mb-3">
                Select a {callerType === "buyer" ? "buyer" : "seller"} category:
              </p>
              <CategoryGrid
                categories={topicCategories}
                onSelect={(category) => void handleCategorySelect(category)}
                disabled={isSearching || sessionResolved || isLoadingBranch}
                callerType={callerType}
              />
            </div>
          </div>
        </div>
      );
    }

    if (msg.kind === "category_empty") {
      return (
        <div key={msg.id} className="flex justify-start mb-4">
          <div className="flex items-start gap-3 max-w-[90%]">
            <AgentAvatar callerType={callerType} />
            <div className="bg-white rounded-2xl rounded-tl-md border border-[#E5EAF2] shadow-sm px-4 py-3 text-sm text-gray-800">
              <p className="mb-2">
                No issues are in the knowledge base for{" "}
                <span className="font-medium">{msg.categoryName}</span> yet.
                Try another category or type a search below.
              </p>
              <button
                type="button"
                onClick={showBrowseCategories}
                className="text-xs bg-white border border-gray-300 hover:bg-gray-50 text-gray-700 font-medium px-3 py-1.5 rounded-lg transition"
              >
                Pick another category
              </button>
            </div>
          </div>
        </div>
      );
    }

    if (msg.kind === "category_topics") {
      return (
        <div key={msg.id} className="flex justify-start mb-4">
          <div className="flex items-start gap-3 max-w-[95%] w-full">
            <AgentAvatar callerType={callerType} />
            <div className="flex-1 bg-white rounded-2xl rounded-tl-md border border-[#E5EAF2] shadow-sm px-4 py-3 text-sm">
              <p className="text-gray-700 font-medium mb-1">{msg.categoryName}</p>
              <p className="text-gray-500 text-xs mb-3">
                {msg.branches.length} issue{msg.branches.length !== 1 ? "s" : ""}{" "}
                in this category. Click one to open resolution steps:
              </p>
              <div className="space-y-1.5 max-h-80 overflow-y-auto">
                {msg.branches.map((branch) => (
                  <button
                    key={branch.branch_id}
                    type="button"
                    onClick={() => void handleSelectBranchById(branch.branch_id)}
                    disabled={isLoadingBranch || sessionResolved}
                    className="w-full rounded-xl border border-[#E5EAF2] bg-white px-4 py-3 text-left text-sm font-medium text-[#0F172A] transition hover:border-[#2563EB]/30 hover:bg-[#EFF6FF] hover:shadow-sm disabled:opacity-50"
                  >
                    {branch.branch_name}
                  </button>
                ))}
              </div>
              <button
                type="button"
                onClick={showBrowseCategories}
                className="mt-3 text-xs text-blue-600 hover:text-blue-700 font-medium"
              >
                ← Change category
              </button>
            </div>
          </div>
        </div>
      );
    }

    if (msg.kind === "results") {
      const topScore =
        msg.results.length > 0 ? getResultScore(msg.results[0]) : 0;
      const weakMatch = topScore < searchConfig.weakMatchScore;

      return (
        <div key={msg.id} className="flex justify-start mb-4">
          <div className="flex items-start gap-3 max-w-[95%] w-full">
            <AgentAvatar callerType={callerType} />
            <div className="flex-1 min-w-0">
              <div className="bg-white rounded-2xl rounded-tl-md border border-[#E5EAF2] shadow-sm px-4 py-3 text-sm text-gray-800 mb-2">
                I found {msg.results.length} matching issue
                {msg.results.length !== 1 ? "s" : ""}. Click one to view
                resolution steps:
                {weakMatch ? (
                  <span className="block mt-2 text-xs text-amber-800">
                    These may not be a close match. Use{" "}
                    <strong>New query</strong> on the right edge if none fit.
                  </span>
                ) : null}
              </div>
              <div className="space-y-2">
                {msg.results.map((result, index) =>
                  renderResultCard(result, msg.query, index)
                )}
              </div>
              <div className="mt-3 pt-3 border-t border-gray-200">
                <button
                  type="button"
                  onClick={() => openSupervisorPanel(msg.query)}
                  disabled={sessionResolved || isSubmittingSupervisor}
                  className="rounded-xl bg-gradient-to-r from-amber-500 to-orange-500 px-4 py-2 text-xs font-semibold text-white shadow-md shadow-amber-500/20 transition hover:shadow-lg disabled:opacity-50"
                >
                  None of these? Submit a new query
                </button>
              </div>
            </div>
          </div>
        </div>
      );
    }

    return null;
  };

  const renderStepper = () => {
    if (!activeBranch) return null;

    const branch = activeBranch;
    const totalSteps = branch.steps.length;
    const progressPct =
      totalSteps > 0 ? ((currentStepIndex + 1) / totalSteps) * 100 : 0;

    if (stepperMode === "blocked") {
      return (
        <div className="space-y-5">
          <PathBreadcrumb path={activePath} />
          <div className="rounded-2xl border border-red-200 bg-red-50 p-6 shadow-sm">
            <p className="mb-1 text-lg font-bold text-red-700">Issue blocked</p>
            <p className="mb-2 text-sm text-red-800">
              {blockedInfo?.message ||
                "Do not proceed to the next step. This issue is blocked."}
            </p>
            <p className="text-sm font-semibold text-[#2563EB]">
              {blockedInfo?.action || `Escalate to: ${branch.escalation}`}
            </p>
            <p className="mt-1 text-xs text-[#64748B]">
              {blockedInfo?.escalation_person || branch.escalation_person}
            </p>
          </div>
          {renderDocumentsChecklist(
            branch,
            "Documents (if escalating)",
            "Only collect these if you need to escalate or the issue is not resolved."
          )}
        </div>
      );
    }

    if (stepperMode === "completed") {
      return (
        <div className="space-y-5">
          <PathBreadcrumb path={activePath} />
          <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-6 shadow-sm">
            <p className="mb-1 text-lg font-bold text-emerald-800">
              All steps verified
            </p>
            <p className="text-sm text-emerald-900">
              The guided steps are complete. Use the checklist below only if
              documents are still needed.
            </p>
          </div>
          <button
            type="button"
            onClick={handleCopySummary}
            className="w-full rounded-2xl border border-[#E5EAF2] bg-white py-3 text-sm font-semibold text-[#0F172A] shadow-sm transition hover:border-[#2563EB]/30 hover:shadow-md"
          >
            {copied ? "Copied to clipboard" : "Copy call summary"}
          </button>
          {renderDocumentsChecklist(
            branch,
            "Documents (if needed)",
            "Optional. Collect only if the customer still has an issue."
          )}
        </div>
      );
    }

    return (
      <div className="space-y-5">
        <PathBreadcrumb path={activePath} />
        <div className="flex items-center justify-between gap-3">
          <span className="rounded-full bg-[#EFF6FF] px-3 py-1.5 text-xs font-semibold text-[#2563EB]">
            {branch.branch_name}
          </span>
          <span className="text-xs font-medium text-[#64748B]">
            Step {currentStepIndex + 1} of {totalSteps}
          </span>
        </div>
        <div className="h-2 w-full overflow-hidden rounded-full bg-[#E2E8F0]">
          <div
            className="h-full rounded-full bg-gradient-to-r from-[#2563EB] to-[#1D4ED8] transition-all duration-500"
            style={{ width: `${progressPct}%` }}
          />
        </div>

        <div className="rounded-2xl border border-indigo-100 bg-indigo-50/50 p-5 shadow-sm">
          <p className="mb-2 text-xs font-bold uppercase tracking-wide text-indigo-700">
            Agent script
          </p>
          <p className="whitespace-pre-line text-sm leading-relaxed text-[#0F172A]">
            {branch.agent_script}
          </p>
        </div>

        <div className="rounded-2xl border border-[#E5EAF2] bg-[#F8FAFC] p-5">
          {branch.steps.map((stepText, i) => {
            if (!completedSteps[i]) return null;
            return (
              <div
                key={i}
                className="mb-2 flex gap-2 text-sm text-emerald-700 line-through opacity-70"
              >
                <span>✓</span>
                <span>{stepText}</span>
              </div>
            );
          })}

          <div
            className={`rounded-2xl border border-[#2563EB]/20 bg-white p-5 shadow-sm transition-all ${
              stepPulse ? "ring-4 ring-[#2563EB]/10" : ""
            }`}
          >
            <div className="mb-4 flex items-start gap-3">
              <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-[#2563EB] to-[#1D4ED8] text-xs font-bold text-white">
                {currentStepIndex + 1}
              </span>
              <span className="pt-1 text-sm font-medium leading-relaxed text-[#0F172A]">
                {branch.steps[currentStepIndex]}
              </span>
            </div>
            <div className="flex gap-3">
              <button
                type="button"
                onClick={handleStepDone}
                disabled={isVerifying}
                className="flex-1 rounded-xl bg-gradient-to-r from-emerald-600 to-green-600 py-3 text-sm font-semibold text-white shadow-lg shadow-emerald-500/20 transition hover:shadow-xl disabled:opacity-50"
              >
                Step complete
              </button>
              <button
                type="button"
                onClick={handleStepBlocked}
                disabled={isVerifying}
                className="flex-1 rounded-xl border border-red-200 bg-white py-3 text-sm font-semibold text-red-600 transition hover:bg-red-50 disabled:opacity-50"
              >
                Blocked
              </button>
            </div>
          </div>
        </div>

        <div className="rounded-2xl border border-[#E5EAF2] bg-white p-4 shadow-sm">
          <p className="mb-1 text-xs font-bold uppercase tracking-wide text-[#64748B]">
            If any step fails
          </p>
          <p className="text-sm text-[#0F172A]">{branch.escalation}</p>
          <p className="mt-1 text-xs text-[#64748B]">
            ({branch.escalation_person})
          </p>
        </div>
      </div>
    );
  };

  const canContinueToCopilot =
    Boolean(callerId.trim()) && gateSelectedType !== null;

  return (
    <div className="brand-premium-bg brand-session-shell flex min-h-screen flex-col text-[#0F172A]">
      {view === "caller_gate" ? (
        <div className="flex min-h-screen flex-col">
          <header className="border-b border-[#E5EAF2]/80 bg-white/70 px-4 py-4 backdrop-blur-md sm:px-6">
            <div className="mx-auto flex max-w-[1100px] flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-3">
                <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-gradient-to-br from-[#2563EB] to-[#1D4ED8] text-white shadow-lg shadow-blue-500/20">
                  <BotIcon className="h-5 w-5" />
                </div>
                <div>
                  <h1 className="text-lg font-bold tracking-tight text-[#0F172A] sm:text-xl">
                    Helpdesk Copilot
                  </h1>
                  <p className="text-sm text-[#64748B]">
                    AI-powered support assistant
                  </p>
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <span className="inline-flex items-center gap-1.5 rounded-full border border-[#E5EAF2] bg-white px-3 py-1.5 text-xs font-medium text-[#0F172A] shadow-sm">
                  <ShieldCheckIcon className="h-3.5 w-3.5 text-[#2563EB]" />
                  Supervisor Governed
                </span>
                <span className="hidden items-center gap-1.5 rounded-full border border-[#E5EAF2] bg-white px-3 py-1.5 text-xs font-medium text-[#0F172A] shadow-sm sm:inline-flex">
                  Secure KB
                </span>
              </div>
            </div>
          </header>

          <main className="flex flex-1 items-center justify-center px-4 py-8 sm:px-6 sm:py-12">
            <div className="brand-fade-in w-full max-w-xl overflow-hidden rounded-[28px] border border-[#E5EAF2] bg-white shadow-[0_24px_64px_-12px_rgba(15,23,42,0.12)]">
              <section className="flex flex-col justify-center p-8 sm:p-10">
                  <div className="mb-8">
                    <h3 className="text-2xl font-bold tracking-tight text-[#0F172A]">
                      Welcome to Helpdesk Copilot
                    </h3>
                    <p className="mt-2 text-sm leading-relaxed text-[#64748B]">
                      Set up the caller context to begin an assisted resolution
                      session.
                    </p>
                  </div>

                  <div className="space-y-6">
                    <div>
                      <label
                        htmlFor="caller-id"
                        className="mb-2 block text-sm font-semibold text-[#0F172A]"
                      >
                        Caller ID
                      </label>
                      <input
                        id="caller-id"
                        type="text"
                        value={callerId}
                        onChange={(e) => setCallerId(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && canContinueToCopilot) {
                            e.preventDefault();
                            handleContinueToCopilot();
                          }
                        }}
                        placeholder="Enter caller ID or ticket reference"
                        className="h-14 w-full rounded-2xl border border-[#E5EAF2] bg-[#F8FAFC] px-4 text-sm text-[#0F172A] shadow-sm transition placeholder:text-[#94A3B8] focus:border-[#2563EB] focus:bg-white focus:outline-none focus:ring-4 focus:ring-[#2563EB]/15"
                        autoComplete="off"
                      />
                    </div>

                    <fieldset>
                      <legend className="mb-1 block text-sm font-semibold text-[#0F172A]">
                        Who is on the line?
                      </legend>
                      <p className="mb-3 text-xs text-[#64748B]">
                        Choose the caller profile so the assistant can load the
                        right knowledge base.
                      </p>
                      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                        <button
                          type="button"
                          aria-pressed={gateSelectedType === "buyer"}
                          onClick={() => setGateSelectedType("buyer")}
                          className={`group relative flex min-h-[120px] flex-col items-start rounded-2xl border-2 p-5 text-left transition-all duration-200 focus:outline-none focus-visible:ring-4 focus-visible:ring-[#2563EB]/20 ${
                            gateSelectedType === "buyer"
                              ? "border-[#2563EB] bg-blue-50/80 shadow-md shadow-blue-500/10"
                              : "border-[#E5EAF2] bg-white hover:-translate-y-0.5 hover:border-[#2563EB]/40 hover:shadow-md"
                          }`}
                        >
                          {gateSelectedType === "buyer" ? (
                            <CheckCircle2Icon className="absolute right-4 top-4 h-5 w-5 text-[#2563EB]" />
                          ) : null}
                          <span
                            className={`mb-3 flex h-11 w-11 items-center justify-center rounded-xl transition-colors ${
                              gateSelectedType === "buyer"
                                ? "bg-[#2563EB] text-white"
                                : "bg-[#F1F5F9] text-[#64748B] group-hover:bg-blue-100 group-hover:text-[#2563EB]"
                            }`}
                          >
                            <ShoppingCartIcon className="h-5 w-5" />
                          </span>
                          <span className="text-base font-semibold text-[#0F172A]">
                            Buyer
                          </span>
                          <span className="mt-1 text-xs text-[#64748B]">
                            Orders, payments, procurement, account support
                          </span>
                        </button>

                        <button
                          type="button"
                          aria-pressed={gateSelectedType === "seller"}
                          onClick={() => setGateSelectedType("seller")}
                          className={`group relative flex min-h-[120px] flex-col items-start rounded-2xl border-2 p-5 text-left transition-all duration-200 focus:outline-none focus-visible:ring-4 focus-visible:ring-[#2563EB]/20 ${
                            gateSelectedType === "seller"
                              ? "border-[#2563EB] bg-blue-50/80 shadow-md shadow-blue-500/10"
                              : "border-[#E5EAF2] bg-white hover:-translate-y-0.5 hover:border-[#2563EB]/40 hover:shadow-md"
                          }`}
                        >
                          {gateSelectedType === "seller" ? (
                            <CheckCircle2Icon className="absolute right-4 top-4 h-5 w-5 text-[#2563EB]" />
                          ) : null}
                          <span
                            className={`mb-3 flex h-11 w-11 items-center justify-center rounded-xl transition-colors ${
                              gateSelectedType === "seller"
                                ? "bg-[#2563EB] text-white"
                                : "bg-[#F1F5F9] text-[#64748B] group-hover:bg-blue-100 group-hover:text-[#2563EB]"
                            }`}
                          >
                            <Building2Icon className="h-5 w-5" />
                          </span>
                          <span className="text-base font-semibold text-[#0F172A]">
                            {SELLER_CALLER_LABEL}
                          </span>
                          <span className="mt-1 text-xs text-[#64748B]">
                            Catalog, listing, compliance, service-related support
                          </span>
                        </button>
                      </div>
                    </fieldset>

                    <button
                      type="button"
                      onClick={handleContinueToCopilot}
                      disabled={!canContinueToCopilot}
                      className="group flex h-14 w-full items-center justify-center gap-2 rounded-2xl bg-gradient-to-r from-[#2563EB] to-[#1D4ED8] text-sm font-semibold text-white shadow-lg shadow-blue-500/25 transition-all duration-200 hover:shadow-xl hover:shadow-blue-500/30 focus:outline-none focus-visible:ring-4 focus-visible:ring-[#2563EB]/30 disabled:cursor-not-allowed disabled:opacity-45 disabled:shadow-none"
                    >
                      Get Started
                      <ArrowRightIcon className="h-4 w-4 transition-transform group-hover:translate-x-1 group-disabled:translate-x-0" />
                    </button>

                    <p className="text-center text-xs leading-relaxed text-[#64748B]">
                      {canContinueToCopilot
                        ? "Session will open with the selected caller context."
                        : "Enter caller ID and select caller type to continue."}
                    </p>

                    <p className="text-center text-[11px] leading-relaxed text-[#94A3B8]">
                      Supervisor-approved answers • Escalation-ready flows •
                      Audit trail enabled
                    </p>
                  </div>
                </section>
            </div>
          </main>
        </div>
      ) : (
        <>
      <header className="fixed top-0 left-0 right-0 z-10 border-b border-[#E5EAF2]/80 bg-white/80 px-4 py-3 backdrop-blur-md">
        <div className="mx-auto flex max-w-4xl items-center justify-between">
          <div className="flex items-center gap-3">
            <div
              className={`flex h-10 w-10 items-center justify-center rounded-xl text-white shadow-md ${
                callerType === "buyer"
                  ? "bg-gradient-to-br from-indigo-600 to-blue-600 shadow-indigo-500/20"
                  : "bg-gradient-to-br from-[#2563EB] to-[#1D4ED8] shadow-blue-500/20"
              }`}
            >
              {callerType === "buyer" ? (
                <ShoppingCartIcon className="h-4 w-4" />
              ) : (
                <Building2Icon className="h-4 w-4" />
              )}
            </div>
            <div>
              <h1 className="text-base font-bold tracking-tight text-[#0F172A] sm:text-lg">
                Helpdesk Copilot
              </h1>
              <p className="text-xs text-[#64748B]">
                {callerType === "buyer"
                  ? "Buyer Support Session"
                  : callerType === "seller"
                    ? "Seller Support Session"
                    : "Active Session"}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {callerId.trim() && (
              <span className="hidden rounded-full border border-[#E5EAF2] bg-white px-2.5 py-1 text-xs font-medium text-[#64748B] shadow-sm sm:inline-block">
                ID: {callerId.trim()}
              </span>
            )}
            {callerType === "seller" && (
              <span className="rounded-full bg-[#EFF6FF] px-2.5 py-1 text-xs font-semibold text-[#2563EB]">
                {SELLER_CALLER_LABEL}
              </span>
            )}
            {callerType === "buyer" && (
              <span className="rounded-full bg-indigo-50 px-2.5 py-1 text-xs font-semibold text-indigo-700">
                Buyer
              </span>
            )}
            <NewCallButton onClick={handleNewCall} />
          </div>
        </div>
      </header>
        </>
      )}

      {view === "chat" && (
        <div className="flex min-h-screen flex-1 flex-col pt-[4.5rem]">
          {renderSupervisorDrawer()}
          <div className="flex-1 overflow-y-auto px-4 pb-4">
            <div className="mx-auto max-w-3xl py-6">
              {messages.map(renderChatMessage)}
            </div>
          </div>

          <div className="sticky bottom-0 border-t border-[#E5EAF2]/80 bg-white/90 px-4 py-4 backdrop-blur-md">
            <div className="mx-auto max-w-3xl">
              {scopedCategoryId ? (
                <div className="mb-2 flex flex-wrap items-center gap-2">
                  <span className="text-xs text-[#64748B]">Search scoped to:</span>
                  <span className="rounded-full bg-[#EFF6FF] px-2.5 py-1 text-xs font-semibold text-[#2563EB]">
                    {topicCategories.find((c) => c.id === scopedCategoryId)?.name ??
                      "Category"}
                  </span>
                  <button
                    type="button"
                    onClick={() => setScopedCategoryId(null)}
                    className="text-xs font-medium text-[#64748B] transition hover:text-[#2563EB]"
                  >
                    Search all
                  </button>
                </div>
              ) : null}
              {searchCorrection ? (
                <div
                  role="status"
                  className="mb-2 flex flex-wrap items-center gap-2 rounded-xl border border-[#E5EAF2] bg-[#F8FAFC] px-3 py-2 text-xs text-[#475569]"
                >
                  <span>Search instead for:</span>
                  <button
                    type="button"
                    onClick={() => {
                      setInputValue(searchCorrection.corrected);
                      void sendMessage(searchCorrection.corrected);
                    }}
                    className="font-semibold text-[#2563EB] underline-offset-2 hover:underline"
                  >
                    {searchCorrection.corrected}
                  </button>
                  <button
                    type="button"
                    onClick={() => setSearchCorrection(null)}
                    className="text-[#94A3B8] hover:text-[#64748B]"
                  >
                    Keep original
                  </button>
                </div>
              ) : null}
              {predictedCategory && !scopedCategoryId ? (
                <div className="mb-2 flex flex-wrap items-center gap-2">
                  <span className="text-xs text-[#64748B]">Likely category:</span>
                  <span className="rounded-full bg-violet-50 px-2.5 py-1 text-xs font-semibold text-violet-700">
                    {predictedCategory.name}
                  </span>
                  <button
                    type="button"
                    onClick={() => setScopedCategoryId(predictedCategory.id)}
                    className="text-xs font-medium text-[#2563EB] transition hover:underline"
                  >
                    Scope search
                  </button>
                  <button
                    type="button"
                    onClick={() => setPredictedCategory(null)}
                    className="text-xs font-medium text-[#64748B] transition hover:text-[#2563EB]"
                  >
                    Dismiss
                  </button>
                </div>
              ) : null}
              {outlierCheck?.is_outlier ? (
                <div
                  role="status"
                  className="mb-3 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950 shadow-sm"
                >
                  <p className="font-medium">{outlierCheck.message}</p>
                  {outlierCheck.suggested_queries.length > 0 ? (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      <span className="w-full text-xs text-amber-800">
                        Suggested searches:
                      </span>
                      {outlierCheck.suggested_queries.map((suggestion) => (
                        <button
                          key={suggestion}
                          type="button"
                          onClick={() => {
                            setInputValue(suggestion);
                            inputRef.current?.focus();
                          }}
                          className="rounded-full border border-amber-200 bg-white px-3 py-1 text-xs font-medium text-amber-900 transition hover:bg-amber-100"
                        >
                          {suggestion}
                        </button>
                      ))}
                    </div>
                  ) : null}
                </div>
              ) : null}
              <div className="flex items-end gap-3 rounded-2xl border border-[#E5EAF2] bg-white px-4 py-3 shadow-lg shadow-slate-200/50 transition focus-within:border-[#2563EB]/50 focus-within:ring-4 focus-within:ring-[#2563EB]/10">
                <textarea
                  ref={inputRef}
                  value={inputValue}
                  onChange={(e) => setInputValue(e.target.value)}
                  onKeyDown={handleInputKeyDown}
                  disabled={sessionResolved || isSearching}
                  placeholder={
                    callerType === "buyer"
                      ? "Describe the buyer issue or search the knowledge base…"
                      : "Describe the seller issue or search the knowledge base…"
                  }
                  rows={1}
                  className="max-h-32 flex-1 resize-none bg-transparent text-sm text-[#0F172A] placeholder:text-[#94A3B8] focus:outline-none disabled:opacity-50"
                  autoComplete="off"
                />
                <button
                  type="button"
                  onClick={() => void sendMessage(inputValue)}
                  disabled={
                    !inputValue.trim() || isSearching || sessionResolved
                  }
                  className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-gradient-to-r from-[#2563EB] to-[#1D4ED8] text-white shadow-lg shadow-blue-500/25 transition hover:shadow-xl hover:shadow-blue-500/30 disabled:cursor-not-allowed disabled:bg-[#E2E8F0] disabled:from-[#E2E8F0] disabled:to-[#E2E8F0] disabled:text-[#94A3B8] disabled:shadow-none"
                  aria-label="Send message"
                >
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 24 24"
                    fill="currentColor"
                    className="h-4 w-4"
                  >
                    <path d="M3.478 2.404a.75.75 0 0 0-.926.941l2.432 7.905H13.5a.75.75 0 0 1 0 1.5H4.984l-2.432 7.905a.75.75 0 0 0 .926.94 60.519 60.519 0 0 0 18.445-8.986.75.75 0 0 0 0-1.218A60.517 60.517 0 0 0 3.478 2.404Z" />
                  </svg>
                </button>
              </div>
              <p className="mt-2 text-center text-xs text-[#94A3B8]">
                Press Enter to send · Shift+Enter for new line
              </p>
            </div>
          </div>
        </div>
      )}

      {view === "stepper" && (
        <main className="mx-auto w-full max-w-3xl flex-1 px-4 pb-8 pt-[4.5rem]">
          <div className="py-4">
            {!sessionResolved && (
              <button
                type="button"
                onClick={handleBackToChat}
                className="mb-4 flex items-center gap-1 text-sm font-medium text-[#64748B] transition hover:text-[#2563EB]"
              >
                ← Back to chat
              </button>
            )}
            {sessionResolved && (
              <p className="mb-4 text-center text-xs text-[#64748B]">
                Call ended. Start a New Call to continue.
              </p>
            )}
            {isLoadingBranch ? (
              <div className="flex flex-col items-center justify-center rounded-[28px] border border-[#E5EAF2] bg-white py-16 shadow-sm">
                <div className="mb-4 h-10 w-10 animate-spin rounded-full border-4 border-[#EFF6FF] border-t-[#2563EB]" />
                <p className="text-sm font-medium text-[#2563EB]">
                  Loading issue details…
                </p>
              </div>
            ) : (
              <div className="rounded-[28px] border border-[#E5EAF2] bg-white p-6 shadow-[0_16px_48px_-12px_rgba(15,23,42,0.08)] sm:p-8">
                {renderStepper()}
              </div>
            )}
          </div>
        </main>
      )}
    </div>
  );
}
