"use client";

import { Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import type { StatusBreakdownItem } from "./statsTypes";
import { ChartCard } from "./ChartCard";

const COLORS: Record<string, string> = {
  Pending: "#f59e0b",
  Approved: "#22c55e",
  Rejected: "#ef4444",
};

type Props = { data: StatusBreakdownItem[] };

export function StatusPieChart({ data }: Props) {
  return (
    <ChartCard
      title="Review Status Distribution"
      subtitle="Current lifecycle state of submitted queries"
      empty={data.length === 0}
    >
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={data}
            dataKey="count"
            nameKey="status"
            cx="50%"
            cy="50%"
            innerRadius={55}
            outerRadius={90}
            paddingAngle={2}
          >
            {data.map((entry) => (
              <Cell key={entry.status} fill={COLORS[entry.status] ?? "#94a3b8"} />
            ))}
          </Pie>
          <Tooltip />
          <Legend />
        </PieChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}
