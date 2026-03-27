"use client";

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
}

export function DataTable({ columns, data, compact = false, onRowClick }: DataTableProps) {
  const py = compact ? "py-1.5" : "py-2.5";
  const text = compact ? "text-xs" : "text-sm";

  return (
    <div className="overflow-x-auto">
      <table className={`w-full ${text}`}>
        <thead>
          <tr className="border-b border-zinc-800">
            {columns.map((col) => (
              <th
                key={col.key}
                className={`${py} px-3 font-medium text-zinc-500 ${
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
              className={`border-b border-zinc-800/40 hover:bg-zinc-800/30 transition-colors ${
                onRowClick ? "cursor-pointer" : ""
              }`}
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
