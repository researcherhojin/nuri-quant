import { NextResponse } from "next/server";
import crypto from "crypto";

/** 비밀번호를 SHA256 해시 토큰으로 변환 (쿠키에 평문 저장 방지). */
function hashToken(password: string): string {
  return crypto.createHash("sha256").update(password).digest("hex");
}

export async function POST(request: Request) {
  const { password } = await request.json();
  const expected = process.env.DASHBOARD_PASSWORD;

  if (!expected || password !== expected) {
    return NextResponse.json({ error: "Invalid password" }, { status: 401 });
  }

  // 쿠키에 해시 토큰 저장 (평문 아님)
  const token = hashToken(expected);
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
