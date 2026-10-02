"use client";

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { KbGrowthItem } from "./statsTypes";
import { ChartCard } from "./ChartCard";

type Props = { data: KbGrowthItem[] };

export function KbGrowthChart({ data }: Props) {
  const formatted = data.map((row) => ({
    ...row,
    label: row.date.slice(5),
  }));

  return (
    <ChartCard
      title="Knowledge Base Growth"
      subtitle="Approved supervisor resolutions converted into reusable KB entries"
      empty={formatted.length === 0}
    >
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={formatted} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
          <XAxis dataKey="label" tick={{ fontSize: 11 }} />
          <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
          <Tooltip />
          <Legend />
          <Line
            type="monotone"
            dataKey="kb_size"
            name="KB size"
            stroke="#0ea5e9"
            strokeWidth={2}
            dot={{ r: 3 }}
          />
          <Line
            type="monotone"
            dataKey="added"
            name="Added per day"
            stroke="#8b5cf6"
            strokeWidth={2}
            dot={{ r: 3 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}
