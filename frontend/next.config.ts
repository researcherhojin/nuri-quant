import type { NextConfig } from "next";

/**
 * Dev-only cross-origin allowlist for Next.js dev assets (HMR, webpack chunks).
 *
 * Defaults cover RFC1918 private-network ranges so devs can open the dashboard
 * on their LAN (e.g. a phone on the same Wi-Fi) without extra config. These
 * wildcards never identify a specific machine — they describe generic
 * private-network subnets.
 *
 * Override or extend via env:
 *   NURI_DEV_ALLOWED_ORIGINS=my-laptop.local,203.0.113.42
 *
 * Production (`next build`) ignores this setting entirely.
 */
const DEFAULT_DEV_ORIGINS = [
  "*.local",        // Bonjour / mDNS hostnames (macOS Network)
  "192.168.*.*",   // Home Wi-Fi / 홈 공유기 (Class C private)
  "10.*.*.*",      // Enterprise / Docker bridge (Class A private)
  "172.16.*.*",    // Docker default (Class B private, lower range)
  "172.17.*.*",
  "172.18.*.*",
  "172.19.*.*",
  "172.20.*.*",
  "172.21.*.*",
  "172.22.*.*",
  "172.23.*.*",
  "172.24.*.*",
  "172.25.*.*",
  "172.26.*.*",
  "172.27.*.*",
  "172.28.*.*",
  "172.29.*.*",
  "172.30.*.*",
  "172.31.*.*",
];

const extraDevOrigins = (process.env.NURI_DEV_ALLOWED_ORIGINS || "")
  .split(",")
  .map((s) => s.trim())
  .filter(Boolean);

const devAllowedOrigins = [...DEFAULT_DEV_ORIGINS, ...extraDevOrigins];

const API_BACKEND = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

const nextConfig: NextConfig = {
  // #214 polish: allow Next.js dev resources (HMR WebSocket, static chunks) from
  // common private-network subnets. No personal or hard-coded host addresses.
  allowedDevOrigins: devAllowedOrigins,
  // Proxy /api/* to backend — client-side fetch uses relative URLs,
  // Next.js handles the forwarding. Eliminates CORS/CSP issues for
  // network access (Mac mini → MBP dev server).
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${API_BACKEND}/api/:path*`,
      },
    ];
  },
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          {
            key: "Strict-Transport-Security",
            value: "max-age=31536000; includeSubDomains",
          },
          {
            key: "X-Content-Type-Options",
            value: "nosniff",
          },
          {
            // SAMEORIGIN: /evidence 페이지가 /api/evidence/{chart_id} 를 iframe 으로 embed
            // (Plotly 차트 HTML). DENY 로 두면 same-origin embed 까지 차단되어 Playwright
            // 검증에서 5 X-Frame-Options 위반이 보였음. SAMEORIGIN 은 same-origin iframe 만
            // 허용 + cross-origin clickjacking 은 여전히 차단 — CSP `frame-ancestors 'self'`
            // 와 일관.
            key: "X-Frame-Options",
            value: "SAMEORIGIN",
          },
          {
            key: "X-XSS-Protection",
            value: "1; mode=block",
          },
          {
            key: "Referrer-Policy",
            value: "strict-origin-when-cross-origin",
          },
          {
            key: "Content-Security-Policy",
            value: [
              "default-src 'self'",
              "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
              "style-src 'self' 'unsafe-inline'",
              "img-src 'self' data: blob:",
              "font-src 'self' data:",
              `connect-src 'self' ${API_BACKEND} ws://localhost:3000 ws://${API_BACKEND.replace("http://", "")}`,
              `frame-src 'self' ${API_BACKEND}`,
              // 'self' 허용: /evidence 페이지가 /api/evidence/{chart_id} 를 iframe 으로
              // embed (Plotly HTML). 'none' 으로 두면 X-Frame-Options SAMEORIGIN 보다
              // CSP 가 우선이라 여전히 blocked. cross-origin clickjacking 은 여전히 차단.
              "frame-ancestors 'self'",
            ].join("; "),
          },
        ],
      },
    ];
  },
};

export default nextConfig;
