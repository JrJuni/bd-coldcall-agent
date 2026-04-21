"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { createRun } from "@/lib/api";

export default function HomePage() {
  const router = useRouter();
  const [company, setCompany] = useState("");
  const [industry, setIndustry] = useState("");
  const [lang, setLang] = useState<"en" | "ko">("en");
  const [topK, setTopK] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body: {
        company: string;
        industry: string;
        lang: "en" | "ko";
        top_k?: number;
      } = { company, industry, lang };
      if (topK) body.top_k = parseInt(topK, 10);
      const r = await createRun(body);
      router.push(`/runs/${encodeURIComponent(r.run_id)}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  return (
    <div className="max-w-xl">
      <h1 className="mb-6 text-2xl font-semibold">New BD run</h1>
      <form
        onSubmit={onSubmit}
        className="space-y-4 rounded-lg border border-slate-200 bg-white p-6 shadow-sm"
      >
        <label className="block">
          <span className="text-sm font-medium text-slate-700">Company</span>
          <input
            required
            value={company}
            onChange={(e) => setCompany(e.target.value)}
            className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2"
            placeholder="NVIDIA"
          />
        </label>
        <label className="block">
          <span className="text-sm font-medium text-slate-700">Industry</span>
          <input
            required
            value={industry}
            onChange={(e) => setIndustry(e.target.value)}
            className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2"
            placeholder="semiconductor"
          />
        </label>
        <div className="flex gap-4">
          <label className="block flex-1">
            <span className="text-sm font-medium text-slate-700">Language</span>
            <select
              value={lang}
              onChange={(e) => setLang(e.target.value as "en" | "ko")}
              className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2"
            >
              <option value="en">English</option>
              <option value="ko">한국어</option>
            </select>
          </label>
          <label className="block flex-1">
            <span className="text-sm font-medium text-slate-700">
              Top-K (optional)
            </span>
            <input
              type="number"
              min={1}
              max={50}
              value={topK}
              onChange={(e) => setTopK(e.target.value)}
              className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2"
              placeholder="8"
            />
          </label>
        </div>
        <button
          type="submit"
          disabled={busy}
          className="w-full rounded-md bg-slate-900 px-4 py-2 text-white hover:bg-slate-800 disabled:opacity-50"
        >
          {busy ? "Starting..." : "Start run"}
        </button>
        {error && <p className="text-sm text-red-600">{error}</p>}
      </form>
    </div>
  );
}
