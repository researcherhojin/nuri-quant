import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Basic password protection via environment variable.
 * Set DASHBOARD_PASSWORD in .env.local to enable.
 * If not set, dashboard is public (dev mode).
 */
export function middleware(request: NextRequest) {
  const password = process.env.DASHBOARD_PASSWORD;

  // 비밀번호 미설정 → 인증 없이 통과 (개발 모드)
  if (!password) return NextResponse.next();

  // 쿠키에 인증 토큰 확인
  const authCookie = request.cookies.get("nuri-auth")?.value;
  if (authCookie === password) return NextResponse.next();

  // /api/auth 경로는 통과 (로그인 처리)
  if (request.nextUrl.pathname === "/api/auth") return NextResponse.next();

  // 쿼리 파라미터로 비밀번호 전달 (간이 로그인)
  const urlPassword = request.nextUrl.searchParams.get("password");
  if (urlPassword === password) {
    const response = NextResponse.redirect(new URL("/", request.url));
    response.cookies.set("nuri-auth", password, {
      httpOnly: true,
      maxAge: 60 * 60 * 24 * 7, // 7일
    });
    return response;
  }

  // 미인증 → 401
  return new NextResponse("Unauthorized. Add ?password=YOUR_PASSWORD to URL.", {
    status: 401,
    headers: { "WWW-Authenticate": 'Basic realm="Nuri-Quant"' },
  });
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
