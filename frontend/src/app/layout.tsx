import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { LiveIndicator } from "@/components/ui/live-indicator";
import { Sidebar } from "@/components/ui/sidebar";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Nuri-Quant",
  description: "Open-source quant investment platform",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko" className={`${geistSans.variable} ${geistMono.variable} dark h-full antialiased`}>
      <body className="min-h-screen flex bg-zinc-950 text-zinc-100">
        <Sidebar />

        <div className="flex-1 flex flex-col min-h-screen">
          {/* Top Bar */}
          <header className="h-11 border-b border-zinc-800 flex items-center px-6 shrink-0">
            <LiveIndicator />
          </header>

          {/* Page */}
          <main className="flex-1 p-6 overflow-auto">
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}
