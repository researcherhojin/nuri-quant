"use client";

import { useEffect, useState } from "react";
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

  async function fetchHoldings() {
    setLoading(true);
    const res = await fetch(`${API_BASE}/api/portfolio`);
    const data = await res.json();
    setHoldings(data.holdings || []);
    setLoading(false);
  }

  useEffect(() => { fetchHoldings(); }, []);

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

  async function handleDelete(account: string, ticker: string) {
    if (!confirm(`Delete ${ticker} from ${account}?`)) return;
    await fetch(`${API_BASE}/api/portfolio/${account}/${ticker}`, { method: "DELETE" });
    fetchHoldings();
  }

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
    { key: "quantity", label: "Qty", align: "right" as const, render: (v: number) => v?.toLocaleString() },
    { key: "avg_price", label: "Avg Price", align: "right" as const, render: (v: number) => v?.toLocaleString() },
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
      render: (_: unknown, row: Holding) => (
        <button
          onClick={(e) => { e.stopPropagation(); handleDelete(row.account, row.ticker); }}
          className="text-zinc-600 hover:text-red-400 text-xs transition-colors"
        >
          Delete
        </button>
      ),
    },
  ];

  const inputClass = "w-full px-2.5 py-1.5 bg-zinc-800 border border-zinc-700 rounded text-sm text-zinc-100 focus:outline-none focus:border-zinc-500";

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Portfolio</h1>
        <Button
          onClick={() => setShowForm(!showForm)}
          className="bg-emerald-600 hover:bg-emerald-700 text-sm"
        >
          {showForm ? "Cancel" : "Add Holding"}
        </Button>
      </div>

      {showForm && (
        <Card className="bg-zinc-900 border-zinc-800">
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

      <Card className="bg-zinc-900 border-zinc-800">
        <CardContent className="pt-5">
          <p className="text-xs text-zinc-500 mb-3">Holdings ({holdings.length})</p>
          {loading ? (
            <div className="h-32 bg-zinc-800 rounded animate-pulse" />
          ) : (
            <DataTable columns={columns} data={holdings} compact />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
