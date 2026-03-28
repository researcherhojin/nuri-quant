import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { LiveIndicator } from "@/components/ui/live-indicator";
import { Sidebar } from "@/components/ui/sidebar";
import { ThemeProvider } from "next-themes";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Nuri-Quant",
  description: "Open-source quant investment platform",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`} suppressHydrationWarning>
      <body className="min-h-screen flex bg-background text-foreground">
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
