"use client";

import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import type { TrackedWallet } from "@/lib/types";

export default function WhaleActivity() {
  const [wallets, setWallets] = useState<TrackedWallet[]>([]);
  const [whaleAlignmentPct, setWhaleAlignmentPct] = useState(0);

  useEffect(() => {
    async function load() {
      const [{ data: walletsData }, { data: trades }] = await Promise.all([
        supabase
          .from("tracked_wallets")
          .select("*")
          .eq("is_active", true)
          .order("win_rate", { ascending: false })
          .limit(10),
        supabase.from("trades").select("whale_aligned").limit(200),
      ]);

      if (walletsData) setWallets(walletsData as TrackedWallet[]);

      if (trades && trades.length > 0) {
        const aligned = trades.filter((t: { whale_aligned: boolean }) => t.whale_aligned).length;
        setWhaleAlignmentPct((aligned / trades.length) * 100);
      }
    }

    load();
  }, []);

  return (
    <div className="bg-card-bg border border-card-border rounded-xl p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold">Whale Tracking</h2>
        <div className="text-sm text-muted">
          {whaleAlignmentPct.toFixed(0)}% alignment
        </div>
      </div>

      {wallets.length > 0 ? (
        <div className="space-y-2">
          {wallets.map((w) => (
            <div
              key={w.id}
              className="flex items-center justify-between py-2 border-b border-card-border/30 last:border-0"
            >
              <div className="flex items-center gap-2">
                <span className="font-mono text-xs text-muted">
                  {w.address.slice(0, 6)}...{w.address.slice(-4)}
                </span>
                {w.alias && (
                  <span className="text-xs text-accent">{w.alias}</span>
                )}
              </div>
              <div className="flex items-center gap-4 text-xs">
                <span className="text-muted">
                  {w.total_trades ?? 0} trades
                </span>
                <span className="font-mono font-bold">
                  {((w.win_rate ?? 0) * 100).toFixed(0)}%
                </span>
                <span
                  className={`font-mono ${(w.total_pnl ?? 0) >= 0 ? "text-win" : "text-loss"}`}
                >
                  ${(w.total_pnl ?? 0).toFixed(0)}
                </span>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-muted text-center py-4 text-sm">
          No tracked wallets yet. The profiler runs daily to discover top performers.
        </div>
      )}
    </div>
  );
}
