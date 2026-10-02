"use client";

import { useCallback, useState } from "react";

import { apiFetch } from "../lib/api";
import { backendAlert } from "./errors";
import type { Branch, CallerType } from "./types";

export type StepperMode = "verify" | "blocked" | "completed";

export type BlockedInfo = {
  message: string;
  action: string;
  escalation_person: string;
};

const BRANCH_GONE_MESSAGE =
  "This issue is no longer in the knowledge base. Please start a new search.";

/**
 * Step-by-step verification of one resolution branch: current step, completed
 * steps, collected documents, and the done/blocked calls to /verify-step.
 * `onResolved` fires when the flow ends (all steps done, or blocked).
 */
export function useStepper({
  callerType,
  onResolved,
}: {
  callerType: CallerType | null;
  onResolved: () => void;
}) {
  const [activeBranch, setActiveBranch] = useState<Branch | null>(null);
  const [activePath, setActivePath] = useState<string[]>([]);
  const [currentStepIndex, setCurrentStepIndex] = useState(0);
  const [completedSteps, setCompletedSteps] = useState<boolean[]>([]);
  const [collectedDocs, setCollectedDocs] = useState<Set<string>>(new Set());
  const [stepperMode, setStepperMode] = useState<StepperMode>("verify");
  const [stepPulse, setStepPulse] = useState(false);
  const [blockedInfo, setBlockedInfo] = useState<BlockedInfo | null>(null);
  const [isVerifying, setIsVerifying] = useState(false);

  const pulse = useCallback(() => {
    setStepPulse(true);
    setTimeout(() => setStepPulse(false), 1000);
  }, []);

  const start = useCallback(
    (branch: Branch, path: string[]) => {
      setActiveBranch(branch);
      setActivePath(path);
      setCurrentStepIndex(0);
      setCompletedSteps(branch.steps.map(() => false));
      setCollectedDocs(new Set());
      setStepperMode("verify");
      setBlockedInfo(null);
      pulse();
    },
    [pulse]
  );

  const clearBranch = useCallback(() => {
    setActiveBranch(null);
    setActivePath([]);
  }, []);

  const reset = useCallback(() => {
    clearBranch();
    setCurrentStepIndex(0);
    setCompletedSteps([]);
    setCollectedDocs(new Set());
    setStepperMode("verify");
    setBlockedInfo(null);
    setIsVerifying(false);
  }, [clearBranch]);

  const postVerify = async (status: "done" | "blocked") => {
    if (!activeBranch) return null;
    const res = await apiFetch("/verify-step", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        branch_id: activeBranch.branch_id,
        step_index: currentStepIndex,
        status,
        caller_type: callerType ?? "seller",
      }),
    });
    if (res.status === 404) {
      alert(BRANCH_GONE_MESSAGE);
      return null;
    }
    if (!res.ok) throw new Error("Verify failed");
    return res.json();
  };

  const markDone = async () => {
    if (!activeBranch || isVerifying || stepperMode !== "verify") return;

    setIsVerifying(true);
    try {
      const data = await postVerify("done");
      if (!data) return;

      const updated = [...completedSteps];
      updated[currentStepIndex] = true;
      setCompletedSteps(updated);

      if (data.status === "completed") {
        setStepperMode("completed");
        onResolved();
      } else if (data.status === "next_step") {
        setCurrentStepIndex(data.step_index);
        pulse();
      }
    } catch {
      backendAlert();
    } finally {
      setIsVerifying(false);
    }
  };

  const markBlocked = async () => {
    if (!activeBranch || isVerifying) return;

    setIsVerifying(true);
    try {
      const data = await postVerify("blocked");
      if (!data) return;

      setBlockedInfo({
        message: data.message,
        action: data.action,
        escalation_person: data.escalation_person,
      });
      setStepperMode("blocked");
      onResolved();
    } catch {
      backendAlert();
    } finally {
      setIsVerifying(false);
    }
  };

  const toggleDoc = (doc: string) => {
    setCollectedDocs((prev) => {
      const next = new Set(prev);
      if (next.has(doc)) next.delete(doc);
      else next.add(doc);
      return next;
    });
  };

  return {
    activeBranch,
    activePath,
    currentStepIndex,
    completedSteps,
    collectedDocs,
    stepperMode,
    stepPulse,
    blockedInfo,
    isVerifying,
    start,
    clearBranch,
    reset,
    markDone,
    markBlocked,
    toggleDoc,
  };
}
