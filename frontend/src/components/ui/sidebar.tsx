"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

// 팔란티어 스타일 그룹 네비게이션
const NAV_GROUPS = [
  {
    label: "OVERVIEW",
    items: [
      { href: "/", label: "Dashboard", icon: "◈" },
    ],
  },
  {
    label: "ANALYSIS",
    items: [
      { href: "/portfolio", label: "Portfolio", icon: "◇" },
      { href: "/signals", label: "Signals", icon: "◆" },
      { href: "/consensus", label: "Agents", icon: "◎" },
      { href: "/scan", label: "Scanner", icon: "⊕" },
    ],
  },
  {
    label: "TRADING",
    items: [
      { href: "/targets", label: "Price Targets", icon: "◉" },
      { href: "/advisor", label: "Advisor", icon: "⊘" },
      { href: "/strategy", label: "Strategy", icon: "▦" },
      { href: "/rebalance", label: "Rebalance", icon: "⊞" },
    ],
  },
  {
    label: "SYSTEM",
    items: [
      { href: "/engine", label: "SIEGE Engine", icon: "⊙" },
      { href: "/evidence", label: "Evidence", icon: "◫" },
      { href: "/report", label: "AI Report", icon: "◧" },
    ],
  },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="fixed left-0 top-0 h-screen w-56 bg-zinc-900 border-r border-zinc-800 flex flex-col z-50">
      {/* Logo */}
      <Link href="/" className="h-12 flex items-center px-5 border-b border-zinc-800 hover:bg-zinc-800/50 transition-colors">
        <span className="text-lg font-bold text-emerald-400 tracking-tight">Nuri-Quant</span>
        <span className="text-[9px] text-zinc-600 ml-2 font-mono">v0.1</span>
      </Link>

      {/* Navigation Groups */}
      <nav className="flex-1 overflow-y-auto py-3">
        {NAV_GROUPS.map((group) => (
          <div key={group.label} className="mb-4">
            <p className="px-5 text-[10px] font-semibold text-zinc-600 tracking-widest mb-1.5">
              {group.label}
            </p>
            {group.items.map((item) => {
              const active = pathname === item.href;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`
                    flex items-center gap-2.5 px-5 py-1.5 text-sm transition-colors
                    ${active
                      ? "text-emerald-400 bg-emerald-400/10 border-r-2 border-emerald-400"
                      : "text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800/50"
                    }
                  `}
                >
                  <span className="text-xs opacity-50 w-4 text-center">{item.icon}</span>
                  {item.label}
                </Link>
              );
            })}
          </div>
        ))}
      </nav>

      {/* Bottom Status */}
      <div className="border-t border-zinc-800 px-5 py-3">
        <div className="flex items-center gap-2">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
            <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
          </span>
          <span className="text-[10px] text-zinc-500">System Online</span>
        </div>
      </div>
    </aside>
  );
}
