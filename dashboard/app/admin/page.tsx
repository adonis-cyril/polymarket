"use client";

import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import type { BotState } from "@/lib/types";

export default function AdminPanel() {
  const [authenticated, setAuthenticated] = useState(false);
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [state, setState] = useState<BotState | null>(null);
  const [commands, setCommands] = useState<
    { id: number; command: string; executed: boolean; created_at: string }[]
  >([]);
  const [sending, setSending] = useState(false);

  // Check if already authenticated
  useEffect(() => {
    fetch("/api/commands", { method: "POST", body: JSON.stringify({ command: "PING" }) })
      .then((r) => {
        if (r.ok) setAuthenticated(true);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!authenticated) return;

    supabase
      .from("bot_state")
      .select("*")
      .eq("id", 1)
      .single()
      .then(({ data }) => {
        if (data) setState(data as BotState);
      });

    supabase
      .from("commands")
      .select("*")
      .order("created_at", { ascending: false })
      .limit(20)
      .then(({ data }) => {
        if (data) setCommands(data);
      });

    const channel = supabase
      .channel("admin_state")
      .on(
        "postgres_changes",
        { event: "UPDATE", schema: "public", table: "bot_state" },
        (payload) => setState(payload.new as BotState)
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [authenticated]);

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault();
    setError("");

    const res = await fetch("/api/auth", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });

    if (res.ok) {
      setAuthenticated(true);
    } else {
      setError("Invalid password");
    }
  }

  async function sendCommand(command: string, payload?: object) {
    setSending(true);
    try {
      await fetch("/api/commands", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command, payload }),
      });
      // Refresh commands list
      const { data } = await supabase
        .from("commands")
        .select("*")
        .order("created_at", { ascending: false })
        .limit(20);
      if (data) setCommands(data);
    } catch {
      // ignore
    }
    setSending(false);
  }

  if (!authenticated) {
    return (
      <main className="max-w-md mx-auto px-4 py-20">
        <div className="bg-card-bg border border-card-border rounded-xl p-8">
          <h1 className="text-xl font-bold mb-6">Admin Login</h1>
          <form onSubmit={handleLogin}>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Password"
              className="w-full bg-background border border-card-border rounded-lg px-4 py-2 mb-4 focus:outline-none focus:border-accent"
            />
            {error && <p className="text-loss text-sm mb-4">{error}</p>}
            <button
              type="submit"
              className="w-full bg-accent text-black font-bold py-2 rounded-lg hover:bg-accent-dim transition-colors"
            >
              Login
            </button>
          </form>
        </div>
      </main>
    );
  }

  const drawdown =
    state && state.peak_balance && state.peak_balance > 0
      ? ((state.peak_balance - (state.current_balance ?? 0)) /
          state.peak_balance) *
        100
      : 0;

  return (
    <main className="max-w-4xl mx-auto px-4 py-8 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Admin Panel</h1>
        <a href="/" className="text-accent text-sm hover:underline">
          Back to Dashboard
        </a>
      </div>

      {/* Controls */}
      <div className="bg-card-bg border border-card-border rounded-xl p-6">
        <h2 className="text-lg font-semibold mb-4">Bot Controls</h2>
        <div className="flex flex-wrap gap-3">
          <button
            onClick={() => sendCommand("PAUSE")}
            disabled={sending}
            className="px-4 py-2 bg-yellow-600 text-white rounded-lg hover:bg-yellow-700 disabled:opacity-50 font-medium"
          >
            Pause
          </button>
          <button
            onClick={() => sendCommand("RESUME")}
            disabled={sending}
            className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 font-medium"
          >
            Resume
          </button>
          <button
            onClick={() => sendCommand("FORCE_SKIP")}
            disabled={sending}
            className="px-4 py-2 bg-card-border text-white rounded-lg hover:bg-gray-600 disabled:opacity-50 font-medium"
          >
            Force Skip
          </button>
          <button
            onClick={() => sendCommand("FORCE_CLAIM")}
            disabled={sending}
            className="px-4 py-2 bg-card-border text-white rounded-lg hover:bg-gray-600 disabled:opacity-50 font-medium"
          >
            Force Claim
          </button>
        </div>
      </div>

      {/* Live State */}
      {state && (
        <div className="bg-card-bg border border-card-border rounded-xl p-6">
          <h2 className="text-lg font-semibold mb-4">Live State</h2>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4 text-sm">
            <div>
              <span className="text-muted">Status</span>
              <div className="font-mono font-bold">{state.status}</div>
            </div>
            <div>
              <span className="text-muted">Balance</span>
              <div className="font-mono font-bold">
                ${(state.current_balance ?? 0).toFixed(2)}
              </div>
            </div>
            <div>
              <span className="text-muted">Peak</span>
              <div className="font-mono font-bold">
                ${(state.peak_balance ?? 0).toFixed(2)}
              </div>
            </div>
            <div>
              <span className="text-muted">Drawdown</span>
              <div
                className={`font-mono font-bold ${drawdown > 20 ? "text-loss" : ""}`}
              >
                {drawdown.toFixed(1)}%
              </div>
            </div>
            <div>
              <span className="text-muted">Consecutive Losses</span>
              <div
                className={`font-mono font-bold ${state.consecutive_losses >= 4 ? "text-loss" : ""}`}
              >
                {state.consecutive_losses}
              </div>
            </div>
            <div>
              <span className="text-muted">Today Start</span>
              <div className="font-mono font-bold">
                ${(state.today_starting_balance ?? 0).toFixed(2)}
              </div>
            </div>
            <div>
              <span className="text-muted">Win Rate</span>
              <div className="font-mono font-bold">
                {((state.win_rate ?? 0) * 100).toFixed(1)}%
              </div>
            </div>
            <div>
              <span className="text-muted">Brier Score</span>
              <div className="font-mono font-bold">
                {(state.brier_score ?? 0).toFixed(4)}
              </div>
            </div>
            <div>
              <span className="text-muted">Regime</span>
              <div className="font-mono font-bold">
                {state.current_regime ?? "N/A"}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Command History */}
      <div className="bg-card-bg border border-card-border rounded-xl p-6">
        <h2 className="text-lg font-semibold mb-4">Command History</h2>
        <div className="space-y-2">
          {commands.map((cmd) => (
            <div
              key={cmd.id}
              className="flex items-center justify-between py-2 border-b border-card-border/30 last:border-0 text-sm"
            >
              <span className="font-mono">{cmd.command}</span>
              <div className="flex items-center gap-3 text-muted text-xs">
                <span>
                  {cmd.executed ? (
                    <span className="text-win">executed</span>
                  ) : (
                    <span className="text-yellow-400">pending</span>
                  )}
                </span>
                <span>
                  {new Date(cmd.created_at).toLocaleString()}
                </span>
              </div>
            </div>
          ))}
          {commands.length === 0 && (
            <div className="text-muted text-center py-4">No commands yet</div>
          )}
        </div>
      </div>
    </main>
  );
}
