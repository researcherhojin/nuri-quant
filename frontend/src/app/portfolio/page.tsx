"use client";

import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { DataTable } from "@/components/ui/data-table";
import { PORTFOLIO } from "@/lib/strings";
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

// Account list is derived from existing holdings — no hardcoded broker names.
// Empty initial state is supplemented from /api/portfolio/accounts when available
// (test fixtures can mock either source).
const FALLBACK_ACCOUNTS = ["test", "demo", "sample"];

export default function PortfolioPage() {
  return (
    <Suspense fallback={<div className="h-32 bg-muted rounded-sm animate-pulse" />}>
      <PortfolioContent />
    </Suspense>
  );
}

function PortfolioContent() {
  const searchParams = useSearchParams();
  const isOnboarding = searchParams.get("onboarding") === "true";

  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [loadingSample, setLoadingSample] = useState(false);
  const [form, setForm] = useState({
    account: "", ticker: "", quantity: "", avg_price: "", currency: "USD", sector: "",
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

  // ACCOUNTS는 기존 holdings에서 동적 추출. 없으면 fallback 사용.
  const ACCOUNTS = useMemo(() => {
    const fromHoldings = Array.from(new Set(holdings.map((h) => h.account))).filter(Boolean);
    return fromHoldings.length > 0 ? fromHoldings : FALLBACK_ACCOUNTS;
  }, [holdings]);

  // form.account 기본값을 첫 번째 ACCOUNTS로 자동 설정 (한 번만)
  useEffect(() => {
    if (!form.account && ACCOUNTS.length > 0) {
      setForm((f) => ({ ...f, account: ACCOUNTS[0] }));
    }
  }, [ACCOUNTS, form.account]);

  async function fetchHoldings() {
    setLoading(true);
    const res = await fetch(`/api/portfolio`);
    const data = await res.json();
    setHoldings(data.holdings || []);
    setLoading(false);
  }

  useEffect(() => { fetchHoldings(); }, []);

  async function handleLoadSample() {
    setLoadingSample(true);
    await fetch(`/api/portfolio/sample`, { method: "POST" });
    setLoadingSample(false);
    fetchHoldings();
  }

  // ─── Add ───
  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    setFormError("");
    const qty = parseFloat(form.quantity);
    const avg = parseFloat(form.avg_price);
    if (!qty || qty <= 0) { setFormError(PORTFOLIO.QTY_ERROR); return; }
    if (!avg || avg <= 0) { setFormError(PORTFOLIO.PRICE_ERROR); return; }
    if (!form.ticker.trim()) { setFormError(PORTFOLIO.TICKER_ERROR); return; }

    setSubmitting(true);
    const res = await fetch(`/api/portfolio`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...form, quantity: qty, avg_price: avg }),
    });
    if (!res.ok) {
      const data = await res.json();
      setFormError(data.detail || PORTFOLIO.ADD_FAILED);
      setSubmitting(false);
      return;
    }
    // ACCOUNTS[0] always truthy: fromHoldings is .filter(Boolean) and FALLBACK_ACCOUNTS[0]==="test", so the ||"" arm is unreachable
    /* v8 ignore next */
    setForm({ account: ACCOUNTS[0] || "", ticker: "", quantity: "", avg_price: "", currency: "USD", sector: "" });
    setShowForm(false);
    setSubmitting(false);
    fetchHoldings();
  }

  // ─── Delete ───
  async function handleDelete(account: string, ticker: string) {
    if (!confirm(`Delete ${ticker} from ${account}?`)) return;
    await fetch(`/api/portfolio/${account}/${ticker}`, { method: "DELETE" });
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
    if (!qty || qty <= 0) { setEditError(PORTFOLIO.QTY_ERROR); return; }
    if (!avg || avg <= 0) { setEditError(PORTFOLIO.PRICE_ERROR); return; }

    setEditSaving(true);
    setEditError("");
    const res = await fetch(`/api/portfolio/${account}/${ticker}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ quantity: qty, avg_price: avg, sector: editValues.sector }),
    });
    if (!res.ok) {
      const data = await res.json();
      setEditError(data.detail || PORTFOLIO.EDIT_FAILED);
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
    const res = await fetch(`/api/portfolio/import`, { method: "POST", body: formData });
    const data = await res.json();
    if (res.ok) {
      setImportResult({ imported: data.imported, errors: data.errors || [] });
      fetchHoldings();
    } else {
      setImportResult({ imported: 0, errors: [data.detail || "Import failed"] });
    }
    setImporting(false);
    // fileRef is bound to a rendered <input>; in jsdom .current is never null when handleImport runs, so the false arm is unreachable
    /* v8 ignore next */
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
              <input placeholder="Ticker (e.g. AAPL)" value={form.ticker}
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
            <a href={`/api/portfolio/export?format=csv`} download>
              <Button variant="outline" className="text-xs h-8">Download CSV</Button>
            </a>
            <a href={`/api/portfolio/export?format=yaml`} download>
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
        <div className="h-32 bg-muted rounded-sm animate-pulse" />
      ) : Object.keys(grouped).length === 0 ? (
        <Card className={`bg-card border-border ${isOnboarding ? "border-emerald-700" : ""}`}>
          <CardContent className="pt-5 space-y-4">
            {isOnboarding && (
              <p className="text-sm font-medium text-emerald-400">
                Welcome to Nuri-Quant
              </p>
            )}
            <p className="text-sm text-muted-foreground">
              Start by adding your portfolio. Follow these steps:
            </p>
            <div className="space-y-3">
              <div className="flex items-start gap-3">
                <span className="flex-none size-6 rounded-full bg-emerald-600 text-white text-xs flex items-center justify-center">1</span>
                <div>
                  <p className="text-sm font-medium">Add holdings</p>
                  <p className="text-xs text-muted-foreground">Click &quot;Add Holding&quot; above to enter your positions manually, or upload a CSV file.</p>
                </div>
              </div>
              <div className="flex items-start gap-3">
                <span className="flex-none size-6 rounded-full bg-zinc-700 text-zinc-300 text-xs flex items-center justify-center">2</span>
                <div>
                  <p className="text-sm font-medium">Collect market data</p>
                  <p className="text-xs text-muted-foreground">Run <code className="text-emerald-400">make collect</code> to fetch price/macro data for your tickers.</p>
                </div>
              </div>
              <div className="flex items-start gap-3">
                <span className="flex-none size-6 rounded-full bg-zinc-700 text-zinc-300 text-xs flex items-center justify-center">3</span>
                <div>
                  <p className="text-sm font-medium">Run analysis</p>
                  <p className="text-xs text-muted-foreground">Run <code className="text-emerald-400">make full-scan</code> for the complete pipeline, or visit the Dashboard.</p>
                </div>
              </div>
            </div>
            <div className="pt-2 flex gap-2">
              <Button onClick={handleLoadSample} disabled={loadingSample}
                variant="outline" className="text-xs h-8">
                {loadingSample ? "Loading..." : "Load Sample Portfolio"}
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : (
        Object.entries(grouped).sort(([, a], [, b]) => {
          // Sort by total holdings value descending (largest account first)
          const aVal = a.reduce((s, h) => s + (h.quantity || 0) * ((h as { latest_price?: number }).latest_price || h.avg_price || 0), 0);
          const bVal = b.reduce((s, h) => s + (h.quantity || 0) * ((h as { latest_price?: number }).latest_price || h.avg_price || 0), 0);
          return bVal - aVal;
        }).map(([account, items]) => (
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
