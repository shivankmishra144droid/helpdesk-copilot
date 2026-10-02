import type { FunnelItem } from "./statsTypes";
import { ChartCard } from "./ChartCard";

type Props = { data: FunnelItem[] };

export function ResolutionFunnel({ data }: Props) {
  const max = Math.max(...data.map((item) => item.count), 1);

  return (
    <ChartCard
      title="Resolution Funnel"
      subtitle="How agent-submitted queries move through supervisor review"
      empty={data.length === 0 || data.every((item) => item.count === 0)}
    >
      <div className="flex h-full flex-col justify-center gap-3">
        {data.map((item) => {
          const width = Math.max(8, Math.round((item.count / max) * 100));
          return (
            <div key={item.stage}>
              <div className="mb-1 flex items-center justify-between text-xs text-gray-600">
                <span className="font-medium">{item.stage}</span>
                <span>{item.count}</span>
              </div>
              <div className="h-3 w-full rounded-full bg-gray-100">
                <div
                  className="h-3 rounded-full bg-blue-600 transition-all"
                  style={{ width: `${width}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </ChartCard>
  );
}
