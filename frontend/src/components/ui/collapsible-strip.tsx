"use client";

/**
 * CollapsibleStrip — single-row info strip with toggle (Phase 2-D #214 polish).
 *
 * Each dashboard context strip (알림 / 이벤트 / 후보) wraps its body in this
 * component. The user can collapse it to a 1-line badge or expand back.
 * Collapse state is persisted per `id` in localStorage so the preference
 * survives page reloads.
 *
 * SSR-safe: first server render + initial client render share the same default
 * (expanded). After mount, we read localStorage and flip if needed. The brief
 * flash on load is acceptable — strips are small.
 *
 * Empty state (`count === 0`): render nothing by default, or a subtle hint if
 * `emptyText` is provided.
 */

import { useEffect, useState } from "react";
import { X, ChevronDown } from "lucide-react";
import { COLLAPSIBLE } from "@/lib/strings";

interface CollapsibleStripProps {
  id: string;                 // localStorage key suffix — must be stable + unique
  title: string;              // short title shown in collapsed badge ("알림")
  icon: string;               // emoji prefix ("⚠")
  count: number;              // item count for the badge ("(2)")
  emptyText?: string;         // optional "알림 없음" style hint when count === 0
  children: React.ReactNode;  // expanded body content
  className?: string;
}

const STORAGE_PREFIX = "nuri-dash-strip:";

export function CollapsibleStrip({
  id,
  title,
  icon,
  count,
  emptyText,
  children,
  className = "",
}: CollapsibleStripProps) {
  const [hidden, setHidden] = useState(false);

  // Load persisted state after mount to avoid SSR mismatch.
  // setState within effect 가 React 권고와 반대 (cascading renders) 이지만,
  // localStorage 는 SSR 단계 부재 → lazy initializer 사용 불가. 의도된 패턴.
  useEffect(() => {
    try {
      const saved = localStorage.getItem(STORAGE_PREFIX + id);
      // eslint-disable-next-line react-hooks/set-state-in-effect
      if (saved === "true") setHidden(true);
    } catch {
      // localStorage unavailable (incognito, etc.) — ignore
    }
  }, [id]);

  const toggle = () => {
    setHidden((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(STORAGE_PREFIX + id, String(next));
      } catch {
        // ignore
      }
      return next;
    });
  };

  // Empty state — nothing to show, nothing to collapse
  if (count === 0) {
    if (!emptyText) return null;
    return (
      <div
        className={`text-[10px] text-zinc-500 px-2 py-0.5 ${className}`}
        data-testid={`strip-empty-${id}`}
      >
        {icon} {emptyText}
      </div>
    );
  }

  // Collapsed — 1-line button to expand
  if (hidden) {
    return (
      <button
        type="button"
        onClick={toggle}
        className={`flex items-center gap-1.5 text-[10px] text-zinc-600 hover:text-zinc-300 hover:bg-zinc-900/50 rounded-sm px-2 py-0.5 transition-colors ${className}`}
        data-testid={`strip-collapsed-${id}`}
        aria-label={`${title} ${COLLAPSIBLE.EXPAND_SUFFIX}`}
      >
        <ChevronDown size={10} />
        <span>{icon}</span>
        <span>{title}</span>
        <span className="text-zinc-500 tabular-nums">({count})</span>
      </button>
    );
  }

  // Expanded — full content with X close button
  return (
    <div
      className={`relative group ${className}`}
      data-testid={`strip-${id}`}
    >
      {children}
      <button
        type="button"
        onClick={toggle}
        className="absolute top-0 right-0 text-zinc-700 hover:text-zinc-300 p-1 opacity-0 group-hover:opacity-100 transition-opacity"
        title={COLLAPSIBLE.HIDE}
        aria-label={`${title} ${COLLAPSIBLE.HIDE_SUFFIX}`}
        data-testid={`strip-close-${id}`}
      >
        <X size={12} />
      </button>
    </div>
  );
}
