"use client";

import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

export default function LoginPage() {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");

    const res = await fetch("/api/auth", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });

    if (res.ok) {
      window.location.href = "/";
    } else {
      setError("Invalid password");
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-zinc-950">
      <Card className="bg-zinc-900 border-zinc-800 w-full max-w-sm">
        <CardContent className="pt-8 pb-6">
          <div className="text-center mb-6">
            <h1 className="text-xl font-bold text-emerald-400">Nuri-Quant</h1>
            <p className="text-xs text-zinc-500 mt-1">Dashboard Login</p>
          </div>
          <form onSubmit={handleSubmit} className="space-y-4">
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Password"
              autoFocus
              className="w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-sm
                         text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500"
            />
            {error && <p className="text-xs text-red-400">{error}</p>}
            <Button
              type="submit"
              disabled={loading || !password}
              className="w-full bg-emerald-600 hover:bg-emerald-700"
            >
              {loading ? "..." : "Login"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
