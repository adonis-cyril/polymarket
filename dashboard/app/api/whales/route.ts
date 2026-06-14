import { NextResponse } from "next/server";
import { query } from "@/lib/db";

export async function GET() {
  try {
    const [wallets, trades] = await Promise.all([
      query(
        `SELECT * FROM tracked_wallets
         WHERE is_active = TRUE
         ORDER BY win_rate DESC NULLS LAST
         LIMIT 10`
      ),
      query("SELECT whale_aligned FROM trades ORDER BY timestamp DESC LIMIT 200"),
    ]);
    return NextResponse.json({ wallets, trades });
  } catch (e) {
    const message = e instanceof Error ? e.message : "Query failed";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
