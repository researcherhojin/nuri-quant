import type { Metadata } from "next";
import { Geist_Mono } from "next/font/google";
// Pretendard Variable: 한글 UI 본문 (#1195 U1a) — dynamic subset woff2 를 Next 가 번들
import "pretendard/dist/web/variable/pretendardvariable-dynamic-subset.css";
import "./globals.css";
import { LiveIndicator } from "@/components/ui/live-indicator";
import { Sidebar } from "@/components/ui/sidebar";
import { ThemeProvider } from "next-themes";

const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Nuri-Quant",
  description: "Open-source quant investment platform",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko" className={`${geistMono.variable} h-full antialiased`} suppressHydrationWarning>
      {/* suppressHydrationWarning: 브라우저 확장(ColorZilla 등)이 <body>에 cz-shortcut-listen 같은 속성을 주입해 SSR↔CSR 불일치 경고가 뜸 — 무해하므로 억제 */}
      <body className="min-h-screen flex bg-background text-foreground" suppressHydrationWarning>
        <ThemeProvider attribute="class" defaultTheme="dark" enableSystem={false}>
          <Sidebar />

          <div className="flex-1 flex flex-col min-h-screen">
            {/* Top Bar */}
            <header className="h-11 border-b border-border flex items-center px-6 shrink-0">
              <LiveIndicator />
            </header>

            {/* Page */}
            <main className="flex-1 p-6 overflow-auto">
              {children}
            </main>
          </div>
        </ThemeProvider>
      </body>
    </html>
  );
}
