"use client";

import { useEffect, useState } from "react";
import type { BotState } from "@/lib/types";

const REGIME_CONFIG: Record<string, { color: string; label: string; action: string }> = {
  LOW_VOL: { color: "bg-green-500", label: "Low Volatility", action: "Active (early entry)" },
  MEDIUM_VOL: { color: "bg-blue-500", label: "Medium Volatility", action: "Active (standard)" },
  TRENDING_VOL: { color: "bg-yellow-500", label: "Trending", action: "Active (late snipe)" },
  HIGH_VOL: { color: "bg-red-500", label: "High Volatility", action: "Skipping" },
  UNKNOWN: { color: "bg-gray-500", label: "Unknown", action: "Initializing..." },
};

const POLL_MS = 4000;

export default function RegimeIndicator() {
  const [regime, setRegime] = useState("UNKNOWN");
  const [status, setStatus] = useState("STOPPED");

  useEffect(() => {
    async function load() {
      const res = await fetch("/api/bot-state");
      if (!res.ok) return;
      const data = (await res.json()) as BotState;
      if (data) {
        setRegime(data.current_regime ?? "UNKNOWN");
        setStatus(data.status ?? "STOPPED");
      }
    }

    load();
    const interval = setInterval(load, POLL_MS);
    return () => clearInterval(interval);
  }, []);

  const config = REGIME_CONFIG[regime] ?? REGIME_CONFIG.UNKNOWN;
  const isActive = status === "RUNNING" && regime !== "HIGH_VOL";

  return (
    <div className="bg-card-bg border border-card-border rounded-xl p-6">
      <h2 className="text-lg font-semibold mb-3">Market Regime</h2>
      <div className="flex items-center gap-3">
        <span className={`w-4 h-4 rounded-full ${config.color} ${isActive ? "animate-pulse" : ""}`} />
        <div>
          <div className="font-mono font-bold">{config.label}</div>
          <div className="text-xs text-muted">{config.action}</div>
        </div>
      </div>
    </div>
  );
}
