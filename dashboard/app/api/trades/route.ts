import { NextRequest, NextResponse } from "next/server";
import { query } from "@/lib/db";

export async function GET(request: NextRequest) {
  const limit = parseInt(request.nextUrl.searchParams.get("limit") ?? "50", 10);
  const order = request.nextUrl.searchParams.get("order") ?? "desc";
  const direction = order === "asc" ? "ASC" : "DESC";

  try {
    const rows = await query(
      `SELECT * FROM trades ORDER BY timestamp ${direction} LIMIT $1`,
      [Math.min(limit, 500)]
    );
    return NextResponse.json(rows);
  } catch (e) {
    const message = e instanceof Error ? e.message : "Query failed";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
