import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { hashToken, timingSafeEqual } from "@/lib/auth-token";

/**
 * Dashboard 인증 미들웨어.
 * DASHBOARD_PASSWORD 설정 시 활성화, 미설정 시 공개 (개발 모드).
 * 쿠키에는 HMAC-SHA256 토큰 저장 (서버 secret으로 키잉).
 */
export async function middleware(request: NextRequest) {
  const password = process.env.DASHBOARD_PASSWORD;

  // 비밀번호 미설정 → 인증 없이 통과
  if (!password) return NextResponse.next();

  // 로그인 페이지 + auth API는 통과
  const { pathname } = request.nextUrl;
  if (pathname === "/login" || pathname === "/api/auth") {
    return NextResponse.next();
  }

  // 쿠키의 토큰과 기대 토큰을 timing-safe로 비교
  const authCookie = request.cookies.get("nuri-auth")?.value;
  if (authCookie && timingSafeEqual(authCookie, await hashToken(password))) {
    return NextResponse.next();
  }

  // 미인증 → 로그인 페이지로 리다이렉트
  return NextResponse.redirect(new URL("/login", request.url));
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
