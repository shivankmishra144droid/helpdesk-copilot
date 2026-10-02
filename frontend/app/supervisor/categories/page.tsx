"use client";

import { apiFetch } from "../../lib/api";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { API_BASE, type Toast } from "../components/types";
import { formatApiError } from "../components/utils";
import { Toast as ToastNotification } from "../components/Toast";

type DbCategory = {
  id: string;
  name: string;
  category_name: string;
  caller_type: string;
  branch_count: number;
  is_empty: boolean;
};

export default function CategoriesPage() {
  const [categories, setCategories] = useState<DbCategory[]>([]);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState<Toast | null>(null);
  const [newName, setNewName] = useState("");
  const [newCallerType, setNewCallerType] = useState<"seller" | "buyer">("seller");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");
  const [mergeSource, setMergeSource] = useState("");
  const [mergeTarget, setMergeTarget] = useState("");
  const [busy, setBusy] = useState(false);

  const showToast = useCallback((next: Toast) => {
    setToast(next);
    window.setTimeout(() => setToast(null), 4500);
  }, []);

  const fetchCategories = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiFetch(`${API_BASE}/supervisor/categories`);
      if (!res.ok) throw new Error("fetch failed");
      const data = await res.json();
      setCategories(data.categories ?? []);
    } catch {
      showToast({ type: "error", message: "Could not load categories." });
      setCategories([]);
    } finally {
      setLoading(false);
    }
  }, [showToast]);

  useEffect(() => {
    void fetchCategories();
  }, [fetchCategories]);

  const grouped = useMemo(() => {
    const seller = categories.filter((c) => c.caller_type === "seller");
    const buyer = categories.filter((c) => c.caller_type === "buyer");
    return { seller, buyer };
  }, [categories]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    const name = newName.trim();
    if (!name) return;

    setBusy(true);
    try {
      const res = await apiFetch(`${API_BASE}/supervisor/categories`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ category_name: name, caller_type: newCallerType }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(formatApiError(data, "Create failed"));
      showToast({ type: "success", message: `Category "${name}" created.` });
      setNewName("");
      await fetchCategories();
    } catch (error) {
      showToast({
        type: "error",
        message: error instanceof Error ? error.message : "Create failed.",
      });
    } finally {
      setBusy(false);
    }
  };

  const handleRename = async (categoryId: string) => {
    const name = editName.trim();
    if (!name) return;

    setBusy(true);
    try {
      const res = await apiFetch(
        `${API_BASE}/supervisor/categories/${encodeURIComponent(categoryId)}`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ category_name: name }),
        }
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(formatApiError(data, "Rename failed"));
      showToast({ type: "success", message: "Category renamed." });
      setEditingId(null);
      setEditName("");
      await fetchCategories();
    } catch (error) {
      showToast({
        type: "error",
        message: error instanceof Error ? error.message : "Rename failed.",
      });
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async (category: DbCategory) => {
    if (!category.is_empty) {
      showToast({
        type: "error",
        message: "Only empty categories (no KB branches) can be deleted.",
      });
      return;
    }
    if (
      !window.confirm(
        `Delete category "${category.name}"? This cannot be undone.`
      )
    ) {
      return;
    }

    setBusy(true);
    try {
      const res = await apiFetch(
        `${API_BASE}/supervisor/categories/${encodeURIComponent(category.id)}`,
        { method: "DELETE" }
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(formatApiError(data, "Delete failed"));
      showToast({ type: "success", message: "Category deleted." });
      await fetchCategories();
    } catch (error) {
      showToast({
        type: "error",
        message: error instanceof Error ? error.message : "Delete failed.",
      });
    } finally {
      setBusy(false);
    }
  };

  const handleMerge = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!mergeSource || !mergeTarget || mergeSource === mergeTarget) {
      showToast({ type: "error", message: "Pick distinct source and target categories." });
      return;
    }
    if (
      !window.confirm(
        "Merge source into target? All issues in the source category will move to the target."
      )
    ) {
      return;
    }

    setBusy(true);
    try {
      const res = await apiFetch(`${API_BASE}/supervisor/categories/merge`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source_id: mergeSource, target_id: mergeTarget }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(formatApiError(data, "Merge failed"));
      showToast({
        type: "success",
        message: `Merged categories (${data.issues_moved ?? 0} issues moved).`,
      });
      setMergeSource("");
      setMergeTarget("");
      await fetchCategories();
    } catch (error) {
      showToast({
        type: "error",
        message: error instanceof Error ? error.message : "Merge failed.",
      });
    } finally {
      setBusy(false);
    }
  };

  const mergeSourceCat = categories.find((c) => c.id === mergeSource);
  const mergeTargetOptions = categories.filter(
    (cat) =>
      cat.id !== mergeSource &&
      (!mergeSourceCat || cat.caller_type === mergeSourceCat.caller_type)
  );

  const renderGroup = (title: string, items: DbCategory[]) => (
    <section className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-100 bg-gray-50">
        <h2 className="text-sm font-bold text-blue-800 uppercase tracking-wide">
          {title}
        </h2>
        <p className="text-xs text-gray-500 mt-0.5">{items.length} categories</p>
      </div>
      <ul className="divide-y divide-gray-100">
        {items.length === 0 ? (
          <li className="px-4 py-6 text-sm text-gray-500 text-center">No categories</li>
        ) : (
          items.map((cat) => (
            <li key={`${cat.caller_type}-${cat.id}`} className="px-4 py-3">
              {editingId === cat.id ? (
                <div className="flex flex-wrap items-center gap-2">
                  <input
                    type="text"
                    value={editName}
                    onChange={(e) => setEditName(e.target.value)}
                    disabled={busy}
                    className="flex-1 min-w-[12rem] text-sm border border-gray-300 rounded-lg px-3 py-1.5"
                  />
                  <button
                    type="button"
                    onClick={() => void handleRename(cat.id)}
                    disabled={busy}
                    className="text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg disabled:opacity-50"
                  >
                    Save
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setEditingId(null);
                      setEditName("");
                    }}
                    disabled={busy}
                    className="text-xs text-gray-600 px-2 py-1.5"
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <p className="text-sm font-medium text-gray-900">{cat.name}</p>
                    <p className="text-xs text-gray-500 mt-0.5">
                      <span className="font-mono">{cat.id}</span>
                      {" · "}
                      {cat.branch_count} KB branch
                      {cat.branch_count === 1 ? "" : "es"}
                      {cat.is_empty ? " · empty" : ""}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    <button
                      type="button"
                      onClick={() => {
                        setEditingId(cat.id);
                        setEditName(cat.name);
                      }}
                      disabled={busy}
                      className="text-xs border border-gray-300 rounded-lg px-2.5 py-1 hover:bg-gray-50 disabled:opacity-50"
                    >
                      Rename
                    </button>
                    <button
                      type="button"
                      onClick={() => void handleDelete(cat)}
                      disabled={busy || !cat.is_empty}
                      title={
                        cat.is_empty
                          ? "Delete category"
                          : "Only empty categories can be deleted"
                      }
                      className="text-xs border border-red-200 text-red-700 rounded-lg px-2.5 py-1 hover:bg-red-50 disabled:opacity-40"
                    >
                      Delete
                    </button>
                  </div>
                </div>
              )}
            </li>
          ))
        )}
      </ul>
    </section>
  );

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col">
      <header className="sticky top-0 z-40 bg-brand text-gray-900 shadow-md">
        <div className="max-w-4xl mx-auto px-4 py-4 flex items-center justify-between gap-3">
          <div>
            <h1 className="text-lg sm:text-xl font-bold">Category Management</h1>
            <p className="text-sm text-gray-900/80">Helpdesk Copilot · Issue categories</p>
          </div>
          <Link
            href="/supervisor"
            className="text-sm bg-white/80 hover:bg-white border border-gray-300 rounded-lg px-3 py-1.5"
          >
            Supervisor
          </Link>
        </div>
      </header>

      <main className="flex-1 max-w-4xl mx-auto w-full p-4 sm:p-6 space-y-6">
        <form
          onSubmit={(e) => void handleCreate(e)}
          className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm space-y-3"
        >
          <h2 className="text-sm font-bold text-gray-800">Add category</h2>
          <div className="flex flex-wrap gap-3">
            <input
              type="text"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="Category name"
              disabled={busy}
              className="flex-1 min-w-[12rem] text-sm border border-gray-300 rounded-lg px-3 py-2"
            />
            <select
              value={newCallerType}
              onChange={(e) =>
                setNewCallerType(e.target.value as "seller" | "buyer")
              }
              disabled={busy}
              className="text-sm border border-gray-300 rounded-lg px-3 py-2 bg-white capitalize"
            >
              <option value="seller">Seller</option>
              <option value="buyer">Buyer</option>
            </select>
            <button
              type="submit"
              disabled={busy || !newName.trim()}
              className="text-sm bg-blue-600 hover:bg-blue-500 text-white font-semibold px-4 py-2 rounded-lg disabled:opacity-50"
            >
              Create
            </button>
          </div>
        </form>

        {loading ? (
          <p className="text-sm text-gray-500">Loading categories…</p>
        ) : (
          <>
            {renderGroup("Seller", grouped.seller)}
            {renderGroup("Buyer", grouped.buyer)}
          </>
        )}

        <form
          onSubmit={(e) => void handleMerge(e)}
          className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm space-y-3"
        >
          <h2 className="text-sm font-bold text-gray-800">Merge categories</h2>
          <p className="text-xs text-gray-500">
            Move all issues from source to target, then remove the source category.
            Both must belong to the same caller type.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <label className="block text-xs text-gray-600">
              Source (will be deleted)
              <select
                value={mergeSource}
                onChange={(e) => setMergeSource(e.target.value)}
                disabled={busy}
                className="mt-1 w-full text-sm border border-gray-300 rounded-lg px-3 py-2 bg-white"
              >
                <option value="">Select source…</option>
                {categories.map((cat) => (
                  <option key={`src-${cat.caller_type}-${cat.id}`} value={cat.id}>
                    [{cat.caller_type}] {cat.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-xs text-gray-600">
              Target (kept)
              <select
                value={mergeTarget}
                onChange={(e) => setMergeTarget(e.target.value)}
                disabled={busy}
                className="mt-1 w-full text-sm border border-gray-300 rounded-lg px-3 py-2 bg-white"
              >
                <option value="">Select target…</option>
                {mergeTargetOptions.map((cat) => (
                  <option key={`tgt-${cat.caller_type}-${cat.id}`} value={cat.id}>
                    [{cat.caller_type}] {cat.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <button
            type="submit"
            disabled={busy || !mergeSource || !mergeTarget}
            className="text-sm bg-amber-600 hover:bg-amber-500 text-white font-semibold px-4 py-2 rounded-lg disabled:opacity-50"
          >
            Merge
          </button>
        </form>
      </main>

      {toast ? <ToastNotification toast={toast} /> : null}
    </div>
  );
}
