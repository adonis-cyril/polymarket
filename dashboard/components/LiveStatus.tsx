"use client";

import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import type { BotState } from "@/lib/types";

const STATUS_COLORS: Record<string, string> = {
  RUNNING: "bg-green-500",
  PAUSED: "bg-yellow-500",
  STOPPED: "bg-gray-500",
  BLOWN_UP: "bg-red-500",
};

const STATUS_EMOJI: Record<string, string> = {
  RUNNING: "",
  PAUSED: "",
  STOPPED: "",
  BLOWN_UP: "",
};

export default function LiveStatus() {
  const [state, setState] = useState<BotState | null>(null);
  const [startTime] = useState(Date.now());

  useEffect(() => {
    // Initial fetch
    supabase
      .from("bot_state")
      .select("*")
      .eq("id", 1)
      .single()
      .then(({ data }) => {
        if (data) setState(data as BotState);
      });

    // Real-time subscription
    const channel = supabase
      .channel("bot_state_changes")
      .on(
        "postgres_changes",
        { event: "UPDATE", schema: "public", table: "bot_state" },
        (payload) => {
          setState(payload.new as BotState);
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, []);

  if (!state) {
    return (
      <div className="bg-card-bg border border-card-border rounded-xl p-6 animate-pulse">
        <div className="h-8 bg-card-border rounded w-48 mb-4" />
        <div className="h-16 bg-card-border rounded w-32" />
      </div>
    );
  }

  const status = state.status || "STOPPED";
  const balance = state.current_balance ?? 0;
  const level = state.current_level ?? 1;
  const target = state.level_target ?? 40;
  const phase = state.current_phase ?? 1;

  const phaseLabels: Record<number, string> = {
    1: "Protecting Principal",
    2: "Playing with House Money",
    3: "Scaling Up",
    4: "Full Compound",
  };
  const phaseColors: Record<number, string> = {
    1: "text-yellow-400",
    2: "text-green-400",
    3: "text-accent",
    4: "text-purple-400",
  };

  return (
    <div className="bg-card-bg border border-card-border rounded-xl p-6">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-bold tracking-tight">POLYMARKET BOT</h1>
        <div className="flex items-center gap-2">
          <span
            className={`w-3 h-3 rounded-full ${STATUS_COLORS[status] ?? "bg-gray-500"} ${status === "RUNNING" ? "animate-pulse" : ""}`}
          />
          <span className="text-sm font-mono uppercase">{status}</span>
        </div>
      </div>

      <div className="text-5xl font-mono font-bold text-accent mb-2">
        ${balance.toFixed(2)}
      </div>

      <div className="flex items-center gap-3 text-sm mb-2">
        <span className={`font-mono font-bold ${phaseColors[phase] ?? "text-muted"}`}>
          Phase {phase}: {phaseLabels[phase] ?? "Unknown"}
        </span>
      </div>

      <div className="text-muted text-sm">
        Level {level}: ${target.toFixed(0)} target
        {state.peak_balance && (
          <span className="ml-3">
            Peak: ${state.peak_balance.toFixed(2)}
          </span>
        )}
      </div>
    </div>
  );
}
