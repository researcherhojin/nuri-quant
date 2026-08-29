"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { NAV } from "@/lib/strings";
import {
  LayoutDashboard,
  Briefcase,
  BarChart3,
  Users,
  Search,
  Target,
  TrendingUp,
  Scale,
  Cog,
  Workflow,
  FileBarChart,
  Bot,
  ChevronLeft,
  ChevronRight,
  BookOpen,
  Compass,
} from "lucide-react";

// 팔란티어 스타일 그룹 네비게이션 — command-palette 도 소비 (#1226 U5b, 단일 소스)
export const NAV_GROUPS = [
  // 5그룹 재편 (#1200 U1b-2, docs/UX_REDESIGN_PLAN.md §1): 사용 빈도·워크플로 기준.
  // 라우트 삭제·이동 없음 — 그룹핑만 바뀐다. 그룹 라벨은 strings.ts NAV 가 정본.
  {
    label: NAV.TODAY,
    items: [
      { href: "/", label: NAV.ROUTE_DASHBOARD, icon: LayoutDashboard },
    ],
  },
  {
    label: NAV.DECISIONS,
    items: [
      { href: "/decisions", label: NAV.ROUTE_DECISIONS, icon: BookOpen },
      { href: "/engine", label: NAV.ROUTE_ENGINE, icon: Cog },
      { href: "/evidence", label: NAV.ROUTE_EVIDENCE, icon: FileBarChart },
    ],
  },
  {
    label: NAV.PORTFOLIO,
    items: [
      { href: "/portfolio", label: NAV.ROUTE_PORTFOLIO, icon: Briefcase },
      { href: "/rebalance", label: NAV.ROUTE_REBALANCE, icon: Scale },
      { href: "/targets", label: NAV.ROUTE_TARGETS, icon: Target },
    ],
  },
  {
    label: NAV.RESEARCH,
    items: [
      { href: "/explore", label: NAV.ROUTE_EXPLORE, icon: Compass },
      { href: "/scan", label: NAV.ROUTE_SCANNER, icon: Search },
      { href: "/signals", label: NAV.ROUTE_SIGNALS, icon: BarChart3 },
      { href: "/strategy", label: NAV.ROUTE_STRATEGY, icon: TrendingUp },
      { href: "/consensus", label: NAV.ROUTE_AGENTS, icon: Users },
    ],
  },
  {
    label: NAV.SYSTEM,
    items: [
      { href: "/pipeline", label: NAV.ROUTE_PIPELINE, icon: Workflow },
      { href: "/report", label: NAV.ROUTE_REPORT, icon: Bot },
    ],
  },
];

export function Sidebar() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);

  const w = collapsed ? "w-16" : "w-56";

  return (
    <>
      <aside className={`fixed left-0 top-0 h-screen ${w} bg-sidebar border-r border-sidebar-border flex flex-col z-50 transition-all duration-200`}>
        {/* Logo + Collapse */}
        <div className="h-12 flex items-center justify-between px-4 border-b border-border">
          <Link href="/" className="flex items-center gap-2 hover:opacity-80 transition-opacity">
            {!collapsed && (
              <>
                <span className="text-lg font-bold text-foreground tracking-tight">Nuri-Quant</span>
                <span className="text-[9px] text-muted-foreground/70 font-mono">v0.1</span>
              </>
            )}
            {collapsed && <span className="text-lg font-bold text-foreground">N</span>}
          </Link>
          <button
            onClick={() => setCollapsed(!collapsed)}
            // 아이콘 전용 버튼의 접근명 (codex design audit M5) — 문구는 strings SSoT
            aria-label={collapsed ? NAV.SIDEBAR_EXPAND : NAV.SIDEBAR_COLLAPSE}
            className="p-1.5 -m-1.5 text-muted-foreground hover:text-foreground/80 transition-colors focus-visible:outline-2 focus-visible:outline-primary/75"
          >
            {collapsed ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
          </button>
        </div>

        {/* Navigation */}
        <nav className="flex-1 overflow-y-auto py-3">
          {NAV_GROUPS.map((group) => (
            <div key={group.label} className="mb-3">
              {!collapsed && (
                <p className="px-4 text-[10px] font-semibold text-muted-foreground/70 tracking-widest mb-1">
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
                    // 접힘 상태는 아이콘만 남아 title 로는 접근명이 불안정 (codex design audit H1)
                    aria-label={collapsed ? item.label : undefined}
                    className={`
                      flex items-center gap-3 py-2 text-sm transition-colors
                      focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-primary/75
                      ${collapsed ? "justify-center px-3" : "px-4"}
                      ${active
                        ? "text-primary bg-primary/10 border-r-2 border-primary"
                        : "text-muted-foreground hover:text-foreground hover:bg-muted/50"
                      }
                    `}
                  >
                    <Icon size={20} className={active ? "text-primary" : "text-muted-foreground"} />
                    {!collapsed && <span>{item.label}</span>}
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>

        {/* System controls */}
        <div className={`border-t border-border py-3 pb-3 space-y-2 ${collapsed ? "px-2" : "px-4"}`}>
          {/* Theme Toggle + Online */}
          {collapsed ? (
            <div className="flex flex-col items-center gap-2">
              {/* 테마 토글 제거 (#1195 U1a codex P2): 제품은 dark-only (frontend/CLAUDE.md).
                  라이트 전환 시 zinc 램프 재매핑과 시맨틱 토큰이 혼합 테마를 만들던 경로 폐쇄 */}
              <span className="relative flex size-2" title={NAV.SYSTEM_ONLINE}>
                <span className="animate-ping absolute inline-flex size-full rounded-full bg-emerald-400 opacity-75" />
                <span className="relative inline-flex rounded-full size-2 bg-emerald-500" />
              </span>
            </div>
          ) : (
            <>
              <div className="flex items-center gap-2">
                <span className="relative flex size-2">
                  <span className="animate-ping absolute inline-flex size-full rounded-full bg-emerald-400 opacity-75" />
                  <span className="relative inline-flex rounded-full size-2 bg-emerald-500" />
                </span>
                <span className="text-[10px] text-muted-foreground">{NAV.SYSTEM_ONLINE}</span>
              </div>
            </>
          )}
        </div>
      </aside>

      {/* Spacer for main content */}
      <div className={`${w} shrink-0 transition-all duration-200`} />
    </>
  );
}
