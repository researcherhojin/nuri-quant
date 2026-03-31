"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { DataTable } from "@/components/ui/data-table";
import { API_BASE } from "@/lib/api";
import Link from "next/link";

interface Holding {
  ticker: string;
  account: string;
  quantity: number;
  avg_price: number;
  currency: string;
  sector: string;
  latest_price: number | null;
  price_date: string | null;
}

const ACCOUNTS = ["test", "demo", "sample", "pension", "irp"];

export default function PortfolioPage() {
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({
    account: "test", ticker: "", quantity: "", avg_price: "", currency: "USD", sector: "",
  });
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState("");

  // 인라인 수정
  const [editKey, setEditKey] = useState<string | null>(null);
  const [editValues, setEditValues] = useState({ quantity: "", avg_price: "", sector: "" });
  const [editSaving, setEditSaving] = useState(false);
  const [editError, setEditError] = useState("");

  // CSV 업로드
  const fileRef = useRef<HTMLInputElement>(null);
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<{ imported: number; errors: string[] } | null>(null);

  // 계좌별 그룹핑
  const grouped = useMemo(() => {
    const map: Record<string, Holding[]> = {};
    for (const h of holdings) {
      (map[h.account] ||= []).push(h);
    }
    return map;
  }, [holdings]);

  async function fetchHoldings() {
    setLoading(true);
    const res = await fetch(`${API_BASE}/api/portfolio`);
    const data = await res.json();
    setHoldings(data.holdings || []);
    setLoading(false);
  }

  useEffect(() => { fetchHoldings(); }, []);

  // ─── Add ───
  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    setFormError("");
    const qty = parseFloat(form.quantity);
    const avg = parseFloat(form.avg_price);
    if (!qty || qty <= 0) { setFormError("수량은 0보다 커야 합니다"); return; }
    if (!avg || avg <= 0) { setFormError("평균가는 0보다 커야 합니다"); return; }
    if (!form.ticker.trim()) { setFormError("Ticker를 입력하세요"); return; }

    setSubmitting(true);
    const res = await fetch(`${API_BASE}/api/portfolio`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...form, quantity: qty, avg_price: avg }),
    });
    if (!res.ok) {
      const data = await res.json();
      setFormError(data.detail || "추가 실패");
      setSubmitting(false);
      return;
    }
    setForm({ account: "test", ticker: "", quantity: "", avg_price: "", currency: "USD", sector: "" });
    setShowForm(false);
    setSubmitting(false);
    fetchHoldings();
  }

  // ─── Delete ───
  async function handleDelete(account: string, ticker: string) {
    if (!confirm(`Delete ${ticker} from ${account}?`)) return;
    await fetch(`${API_BASE}/api/portfolio/${account}/${ticker}`, { method: "DELETE" });
    fetchHoldings();
  }

  // ─── Inline Edit ───
  function startEdit(row: Holding) {
    setEditKey(`${row.account}/${row.ticker}`);
    setEditValues({
      quantity: String(row.quantity),
      avg_price: String(row.avg_price),
      sector: row.sector || "",
    });
    setEditError("");
  }

  function cancelEdit() {
    setEditKey(null);
    setEditError("");
  }

  async function saveEdit(account: string, ticker: string) {
    const qty = parseFloat(editValues.quantity);
    const avg = parseFloat(editValues.avg_price);
    if (!qty || qty <= 0) { setEditError("수량은 0보다 커야 합니다"); return; }
    if (!avg || avg <= 0) { setEditError("평균가는 0보다 커야 합니다"); return; }

    setEditSaving(true);
    setEditError("");
    const res = await fetch(`${API_BASE}/api/portfolio/${account}/${ticker}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ quantity: qty, avg_price: avg, sector: editValues.sector }),
    });
    if (!res.ok) {
      const data = await res.json();
      setEditError(data.detail || "수정 실패");
      setEditSaving(false);
      return;
    }
    setEditKey(null);
    setEditSaving(false);
    fetchHoldings();
  }

  // ─── CSV Import ───
  async function handleImport(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setImporting(true);
    setImportResult(null);
    const formData = new FormData();
    formData.append("file", file);
    const res = await fetch(`${API_BASE}/api/portfolio/import`, { method: "POST", body: formData });
    const data = await res.json();
    if (res.ok) {
      setImportResult({ imported: data.imported, errors: data.errors || [] });
      fetchHoldings();
    } else {
      setImportResult({ imported: 0, errors: [data.detail || "Import failed"] });
    }
    setImporting(false);
    if (fileRef.current) fileRef.current.value = "";
  }

  // ─── Column definitions ───
  const editInputClass = "w-20 px-1.5 py-0.5 bg-muted border border-input rounded text-xs text-foreground focus:outline-none focus:border-emerald-500 text-right";

  const columns = [
    {
      key: "ticker", label: "Ticker",
      render: (_: string, row: Holding) => (
        <Link href={`/ticker/${row.ticker}`} className="font-medium text-emerald-400 hover:underline">
          {row.ticker}
        </Link>
      ),
    },
    {
      key: "quantity", label: "Qty", align: "right" as const,
      render: (v: number, row: Holding) => {
        const key = `${row.account}/${row.ticker}`;
        if (editKey === key) {
          return (
            <input type="number" step="any" min="0" className={editInputClass}
              value={editValues.quantity}
              onChange={(e) => setEditValues({ ...editValues, quantity: e.target.value })}
              onClick={(e) => e.stopPropagation()} />
          );
        }
        return v?.toLocaleString();
      },
    },
    {
      key: "avg_price", label: "Avg Price", align: "right" as const,
      render: (v: number, row: Holding) => {
        const key = `${row.account}/${row.ticker}`;
        if (editKey === key) {
          return (
            <input type="number" step="any" min="0" className={editInputClass}
              value={editValues.avg_price}
              onChange={(e) => setEditValues({ ...editValues, avg_price: e.target.value })}
              onClick={(e) => e.stopPropagation()} />
          );
        }
        return v?.toLocaleString();
      },
    },
    {
      key: "latest_price", label: "Current", align: "right" as const, hideOnMobile: true,
      render: (v: number | null, row: Holding) =>
        v ? `${row.currency === "KRW" ? "₩" : "$"}${v.toLocaleString()}` : "—",
    },
    {
      key: "pnl", label: "P&L", align: "right" as const,
      render: (_: unknown, row: Holding) => {
        if (!row.latest_price || !row.avg_price) return "—";
        const pnl = ((row.latest_price - row.avg_price) / row.avg_price) * 100;
        return (
          <span className={pnl >= 0 ? "text-emerald-400" : "text-red-400"}>
            {pnl >= 0 ? "+" : ""}{pnl.toFixed(1)}%
          </span>
        );
      },
    },
    {
      key: "actions", label: "", align: "center" as const,
      render: (_: unknown, row: Holding) => {
        const key = `${row.account}/${row.ticker}`;
        if (editKey === key) {
          return (
            <span className="flex gap-1.5 justify-center" onClick={(e) => e.stopPropagation()}>
              <button onClick={() => saveEdit(row.account, row.ticker)} disabled={editSaving}
                className="text-emerald-400 hover:text-emerald-300 text-xs transition-colors">
                {editSaving ? "..." : "Save"}
              </button>
              <button onClick={cancelEdit}
                className="text-muted-foreground/70 hover:text-foreground text-xs transition-colors">
                Cancel
              </button>
            </span>
          );
        }
        return (
          <span className="flex gap-1.5 justify-center">
            <button onClick={(e) => { e.stopPropagation(); startEdit(row); }}
              className="text-muted-foreground/70 hover:text-emerald-400 text-xs transition-colors">Edit</button>
            <button onClick={(e) => { e.stopPropagation(); handleDelete(row.account, row.ticker); }}
              className="text-muted-foreground/70 hover:text-red-400 text-xs transition-colors">Delete</button>
          </span>
        );
      },
    },
  ];

  const inputClass = "w-full px-2.5 py-1.5 bg-muted border border-input rounded text-sm text-foreground focus:outline-none focus:border-zinc-500";

  return (
    <div className="space-y-5">
      {/* ── Header ── */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Portfolio</h1>
        <Button onClick={() => { setShowForm(!showForm); setFormError(""); }}
          className="bg-emerald-600 hover:bg-emerald-700 text-sm">
          {showForm ? "Cancel" : "Add Holding"}
        </Button>
      </div>

      {/* ── Add Form ── */}
      {showForm && (
        <Card className="bg-card border-border">
          <CardContent className="pt-5">
            <form onSubmit={handleAdd} className="grid grid-cols-2 sm:grid-cols-3 gap-3">
              <select value={form.account} onChange={(e) => setForm({ ...form, account: e.target.value })}
                className={inputClass}>
                {ACCOUNTS.map((a) => <option key={a} value={a}>{a}</option>)}
              </select>
              <input placeholder="Ticker (e.g. TSLA)" value={form.ticker}
                onChange={(e) => setForm({ ...form, ticker: e.target.value })} className={inputClass} required />
              <input placeholder="Quantity" type="number" step="any" min="0" value={form.quantity}
                onChange={(e) => setForm({ ...form, quantity: e.target.value })} className={inputClass} required />
              <input placeholder="Avg Price" type="number" step="any" min="0" value={form.avg_price}
                onChange={(e) => setForm({ ...form, avg_price: e.target.value })} className={inputClass} required />
              <select value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value })}
                className={inputClass}>
                <option value="USD">USD</option>
                <option value="KRW">KRW</option>
              </select>
              <input placeholder="Sector" value={form.sector}
                onChange={(e) => setForm({ ...form, sector: e.target.value })} className={inputClass} />
              <div className="col-span-2 sm:col-span-3 flex items-center gap-3">
                <Button type="submit" disabled={submitting} className="bg-emerald-600 hover:bg-emerald-700 text-sm">
                  {submitting ? "Saving..." : "Save"}
                </Button>
                {formError && <span className="text-xs text-red-400">{formError}</span>}
              </div>
            </form>
          </CardContent>
        </Card>
      )}

      {/* ── Import / Export ── */}
      <Card className="bg-card border-border">
        <CardContent className="pt-5">
          <p className="text-xs text-muted-foreground mb-3">Import / Export</p>
          <div className="flex flex-wrap gap-2 items-center">
            <input ref={fileRef} type="file" accept=".csv" onChange={handleImport} className="hidden" />
            <Button onClick={() => fileRef.current?.click()} disabled={importing}
              variant="outline" className="text-xs h-8">
              {importing ? "Importing..." : "Upload CSV"}
            </Button>
            <a href={`${API_BASE}/api/portfolio/export?format=csv`} download>
              <Button variant="outline" className="text-xs h-8">Download CSV</Button>
            </a>
            <a href={`${API_BASE}/api/portfolio/export?format=yaml`} download>
              <Button variant="outline" className="text-xs h-8">Download YAML</Button>
            </a>
          </div>
          {importResult && (
            <div className="mt-3 text-xs">
              {importResult.imported > 0 && (
                <p className="text-emerald-400">{importResult.imported} holdings imported.</p>
              )}
              {importResult.errors.length > 0 && (
                <div className="text-red-400 mt-1 space-y-0.5">
                  {importResult.errors.slice(0, 5).map((err, i) => <p key={i}>{err}</p>)}
                  {importResult.errors.length > 5 && <p>...and {importResult.errors.length - 5} more errors</p>}
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── Holdings by Account ── */}
      {loading ? (
        <div className="h-32 bg-muted rounded animate-pulse" />
      ) : Object.keys(grouped).length === 0 ? (
        <Card className="bg-card border-border">
          <CardContent className="pt-5">
            <p className="text-sm text-muted-foreground">
              No holdings yet. Add a holding or upload a CSV to get started.
            </p>
          </CardContent>
        </Card>
      ) : (
        Object.entries(grouped).map(([account, items]) => (
          <Card key={account} className="bg-card border-border">
            <CardContent className="pt-5">
              <div className="flex items-center gap-2 mb-3">
                <span className="text-sm font-medium">{account}</span>
                <span className="text-[10px] text-muted-foreground">
                  {items.length} holdings · {items[0]?.currency}
                </span>
              </div>
              {editError && editKey?.startsWith(account + "/") && (
                <p className="text-xs text-red-400 mb-2">{editError}</p>
              )}
              <DataTable columns={columns} data={items} compact />
            </CardContent>
          </Card>
        ))
      )}
    </div>
  );
}
