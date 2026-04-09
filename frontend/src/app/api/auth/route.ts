import { NextResponse } from "next/server";
import { hashToken, timingSafeEqual } from "@/lib/auth-token";

export async function POST(request: Request) {
  const { password } = await request.json();
  const expected = process.env.DASHBOARD_PASSWORD;

  if (!expected) {
    return NextResponse.json({ error: "Auth not configured" }, { status: 401 });
  }

  // Constant-time password comparison to avoid leaking timing.
  if (!timingSafeEqual(password ?? "", expected)) {
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
