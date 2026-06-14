import { NextRequest, NextResponse } from "next/server";
import { query } from "@/lib/db";

export async function GET(request: NextRequest) {
  const auth = request.cookies.get("admin_auth");
  if (!auth || auth.value !== "true") {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  try {
    const rows = await query(
      "SELECT * FROM commands ORDER BY created_at DESC LIMIT 20"
    );
    return NextResponse.json(rows);
  } catch (e) {
    const message = e instanceof Error ? e.message : "Query failed";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

export async function POST(request: NextRequest) {
  const auth = request.cookies.get("admin_auth");
  if (!auth || auth.value !== "true") {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const { command, payload } = await request.json();

  if (command === "PING") {
    return NextResponse.json({ success: true });
  }

  try {
    await query(
      "INSERT INTO commands (command, payload, executed) VALUES ($1, $2, FALSE)",
      [command, payload ?? null]
    );
    return NextResponse.json({ success: true });
  } catch (e) {
    const message = e instanceof Error ? e.message : "Insert failed";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
