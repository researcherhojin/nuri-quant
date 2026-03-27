import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import Link from "next/link";
import { LiveIndicator } from "@/components/ui/live-indicator";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Nuri-Quant Dashboard",
  description: "Open-source quant investment platform",
};

const NAV_ITEMS = [
  { href: "/", label: "Overview" },
  { href: "/portfolio", label: "Portfolio" },
  { href: "/signals", label: "Signals" },
  { href: "/consensus", label: "Agents" },
  { href: "/scan", label: "Scan" },
  { href: "/strategy", label: "Strategy" },
  { href: "/rebalance", label: "Rebalance" },
  { href: "/engine", label: "Engine" },
  { href: "/report", label: "AI Report" },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko" className={`${geistSans.variable} ${geistMono.variable} dark h-full antialiased`}>
      <body className="min-h-full flex flex-col bg-zinc-950 text-zinc-100">
        <nav className="border-b border-zinc-800 px-4 sm:px-6 py-3 flex items-center gap-3 sm:gap-6 overflow-x-auto">
          <span className="text-lg font-bold text-emerald-400 shrink-0">Nuri-Quant</span>
          {NAV_ITEMS.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="text-xs sm:text-sm text-zinc-400 hover:text-zinc-100 transition-colors whitespace-nowrap"
            >
              {item.label}
            </Link>
          ))}
          <LiveIndicator />
        </nav>
        <main className="max-w-7xl mx-auto px-4 sm:px-6 py-4 sm:py-6 flex-1 w-full">{children}</main>
      </body>
    </html>
  );
}
