"use client";

import { useEffect, useRef, useState } from "react";
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

export default function PortfolioPage() {
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({
    account: "test", ticker: "", quantity: "", avg_price: "", currency: "USD", sector: "",
  });
  const [submitting, setSubmitting] = useState(false);

  // 인라인 수정
  const [editKey, setEditKey] = useState<string | null>(null);
  const [editValues, setEditValues] = useState({ quantity: "", avg_price: "", sector: "" });
  const [editSaving, setEditSaving] = useState(false);

  // CSV 업로드
  const fileRef = useRef<HTMLInputElement>(null);
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<{ imported: number; errors: string[] } | null>(null);

  async function fetchHoldings() {
    setLoading(true);
    const res = await fetch(`${API_BASE}/api/portfolio`);
    const data = await res.json();
    setHoldings(data.holdings || []);
    setLoading(false);
  }

  // eslint-disable-next-line react-hooks/set-state-in-effect -- 초기 데이터 로드
  useEffect(() => { fetchHoldings(); }, []);

  // ─── Add ───
  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    await fetch(`${API_BASE}/api/portfolio`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...form,
        quantity: parseFloat(form.quantity),
        avg_price: parseFloat(form.avg_price),
      }),
    });
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
  }

  function cancelEdit() {
    setEditKey(null);
  }

  async function saveEdit(account: string, ticker: string) {
    setEditSaving(true);
    await fetch(`${API_BASE}/api/portfolio/${account}/${ticker}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        quantity: parseFloat(editValues.quantity),
        avg_price: parseFloat(editValues.avg_price),
        sector: editValues.sector,
      }),
    });
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
    { key: "account", label: "Account", hideOnMobile: true },
    {
      key: "quantity", label: "Qty", align: "right" as const,
      render: (v: number, row: Holding) => {
        const key = `${row.account}/${row.ticker}`;
        if (editKey === key) {
          return (
            <input
              type="number" step="any" className={editInputClass}
              value={editValues.quantity}
              onChange={(e) => setEditValues({ ...editValues, quantity: e.target.value })}
              onClick={(e) => e.stopPropagation()}
            />
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
            <input
              type="number" step="any" className={editInputClass}
              value={editValues.avg_price}
              onChange={(e) => setEditValues({ ...editValues, avg_price: e.target.value })}
              onClick={(e) => e.stopPropagation()}
            />
          );
        }
        return v?.toLocaleString();
      },
    },
    {
      key: "latest_price", label: "Current", align: "right" as const, hideOnMobile: true,
      render: (v: number | null) => v ? `$${v.toLocaleString()}` : "—",
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
              <button
                onClick={() => saveEdit(row.account, row.ticker)}
                disabled={editSaving}
                className="text-emerald-400 hover:text-emerald-300 text-xs transition-colors"
              >
                {editSaving ? "..." : "Save"}
              </button>
              <button
                onClick={cancelEdit}
                className="text-muted-foreground/70 hover:text-foreground text-xs transition-colors"
              >
                Cancel
              </button>
            </span>
          );
        }
        return (
          <span className="flex gap-1.5 justify-center">
            <button
              onClick={(e) => { e.stopPropagation(); startEdit(row); }}
              className="text-muted-foreground/70 hover:text-emerald-400 text-xs transition-colors"
            >
              Edit
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); handleDelete(row.account, row.ticker); }}
              className="text-muted-foreground/70 hover:text-red-400 text-xs transition-colors"
            >
              Delete
            </button>
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
        <div className="flex gap-2">
          <Button
            onClick={() => setShowForm(!showForm)}
            className="bg-emerald-600 hover:bg-emerald-700 text-sm"
          >
            {showForm ? "Cancel" : "Add Holding"}
          </Button>
        </div>
      </div>

      {/* ── Add Form ── */}
      {showForm && (
        <Card className="bg-card border-border">
          <CardContent className="pt-5">
            <form onSubmit={handleAdd} className="grid grid-cols-2 sm:grid-cols-3 gap-3">
              <select
                value={form.account}
                onChange={(e) => setForm({ ...form, account: e.target.value })}
                className={inputClass}
              >
                {["test", "demo", "sample", "pension", "irp"].map((a) => (
                  <option key={a} value={a}>{a}</option>
                ))}
              </select>
              <input placeholder="Ticker (e.g. TSLA)" value={form.ticker}
                onChange={(e) => setForm({ ...form, ticker: e.target.value })} className={inputClass} required />
              <input placeholder="Quantity" type="number" step="any" value={form.quantity}
                onChange={(e) => setForm({ ...form, quantity: e.target.value })} className={inputClass} required />
              <input placeholder="Avg Price" type="number" step="any" value={form.avg_price}
                onChange={(e) => setForm({ ...form, avg_price: e.target.value })} className={inputClass} required />
              <select value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value })}
                className={inputClass}>
                <option value="USD">USD</option>
                <option value="KRW">KRW</option>
              </select>
              <input placeholder="Sector" value={form.sector}
                onChange={(e) => setForm({ ...form, sector: e.target.value })} className={inputClass} />
              <div className="col-span-2 sm:col-span-3">
                <Button type="submit" disabled={submitting} className="bg-emerald-600 hover:bg-emerald-700 text-sm">
                  {submitting ? "Saving..." : "Save"}
                </Button>
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
            <Button
              onClick={() => fileRef.current?.click()}
              disabled={importing}
              variant="outline" className="text-xs h-8"
            >
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
                  {importResult.errors.length > 5 && (
                    <p>...and {importResult.errors.length - 5} more errors</p>
                  )}
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── Holdings Table ── */}
      <Card className="bg-card border-border">
        <CardContent className="pt-5">
          <p className="text-xs text-muted-foreground mb-3">Holdings ({holdings.length})</p>
          {loading ? (
            <div className="h-32 bg-muted rounded animate-pulse" />
          ) : (
            <DataTable columns={columns} data={holdings} compact />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
