"use client";

import { useEffect, useState } from "react";
import type { TrackedWallet } from "@/lib/types";

const POLL_MS = 8000;

export default function WhaleActivity() {
  const [wallets, setWallets] = useState<TrackedWallet[]>([]);
  const [whaleAlignmentPct, setWhaleAlignmentPct] = useState(0);

  useEffect(() => {
    async function load() {
      const res = await fetch("/api/whales");
      if (!res.ok) return;

      const { wallets: walletsData, trades } = await res.json();
      if (walletsData) setWallets(walletsData);

      if (trades && trades.length > 0) {
        const aligned = trades.filter((t: { whale_aligned: boolean }) => t.whale_aligned).length;
        setWhaleAlignmentPct((aligned / trades.length) * 100);
      }
    }

    load();
    const interval = setInterval(load, POLL_MS);
    return () => clearInterval(interval);
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
                  {((Number(w.win_rate) ?? 0) * 100).toFixed(0)}%
                </span>
                <span
                  className={`font-mono ${(Number(w.total_pnl) ?? 0) >= 0 ? "text-win" : "text-loss"}`}
                >
                  ${(Number(w.total_pnl) ?? 0).toFixed(0)}
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
