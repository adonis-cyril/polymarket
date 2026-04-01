"use client";

import { useEffect, useState } from "react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";
import { supabase } from "@/lib/supabase";
import type { Trade } from "@/lib/types";

const LEVEL_TARGETS = [40, 80, 160, 320, 640, 1280, 2560, 5120, 10240];

interface DataPoint {
  timestamp: string;
  balance: number;
  tradeNum: number;
}

export default function EquityCurve() {
  const [data, setData] = useState<DataPoint[]>([]);

  useEffect(() => {
    async function fetchTrades() {
      const { data: trades } = await supabase
        .from("trades")
        .select("timestamp, balance_after")
        .order("timestamp", { ascending: true });

      if (!trades) return;

      const points: DataPoint[] = [
        { timestamp: "", balance: 20, tradeNum: 0 },
        ...trades.map((t: { timestamp: string; balance_after: number }, i: number) => ({
          timestamp: new Date(t.timestamp).toLocaleDateString("en-US", {
            month: "short",
            day: "numeric",
            hour: "2-digit",
            minute: "2-digit",
          }),
          balance: t.balance_after,
          tradeNum: i + 1,
        })),
      ];
      setData(points);
    }

    fetchTrades();

    const channel = supabase
      .channel("trades_chart")
      .on(
        "postgres_changes",
        { event: "INSERT", schema: "public", table: "trades" },
        (payload) => {
          const t = payload.new as Trade;
          setData((prev) => [
            ...prev,
            {
              timestamp: new Date(t.timestamp).toLocaleDateString("en-US", {
                month: "short",
                day: "numeric",
                hour: "2-digit",
                minute: "2-digit",
              }),
              balance: t.balance_after,
              tradeNum: prev.length,
            },
          ]);
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, []);

  const maxBalance = Math.max(...data.map((d) => d.balance), 100);
  const visibleLevels = LEVEL_TARGETS.filter((t) => t <= maxBalance * 1.5);

  return (
    <div className="bg-card-bg border border-card-border rounded-xl p-6">
      <h2 className="text-lg font-semibold mb-4">Equity Curve</h2>
      <div className="h-72">
        {data.length > 1 ? (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data}>
              <defs>
                <linearGradient id="balanceGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#00a8ff" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#00a8ff" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis
                dataKey="tradeNum"
                tick={{ fill: "#9ca3af", fontSize: 11 }}
                axisLine={{ stroke: "#1f2937" }}
                tickLine={false}
                label={{ value: "Trade #", fill: "#9ca3af", fontSize: 11, position: "insideBottom", offset: -5 }}
              />
              <YAxis
                tick={{ fill: "#9ca3af", fontSize: 11 }}
                axisLine={{ stroke: "#1f2937" }}
                tickLine={false}
                tickFormatter={(v: number) => `$${v}`}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#111827",
                  border: "1px solid #1f2937",
                  borderRadius: 8,
                  color: "#fff",
                  fontSize: 12,
                }}
                formatter={(value) => [`$${Number(value).toFixed(2)}`, "Balance"]}
                labelFormatter={(label) => `Trade #${label}`}
              />
              {visibleLevels.map((target) => (
                <ReferenceLine
                  key={target}
                  y={target}
                  stroke="#1f2937"
                  strokeDasharray="4 4"
                  label={{
                    value: `$${target}`,
                    fill: "#4b5563",
                    fontSize: 10,
                    position: "right",
                  }}
                />
              ))}
              <Area
                type="monotone"
                dataKey="balance"
                stroke="#00a8ff"
                strokeWidth={2}
                fill="url(#balanceGradient)"
              />
            </AreaChart>
          </ResponsiveContainer>
        ) : (
          <div className="h-full flex items-center justify-center text-muted">
            Waiting for trades...
          </div>
        )}
      </div>
    </div>
  );
}
