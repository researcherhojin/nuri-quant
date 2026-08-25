"use client";
/* eslint-disable @typescript-eslint/no-explicit-any */

/**
 * DataTable — 전 페이지 공통 테이블 컴포넌트.
 * 일관된 패딩, 호버, 줄무늬 적용.
 */
import { ReactNode } from "react";

interface Column {
  key: string;
  label: string;
  align?: "left" | "center" | "right";
  width?: string;
  /** 모바일에서 숨김 (sm 미만에서 display:none) */
  hideOnMobile?: boolean;
  render?: (value: any, row: any) => ReactNode;
}

interface DataTableProps {
  columns: Column[];
  data: any[];
  compact?: boolean;
  onRowClick?: (row: any) => void;
  rowClassName?: (row: any) => string;
}

export function DataTable({ columns, data, compact = false, onRowClick, rowClassName }: DataTableProps) {
  // 터미널 밀도 (#1200 U1b-2, 스펙 §2): 기본 행 ~32px(구 compact), compact ~28px.
  // 구 기본값 py-2.5(~40px)는 컨슈머 밀도 — screener 류 표에는 과했다.
  const py = compact ? "py-1" : "py-1.5";
  const text = "text-xs";

  return (
    <div className="overflow-x-auto">
      <table className={`w-full ${text}`}>
        <thead>
          <tr className="border-b border-border">
            {columns.map((col) => (
              <th
                key={col.key}
                className={`${py} px-3 font-mono text-[11px] font-medium uppercase tracking-wider text-muted-foreground ${
                  col.align === "right" ? "text-right" :
                  col.align === "center" ? "text-center" : "text-left"
                }${col.hideOnMobile ? " hidden sm:table-cell" : ""}`}
                style={col.width ? { width: col.width } : undefined}
              >
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((row, i) => (
            <tr
              key={i}
              className={`border-b border-border/40 hover:bg-muted/30 transition-colors ${
                onRowClick ? "cursor-pointer" : ""
              } ${rowClassName ? rowClassName(row) : ""}`}
              onClick={() => onRowClick?.(row)}
            >
              {columns.map((col) => (
                <td
                  key={col.key}
                  className={`${py} px-3 ${
                    col.align === "right" ? "text-right" :
                    col.align === "center" ? "text-center" : "text-left"
                  }${col.hideOnMobile ? " hidden sm:table-cell" : ""}`}
                >
                  {col.render ? col.render(row[col.key], row) : row[col.key]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
