"use client";

import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import type { BotState, Trade } from "@/lib/types";

interface Stats {
  winRate: string;
  totalTrades: number;
  reversalCount: number;
  kellyAlpha: string;
  brierScore: string;
  bestTrade: string;
  reversalWinRate: string;
  reversalAvgPayout: string;
  whaleAlignment: string;
}

export default function StatsGrid() {
  const [stats, setStats] = useState<Stats | null>(null);

  useEffect(() => {
    async function load() {
      const [{ data: state }, { data: trades }] = await Promise.all([
        supabase.from("bot_state").select("*").eq("id", 1).single(),
        supabase
          .from("trades")
          .select("*")
          .order("pnl", { ascending: false })
          .limit(500),
      ]);

      if (!state || !trades) return;

      const s = state as BotState;
      const allTrades = trades as Trade[];
      const reversals = allTrades.filter((t) => t.trade_type === "REVERSAL");
      const reversalWins = reversals.filter((t) => t.result === "WIN");
      const whaleAligned = allTrades.filter((t) => t.whale_aligned);

      const best = allTrades[0];
      const bestStr = best
        ? `+$${(best.pnl ?? 0).toFixed(2)} (${best.asset.toUpperCase()}, ${best.trade_type})`
        : "N/A";

      const avgPayout =
        reversals.length > 0
          ? reversals.reduce((s, t) => s + (t.payout_ratio ?? 0), 0) /
            reversals.length
          : 0;

      setStats({
        winRate: `${((s.win_rate ?? 0) * 100).toFixed(1)}%`,
        totalTrades: s.total_trades,
        reversalCount: reversals.length,
        kellyAlpha: (s.kelly_alpha ?? 0).toFixed(2),
        brierScore: (s.brier_score ?? 0).toFixed(3),
        bestTrade: bestStr,
        reversalWinRate:
          reversals.length > 0
            ? `${((reversalWins.length / reversals.length) * 100).toFixed(1)}%`
            : "N/A",
        reversalAvgPayout: avgPayout > 0 ? `${avgPayout.toFixed(1)}x` : "N/A",
        whaleAlignment:
          allTrades.length > 0
            ? `${((whaleAligned.length / allTrades.length) * 100).toFixed(0)}%`
            : "N/A",
      });
    }

    load();

    const channel = supabase
      .channel("stats_updates")
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "bot_state" },
        () => load()
      )
      .on(
        "postgres_changes",
        { event: "INSERT", schema: "public", table: "trades" },
        () => load()
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, []);

  if (!stats) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
        {Array.from({ length: 6 }).map((_, i) => (
          <div
            key={i}
            className="bg-card-bg border border-card-border rounded-xl p-4 animate-pulse"
          >
            <div className="h-4 bg-card-border rounded w-20 mb-2" />
            <div className="h-8 bg-card-border rounded w-16" />
          </div>
        ))}
      </div>
    );
  }

  const cards = [
    { label: "Win Rate", value: stats.winRate, sub: "last 50 trades" },
    {
      label: "Total Trades",
      value: stats.totalTrades.toString(),
      sub: `${stats.reversalCount} reversals`,
    },
    {
      label: "Kelly Alpha",
      value: stats.kellyAlpha,
      sub: `Brier: ${stats.brierScore}`,
    },
    { label: "Best Trade", value: stats.bestTrade, sub: "" },
    {
      label: "Reversals",
      value: `${stats.reversalWinRate} win`,
      sub: `Avg payout: ${stats.reversalAvgPayout}`,
    },
    {
      label: "Whale Alignment",
      value: stats.whaleAlignment,
      sub: "trades with whale confirmation",
    },
  ];

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
      {cards.map((card) => (
        <div
          key={card.label}
          className="bg-card-bg border border-card-border rounded-xl p-4"
        >
          <div className="text-xs text-muted uppercase tracking-wide mb-1">
            {card.label}
          </div>
          <div className="text-xl font-mono font-bold">{card.value}</div>
          {card.sub && (
            <div className="text-xs text-muted mt-1">{card.sub}</div>
          )}
        </div>
      ))}
    </div>
  );
}
