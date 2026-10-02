import { BotIcon, PhoneHangupIcon } from "./icons";
import type { CallerType, TopicCategory } from "./types";

export function AgentAvatar({ callerType }: { callerType?: CallerType | null }) {
  const isBuyer = callerType === "buyer";
  return (
    <div
      className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-white shadow-md ${
        isBuyer
          ? "bg-gradient-to-br from-indigo-600 to-blue-600 shadow-indigo-500/20"
          : "bg-gradient-to-br from-[#2563EB] to-[#1D4ED8] shadow-blue-500/20"
      }`}
    >
      <BotIcon className="h-4 w-4" />
    </div>
  );
}

export function CategoryGrid({
  categories,
  onSelect,
  disabled,
  callerType,
}: {
  categories: TopicCategory[];
  onSelect: (category: TopicCategory) => void;
  disabled?: boolean;
  callerType?: CallerType | null;
}) {
  const isBuyer = callerType === "buyer";
  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
      {categories.map((category) => (
        <button
          key={category.id}
          type="button"
          onClick={() => onSelect(category)}
          disabled={disabled}
          className={`group rounded-2xl border border-[#E5EAF2] bg-white px-4 py-3 text-left shadow-sm transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md disabled:cursor-not-allowed disabled:opacity-50 ${
            isBuyer
              ? "hover:border-indigo-300 hover:bg-indigo-50/60"
              : "hover:border-[#2563EB]/40 hover:bg-[#EFF6FF]"
          }`}
        >
          <span className="block text-sm font-semibold text-[#0F172A] leading-snug">
            {category.name}
          </span>
          {category.branch_count > 0 ? (
            <span
              className={`mt-1 inline-block text-xs font-medium ${
                isBuyer ? "text-indigo-600" : "text-[#2563EB]"
              }`}
            >
              {category.branch_count} issue
              {category.branch_count !== 1 ? "s" : ""}
            </span>
          ) : null}
        </button>
      ))}
    </div>
  );
}

export function PathBreadcrumb({ path }: { path: string[] }) {
  if (!path.length) return null;

  return (
    <div className="mb-4 flex flex-wrap items-center gap-1 rounded-2xl border border-[#E5EAF2] bg-white/80 px-4 py-2.5 text-xs shadow-sm">
      {path.map((segment, index) => (
        <span key={`${segment}-${index}`} className="flex items-center gap-1">
          {index > 0 && <span className="text-[#94A3B8]">›</span>}
          <span
            className={
              index === path.length - 1
                ? "font-semibold text-[#0F172A]"
                : "text-[#64748B]"
            }
          >
            {segment}
          </span>
        </span>
      ))}
    </div>
  );
}

export function TypingIndicator() {
  return (
    <div className="flex items-center gap-1 py-1">
      <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce [animation-delay:0ms]" />
      <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce [animation-delay:150ms]" />
      <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce [animation-delay:300ms]" />
    </div>
  );
}

export function NewCallButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex items-center gap-2 rounded-xl border border-red-200 bg-white px-3 py-2 text-sm font-semibold text-red-600 shadow-sm transition hover:border-red-300 hover:bg-red-50 hover:shadow-md"
      title="End call and start new"
    >
      <PhoneHangupIcon className="h-4 w-4" />
      <span>New Call</span>
    </button>
  );
}
