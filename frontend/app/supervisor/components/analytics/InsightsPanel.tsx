import type { TopRepeatedQuery } from "./statsTypes";

type Props = {
  insights: string[];
  topQueries: TopRepeatedQuery[];
};

export function InsightsPanel({ insights, topQueries }: Props) {
  return (
    <div className="brand-supervisor-stat-card h-full p-5">
      <div className="border-b border-[rgba(15,23,42,0.06)] pb-3">
        <h3 className="text-sm font-bold tracking-tight text-[#0F172A]">Key Insights</h3>
        <p className="mt-1 text-xs tracking-wide text-[#64748B]">
          Automated takeaways from supervisor review activity
        </p>
      </div>
      {insights.length === 0 ? (
        <p className="mt-6 text-sm text-[#64748B]">
          No insights yet. Analytics will populate as agents submit queries.
        </p>
      ) : (
        <ol className="mt-4 list-decimal space-y-2 pl-4 text-sm text-[#0F172A]">
          {insights.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ol>
      )}
      {topQueries.length > 0 ? (
        <div className="mt-6 border-t border-[rgba(15,23,42,0.06)] pt-4">
          <p className="brand-supervisor-label">
            Top repeated queries
          </p>
          <ul className="mt-2 space-y-2">
            {topQueries.slice(0, 5).map((item) => (
              <li
                key={item.query}
                className="rounded-lg border border-[rgba(15,23,42,0.06)] bg-[#F8F6F1] px-3 py-2 text-xs text-[#0F172A]"
              >
                <span className="font-medium">{item.query}</span>
                <span className="mt-0.5 block text-[#64748B]">
                  {item.count}× · {item.category}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
