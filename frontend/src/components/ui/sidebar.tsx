"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, useEffect } from "react";
import {
  LayoutDashboard,
  Briefcase,
  BarChart3,
  Users,
  Search,
  Target,
  ShieldAlert,
  TrendingUp,
  Scale,
  Cog,
  FileBarChart,
  Bot,
  ChevronLeft,
  ChevronRight,
  ShieldCheck,
  ShieldX,
} from "lucide-react";

// 팔란티어 스타일 그룹 네비게이션
const NAV_GROUPS = [
  {
    label: "OVERVIEW",
    items: [
      { href: "/", label: "Dashboard", icon: LayoutDashboard },
    ],
  },
  {
    label: "ANALYSIS",
    items: [
      { href: "/portfolio", label: "Portfolio", icon: Briefcase },
      { href: "/signals", label: "Signals", icon: BarChart3 },
      { href: "/consensus", label: "Agents", icon: Users },
      { href: "/scan", label: "Scanner", icon: Search },
    ],
  },
  {
    label: "TRADING",
    items: [
      { href: "/targets", label: "Price Targets", icon: Target },
      { href: "/advisor", label: "Advisor", icon: ShieldAlert },
      { href: "/strategy", label: "Strategy", icon: TrendingUp },
      { href: "/rebalance", label: "Rebalance", icon: Scale },
    ],
  },
  {
    label: "SYSTEM",
    items: [
      { href: "/engine", label: "SIEGE Engine", icon: Cog },
      { href: "/evidence", label: "Evidence", icon: FileBarChart },
      { href: "/report", label: "AI Report", icon: Bot },
    ],
  },
];

export function Sidebar() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [siegeStatus, setSiegeStatus] = useState<{ certified: boolean; score: number } | null>(null);

  // SIEGE 인증 상태 조회
  useEffect(() => {
    fetch("http://localhost:8001/api/certify")
      .then((r) => r.ok ? r.json() : null)
      .then((data) => {
        if (data) setSiegeStatus({ certified: data.certified, score: data.score });
      })
      .catch(() => {});
  }, []);

  const w = collapsed ? "w-16" : "w-56";
  const ml = collapsed ? "ml-16" : "ml-56";

  return (
    <>
      <aside className={`fixed left-0 top-0 h-screen ${w} bg-zinc-900 border-r border-zinc-800 flex flex-col z-50 transition-all duration-200`}>
        {/* Logo + Collapse */}
        <div className="h-12 flex items-center justify-between px-4 border-b border-zinc-800">
          <Link href="/" className="flex items-center gap-2 hover:opacity-80 transition-opacity">
            {!collapsed && (
              <>
                <span className="text-lg font-bold text-emerald-400 tracking-tight">Nuri-Quant</span>
                <span className="text-[9px] text-zinc-600 font-mono">v0.1</span>
              </>
            )}
            {collapsed && <span className="text-lg font-bold text-emerald-400">N</span>}
          </Link>
          <button
            onClick={() => setCollapsed(!collapsed)}
            className="text-zinc-500 hover:text-zinc-300 transition-colors"
          >
            {collapsed ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
          </button>
        </div>

        {/* Navigation */}
        <nav className="flex-1 overflow-y-auto py-3">
          {NAV_GROUPS.map((group) => (
            <div key={group.label} className="mb-3">
              {!collapsed && (
                <p className="px-4 text-[10px] font-semibold text-zinc-600 tracking-widest mb-1">
                  {group.label}
                </p>
              )}
              {group.items.map((item) => {
                const active = pathname === item.href;
                const Icon = item.icon;
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    title={collapsed ? item.label : undefined}
                    className={`
                      flex items-center gap-2.5 py-1.5 text-sm transition-colors
                      ${collapsed ? "justify-center px-2" : "px-4"}
                      ${active
                        ? "text-emerald-400 bg-emerald-400/10 border-r-2 border-emerald-400"
                        : "text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800/50"
                      }
                    `}
                  >
                    <Icon size={16} className={active ? "text-emerald-400" : "text-zinc-500"} />
                    {!collapsed && <span>{item.label}</span>}
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>

        {/* SIEGE Status + System */}
        <div className="border-t border-zinc-800 px-4 py-3 space-y-2">
          {/* SIEGE 인증 배지 */}
          {siegeStatus && !collapsed && (
            <div className={`flex items-center gap-2 px-2 py-1.5 rounded text-xs ${
              siegeStatus.certified
                ? "bg-emerald-400/10 text-emerald-400"
                : "bg-red-400/10 text-red-400"
            }`}>
              {siegeStatus.certified ? <ShieldCheck size={14} /> : <ShieldX size={14} />}
              <span className="font-medium">
                {siegeStatus.certified ? "CERTIFIED" : "REJECTED"}
              </span>
              <span className="ml-auto text-[10px] opacity-70">{siegeStatus.score}%</span>
            </div>
          )}
          {siegeStatus && collapsed && (
            <div className="flex justify-center" title={`SIEGE: ${siegeStatus.certified ? "CERTIFIED" : "REJECTED"} (${siegeStatus.score}%)`}>
              {siegeStatus.certified
                ? <ShieldCheck size={16} className="text-emerald-400" />
                : <ShieldX size={16} className="text-red-400" />
              }
            </div>
          )}

          {/* Online 상태 */}
          <div className={`flex items-center gap-2 ${collapsed ? "justify-center" : ""}`}>
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
            </span>
            {!collapsed && <span className="text-[10px] text-zinc-500">System Online</span>}
          </div>
        </div>
      </aside>

      {/* Spacer for main content */}
      <div className={`${w} shrink-0 transition-all duration-200`} />
    </>
  );
}
