"use client";

import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import type { Trade } from "@/lib/types";

interface AssetStats {
  asset: string;
  trades: number;
  wins: number;
  winRate: number;
  pnl: number;
}

const ASSET_COLORS: Record<string, string> = {
  btc: "bg-orange-400",
  eth: "bg-blue-400",
  sol: "bg-purple-400",
  xrp: "bg-gray-400",
};

export default function AssetBreakdown() {
  const [stats, setStats] = useState<AssetStats[]>([]);

  useEffect(() => {
    async function load() {
      const { data: trades } = await supabase.from("trades").select("asset, result, pnl");
      if (!trades) return;

      const byAsset: Record<string, AssetStats> = {};
      for (const t of trades as Pick<Trade, "asset" | "result" | "pnl">[]) {
        if (!byAsset[t.asset]) {
          byAsset[t.asset] = { asset: t.asset, trades: 0, wins: 0, winRate: 0, pnl: 0 };
        }
        byAsset[t.asset].trades++;
        if (t.result === "WIN") byAsset[t.asset].wins++;
        byAsset[t.asset].pnl += t.pnl ?? 0;
      }

      const result = Object.values(byAsset).map((s) => ({
        ...s,
        winRate: s.trades > 0 ? s.wins / s.trades : 0,
      }));
      result.sort((a, b) => b.pnl - a.pnl);
      setStats(result);
    }

    load();

    const channel = supabase
      .channel("asset_breakdown")
      .on("postgres_changes", { event: "INSERT", schema: "public", table: "trades" }, () => load())
      .subscribe();

    return () => { supabase.removeChannel(channel); };
  }, []);

  const maxPnl = Math.max(...stats.map((s) => Math.abs(s.pnl)), 1);

  return (
    <div className="bg-card-bg border border-card-border rounded-xl p-6">
      <h2 className="text-lg font-semibold mb-4">Asset Breakdown</h2>
      <div className="space-y-3">
        {stats.map((s) => (
          <div key={s.asset} className="flex items-center gap-3">
            <span className="font-mono font-bold w-10 text-sm">
              {s.asset.toUpperCase()}
            </span>
            <div className="flex-1 relative h-6 bg-card-border/30 rounded overflow-hidden">
              <div
                className={`h-full rounded ${ASSET_COLORS[s.asset] ?? "bg-accent"} opacity-60`}
                style={{ width: `${(Math.abs(s.pnl) / maxPnl) * 100}%` }}
              />
            </div>
            <span className="font-mono text-sm w-16 text-right">
              {(s.winRate * 100).toFixed(0)}%
            </span>
            <span
              className={`font-mono text-sm w-20 text-right ${s.pnl >= 0 ? "text-win" : "text-loss"}`}
            >
              {s.pnl >= 0 ? "+" : ""}${s.pnl.toFixed(2)}
            </span>
            <span className="text-muted text-xs w-14 text-right">
              {s.trades} trades
            </span>
          </div>
        ))}
        {stats.length === 0 && (
          <div className="text-muted text-center py-4">No data yet</div>
        )}
      </div>
    </div>
  );
}
