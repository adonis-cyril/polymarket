"use client";

import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import type { Trade } from "@/lib/types";

const ASSET_COLORS: Record<string, string> = {
  btc: "text-orange-400",
  eth: "text-blue-400",
  sol: "text-purple-400",
  xrp: "text-gray-300",
};

export default function RecentTrades() {
  const [trades, setTrades] = useState<Trade[]>([]);

  useEffect(() => {
    supabase
      .from("trades")
      .select("*")
      .order("timestamp", { ascending: false })
      .limit(50)
      .then(({ data }) => {
        if (data) setTrades(data as Trade[]);
      });

    const channel = supabase
      .channel("recent_trades")
      .on(
        "postgres_changes",
        { event: "INSERT", schema: "public", table: "trades" },
        (payload) => {
          setTrades((prev) => [payload.new as Trade, ...prev].slice(0, 50));
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, []);

  return (
    <div className="bg-card-bg border border-card-border rounded-xl p-6">
      <h2 className="text-lg font-semibold mb-4">Recent Trades</h2>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-muted text-xs uppercase border-b border-card-border">
              <th className="text-left py-2 pr-3">Time</th>
              <th className="text-left py-2 pr-3">Asset</th>
              <th className="text-left py-2 pr-3">Dir</th>
              <th className="text-right py-2 pr-3">Price</th>
              <th className="text-right py-2 pr-3">Bet</th>
              <th className="text-center py-2 pr-3">Result</th>
              <th className="text-right py-2 pr-3">P&L</th>
              <th className="text-right py-2">Balance</th>
            </tr>
          </thead>
          <tbody>
            {trades.map((trade) => (
              <tr
                key={trade.id}
                className="border-b border-card-border/50 hover:bg-card-border/20 transition-colors"
              >
                <td className="py-2 pr-3 font-mono text-xs text-muted">
                  {new Date(trade.timestamp).toLocaleTimeString("en-US", {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </td>
                <td className="py-2 pr-3">
                  <span
                    className={`font-mono font-bold ${ASSET_COLORS[trade.asset] ?? "text-white"}`}
                  >
                    {trade.asset.toUpperCase()}
                  </span>
                </td>
                <td className="py-2 pr-3">
                  <span
                    className={`font-mono text-xs px-1.5 py-0.5 rounded ${
                      trade.direction === "UP"
                        ? "bg-green-900/30 text-green-400"
                        : "bg-red-900/30 text-red-400"
                    }`}
                  >
                    {trade.direction}
                  </span>
                </td>
                <td className="py-2 pr-3 text-right font-mono">
                  ${trade.token_price.toFixed(2)}
                </td>
                <td className="py-2 pr-3 text-right font-mono">
                  ${trade.bet_size.toFixed(2)}
                </td>
                <td className="py-2 pr-3 text-center">
                  <div className="flex items-center justify-center gap-1">
                    <span
                      className={
                        trade.result === "WIN" ? "text-win" : "text-loss"
                      }
                    >
                      {trade.result === "WIN" ? "\u2713" : "\u2717"}
                    </span>
                    {trade.trade_type === "REVERSAL" && (
                      <span className="text-[10px] bg-orange-900/30 text-orange-400 px-1 rounded">
                        REV
                      </span>
                    )}
                    {trade.whale_aligned && (
                      <span className="text-[10px] bg-blue-900/30 text-blue-400 px-1 rounded">
                        WHALE
                      </span>
                    )}
                  </div>
                </td>
                <td
                  className={`py-2 pr-3 text-right font-mono ${
                    (trade.pnl ?? 0) >= 0 ? "text-win" : "text-loss"
                  }`}
                >
                  {(trade.pnl ?? 0) >= 0 ? "+" : ""}$
                  {Math.abs(trade.pnl ?? 0).toFixed(2)}
                </td>
                <td className="py-2 text-right font-mono">
                  ${trade.balance_after.toFixed(2)}
                </td>
              </tr>
            ))}
            {trades.length === 0 && (
              <tr>
                <td colSpan={8} className="py-8 text-center text-muted">
                  No trades yet
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
