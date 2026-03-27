import { NextResponse } from "next/server";

export async function POST(request: Request) {
  const { password } = await request.json();
  const expected = process.env.DASHBOARD_PASSWORD;

  if (!expected || password !== expected) {
    return NextResponse.json({ error: "Invalid password" }, { status: 401 });
  }

  const response = NextResponse.json({ ok: true });
  response.cookies.set("nuri-auth", expected, {
    httpOnly: true,
    maxAge: 60 * 60 * 24 * 7, // 7일
    path: "/",
  });
  return response;
}
