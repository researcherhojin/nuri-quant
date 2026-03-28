import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Dashboard 인증 미들웨어.
 * DASHBOARD_PASSWORD 설정 시 활성화, 미설정 시 공개 (개발 모드).
 * 쿠키에는 SHA256 해시 토큰 저장 (평문 비교 아님).
 */
export function middleware(request: NextRequest) {
  const password = process.env.DASHBOARD_PASSWORD;

  // 비밀번호 미설정 → 인증 없이 통과
  if (!password) return NextResponse.next();

  // 로그인 페이지 + auth API는 통과
  const { pathname } = request.nextUrl;
  if (pathname === "/login" || pathname === "/api/auth") {
    return NextResponse.next();
  }

  // 쿠키의 해시 토큰과 비밀번호의 해시를 비교
  const authCookie = request.cookies.get("nuri-auth")?.value;
  if (authCookie && authCookie === hashToken(password)) {
    return NextResponse.next();
  }

  // 미인증 → 로그인 페이지로 리다이렉트
  return NextResponse.redirect(new URL("/login", request.url));
}

/** SHA256 해시 (Edge Runtime 호환). */
function hashToken(password: string): string {
  // Edge Runtime에서는 crypto.subtle 사용 불가 → 간단한 해시
  // middleware는 Node.js runtime에서 실행되므로 crypto 사용 가능
  const crypto = require("crypto");
  return crypto.createHash("sha256").update(password).digest("hex");
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
