import type { IssueForm as IssueFormState, TopicCategory } from "./types";
import { listToPipe, pipeSplit, resolutionStepsSplit, resolutionStepsToText } from "./utils";
import { FieldLabel } from "./DraftBadge";

const inputClass =
  "brand-supervisor-input mt-1.5 w-full rounded-xl px-3 py-2.5 text-sm text-[#0F172A] disabled:opacity-60";

type IssueFormProps = {
  form: IssueFormState;
  categories: TopicCategory[];
  disabled: boolean;
  draftSource?: string | null;
  templateIssueName?: string | null;
  onChange: (next: IssueFormState) => void;
};

export function IssueForm({
  form,
  categories,
  disabled,
  draftSource,
  templateIssueName,
  onChange,
}: IssueFormProps) {
  const patch = (partial: Partial<IssueFormState>) =>
    onChange({ ...form, ...partial });
  const labelProps = { draftSource, templateIssueName };

  return (
    <div className="space-y-3">
      <label className="block">
        <FieldLabel required {...labelProps}>
          Issue name
        </FieldLabel>
        <input
          type="text"
          value={form.issue_name}
          onChange={(e) => patch({ issue_name: e.target.value })}
          disabled={disabled}
          required
          className={inputClass}
        />
      </label>

      <label className="block">
        <FieldLabel {...labelProps}>Category</FieldLabel>
        <select
          value={form.category}
          onChange={(e) => patch({ category: e.target.value })}
          disabled={disabled}
          className={`${inputClass} bg-white`}
        >
          <option value="">Select category…</option>
          {categories.map((cat) => (
            <option key={cat.id} value={cat.id}>
              {cat.name}
              {cat.branch_count > 0 ? ` (${cat.branch_count})` : ""}
            </option>
          ))}
        </select>
      </label>

      <label className="block">
        <FieldLabel {...labelProps}>Problem statement</FieldLabel>
        <textarea
          value={form.problem_statement}
          onChange={(e) => patch({ problem_statement: e.target.value })}
          disabled={disabled}
          rows={3}
          className={`${inputClass} resize-y`}
        />
      </label>

      <label className="block">
        <FieldLabel {...labelProps}>Policy</FieldLabel>
        <textarea
          value={form.policy}
          onChange={(e) => patch({ policy: e.target.value })}
          disabled={disabled}
          rows={4}
          className={`${inputClass} resize-y`}
        />
      </label>

      <label className="block">
        <FieldLabel {...labelProps}>
          Resolution steps (paragraph or pipe-separated)
        </FieldLabel>
        <textarea
          value={resolutionStepsToText(form.resolution_steps)}
          onChange={(e) =>
            patch({ resolution_steps: resolutionStepsSplit(e.target.value) })
          }
          disabled={disabled}
          rows={5}
          placeholder="Write steps as a paragraph, one per line, or Step 1 | Step 2 | Step 3"
          className={`${inputClass} resize-y`}
        />
        {form.resolution_steps.length > 0 ? (
          <ol className="mt-2 list-decimal list-inside space-y-1 rounded-lg border border-[rgba(15,23,42,0.06)] bg-[#F8F6F1] p-2 text-xs text-[#64748B]">
            {form.resolution_steps.map((step, i) => (
              <li key={`${step}-${i}`}>{step}</li>
            ))}
          </ol>
        ) : null}
      </label>

      <label className="block">
        <FieldLabel {...labelProps}>
          Required documents (pipe-separated)
        </FieldLabel>
        <textarea
          value={listToPipe(form.required_documents)}
          onChange={(e) =>
            patch({ required_documents: pipeSplit(e.target.value) })
          }
          disabled={disabled}
          rows={3}
          placeholder="Document A | Document B"
          className={`${inputClass} resize-y font-mono text-xs`}
        />
        {form.required_documents.length > 0 ? (
          <ul className="mt-2 space-y-1 rounded-lg border border-[rgba(15,23,42,0.06)] bg-[#F8F6F1] p-2 text-xs text-[#64748B]">
            {form.required_documents.map((doc, i) => (
              <li key={`${doc}-${i}`} className="flex items-start gap-2">
                <span className="text-brand-dark">☐</span>
                <span>{doc}</span>
              </li>
            ))}
          </ul>
        ) : null}
      </label>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <label className="block">
          <FieldLabel {...labelProps}>L1 team</FieldLabel>
          <input
            type="text"
            value={form.l1_team}
            onChange={(e) => patch({ l1_team: e.target.value })}
            disabled={disabled}
            className={inputClass}
          />
        </label>
        <label className="block">
          <FieldLabel {...labelProps}>L1 person</FieldLabel>
          <input
            type="text"
            value={form.l1_person}
            onChange={(e) => patch({ l1_person: e.target.value })}
            disabled={disabled}
            className={inputClass}
          />
        </label>
      </div>

      <label className="block">
        <FieldLabel {...labelProps}>
          Trigger keywords (pipe-separated)
        </FieldLabel>
        <textarea
          value={listToPipe(form.trigger_keywords)}
          onChange={(e) =>
            patch({ trigger_keywords: pipeSplit(e.target.value) })
          }
          disabled={disabled}
          rows={2}
          placeholder="keyword1 | keyword2"
          className={`${inputClass} resize-y font-mono text-xs`}
        />
      </label>
    </div>
  );
}
