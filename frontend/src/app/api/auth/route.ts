import { NextResponse } from "next/server";
import { hashToken, timingSafeEqual } from "@/lib/auth-token";
import { isPlainObject, isString, type JsonValue } from "@/lib/types";

const RATE_LIMIT_MAX_ATTEMPTS = 5;

const RATE_LIMIT_WINDOW_MS = 15 * 60 * 1000;

const attemptsByIp = new Map<string, number[]>();

function getClientIp(request: Request): string {
  const forwarded = request.headers.get("x-forwarded-for");

  if (forwarded) {
    const [firstRaw] = forwarded.split(",");
    const first = firstRaw.trim();

    if (first) return first;
  }

  return request.headers.get("x-real-ip")?.trim() || "unknown";
}

function isRateLimited(ip: string, now: number): boolean {
  const cutoff = now - RATE_LIMIT_WINDOW_MS;
  const recent = (attemptsByIp.get(ip) ?? []).filter((ts) => ts > cutoff);

  if (recent.length >= RATE_LIMIT_MAX_ATTEMPTS) {
    attemptsByIp.set(ip, recent);

    return true;
  }

  recent.push(now);
  attemptsByIp.set(ip, recent);

  return false;
}

export async function POST(request: Request) {
  if (isRateLimited(getClientIp(request), Date.now())) {
    return NextResponse.json({ error: "Too many login attempts" }, { status: 429 });
  }

  let body: JsonValue;

  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid request body" }, { status: 400 });
  }

  if (!isPlainObject(body) || !isString(body.password)) {
    return NextResponse.json({ error: "Invalid request body" }, { status: 400 });
  }

  const { password } = body;
  const expected = process.env.DASHBOARD_PASSWORD;

  if (!expected) {
    return NextResponse.json({ error: "Auth not configured" }, { status: 401 });
  }

  // Constant-time password comparison to avoid leaking timing.
  if (!timingSafeEqual(password, expected)) {
    return NextResponse.json({ error: "Invalid password" }, { status: 401 });
  }

  // 쿠키에 HMAC 토큰 저장 (서버 secret으로 키잉, 평문 아님)
  const token = await hashToken(expected);
  const response = NextResponse.json({ ok: true });
  response.cookies.set("nuri-auth", token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "strict",
    maxAge: 60 * 60 * 24 * 7, // 7일
    path: "/",
  });

  return response;
}
