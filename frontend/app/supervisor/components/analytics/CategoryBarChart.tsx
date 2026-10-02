"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { CategoryCountItem } from "./statsTypes";
import { ChartCard } from "./ChartCard";

type Props = {
  data: CategoryCountItem[];
  title?: string;
  subtitle?: string;
};

export function CategoryBarChart({
  data,
  title = "Top Issue Categories",
  subtitle = "Where most unresolved support queries are coming from",
}: Props) {
  const formatted = [...data].reverse();

  return (
    <ChartCard title={title} subtitle={subtitle} empty={formatted.length === 0}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          layout="vertical"
          data={formatted}
          margin={{ top: 8, right: 16, left: 8, bottom: 0 }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" horizontal={false} />
          <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11 }} />
          <YAxis
            type="category"
            dataKey="category"
            width={120}
            tick={{ fontSize: 10 }}
          />
          <Tooltip />
          <Bar dataKey="count" name="Queries" fill="#6366f1" radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}
