"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { Search } from "lucide-react";
import { EXPLORE } from "@/lib/strings";

interface SearchResult {
  ticker: string;
  name: string | null;
  price: number | null;
  date: string | null;
}

export function ExploreSearch() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const router = useRouter();
  const ref = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  // Debounced search
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (query.trim().length === 0) {
      setResults([]);
      setOpen(false);
      return;
    }
    debounceRef.current = setTimeout(async () => {
      setLoading(true);
      try {
        const res = await fetch(`/api/tickers/search?q=${encodeURIComponent(query.trim())}`);
        if (res.ok) {
          const data = await res.json();
          setResults(data.results ?? []);
          setOpen(true);
        }
      } catch {
        setResults([]);
      } finally {
        setLoading(false);
      }
    }, 250);
  }, [query]);

  function handleSelect(ticker: string) {
    setOpen(false);
    setQuery("");
    router.push(`/ticker/${ticker}`);
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && query.trim()) {
      // Direct navigation for exact ticker input
      setOpen(false);
      const t = query.trim().toUpperCase();
      setQuery("");
      router.push(`/ticker/${t}`);
    }
    if (e.key === "Escape") {
      setOpen(false);
    }
  }

  return (
    <div ref={ref} className="relative" data-testid="explore-search">
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-zinc-500" />
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          onFocus={() => results.length > 0 && setOpen(true)}
          placeholder={EXPLORE.SEARCH_PLACEHOLDER}
          className="w-full rounded-lg border border-zinc-800 bg-zinc-900/60 pl-9 pr-4 py-2.5 text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:ring-1 focus:ring-emerald-500/40 focus:border-emerald-500/40"
          data-testid="explore-search-input"
        />
        {loading && (
          <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] text-zinc-500">
            {EXPLORE.LOADING}
          </span>
        )}
      </div>

      {/* Dropdown */}
      {open && (
        <div className="absolute z-50 mt-1 w-full rounded-lg border border-zinc-800 bg-zinc-900 shadow-lg overflow-hidden" data-testid="explore-search-dropdown">
          {results.length === 0 && !loading ? (
            <p className="px-4 py-3 text-xs text-zinc-500">{EXPLORE.NO_RESULTS}</p>
          ) : (
            results.map((r) => {
              const isKr = r.ticker.endsWith(".KS") || r.ticker.endsWith(".KQ");
              const priceStr = r.price != null
                ? isKr ? `₩${Math.round(r.price).toLocaleString()}` : `$${r.price < 100 ? r.price.toFixed(2) : Math.round(r.price).toLocaleString()}`
                : "";
              return (
                <button
                  key={r.ticker}
                  type="button"
                  onClick={() => handleSelect(r.ticker)}
                  className="flex items-center justify-between w-full px-4 py-2 text-left hover:bg-zinc-800/60 transition-colors"
                  data-testid={`search-result-${r.ticker}`}
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="text-xs font-semibold text-zinc-100">{r.ticker}</span>
                    {r.name && <span className="text-[10px] text-zinc-500 truncate">{r.name}</span>}
                  </div>
                  {priceStr && <span className="text-[10px] text-zinc-400 tabular-nums shrink-0 ml-2">{priceStr}</span>}
                </button>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}
