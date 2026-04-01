"use client";

import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import type { Level, BotState } from "@/lib/types";

const TARGETS = [40, 80, 160, 320, 640, 1280, 2560, 5120, 10240];

export default function LevelTracker() {
  const [levels, setLevels] = useState<Level[]>([]);
  const [currentBalance, setCurrentBalance] = useState(20);
  const [currentLevel, setCurrentLevel] = useState(1);

  useEffect(() => {
    supabase
      .from("levels")
      .select("*")
      .order("level", { ascending: true })
      .then(({ data }) => {
        if (data) setLevels(data as Level[]);
      });

    supabase
      .from("bot_state")
      .select("current_balance, current_level")
      .eq("id", 1)
      .single()
      .then(({ data }) => {
        if (data) {
          setCurrentBalance(data.current_balance ?? 20);
          setCurrentLevel(data.current_level ?? 1);
        }
      });

    const channel = supabase
      .channel("level_tracker")
      .on(
        "postgres_changes",
        { event: "UPDATE", schema: "public", table: "bot_state" },
        (payload) => {
          const s = payload.new as BotState;
          setCurrentBalance(s.current_balance ?? 20);
          setCurrentLevel(s.current_level ?? 1);
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, []);

  return (
    <div className="bg-card-bg border border-card-border rounded-xl p-6">
      <h2 className="text-lg font-semibold mb-4">Level Progress</h2>
      <div className="flex gap-1">
        {TARGETS.map((target, i) => {
          const levelNum = i + 1;
          const reached = levels.find(
            (l) => l.level === levelNum && l.reached_at
          );
          const isCurrent = levelNum === currentLevel;
          const isPast = levelNum < currentLevel;

          let progressPct = 0;
          if (isCurrent && levelNum > 1) {
            const prevTarget = TARGETS[i - 1] || 20;
            progressPct = Math.min(
              100,
              ((currentBalance - prevTarget) / (target - prevTarget)) * 100
            );
          } else if (isCurrent && levelNum === 1) {
            progressPct = Math.min(100, ((currentBalance - 20) / (target - 20)) * 100);
          }

          return (
            <div key={target} className="flex-1 min-w-0">
              <div
                className={`h-3 rounded-full relative overflow-hidden ${
                  isPast || reached
                    ? "bg-accent"
                    : isCurrent
                      ? "bg-card-border"
                      : "bg-card-border/50"
                }`}
              >
                {isCurrent && (
                  <div
                    className="h-full bg-accent rounded-full transition-all duration-500 animate-pulse"
                    style={{ width: `${Math.max(progressPct, 5)}%` }}
                  />
                )}
              </div>
              <div
                className={`text-xs mt-1 text-center font-mono ${
                  isPast || reached
                    ? "text-accent"
                    : isCurrent
                      ? "text-white"
                      : "text-muted/50"
                }`}
              >
                ${target >= 1000 ? `${(target / 1000).toFixed(1)}k` : target}
              </div>
              {reached && (
                <div className="text-[9px] text-muted text-center">
                  {reached.time_elapsed_hours
                    ? `${reached.time_elapsed_hours.toFixed(0)}h`
                    : ""}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
