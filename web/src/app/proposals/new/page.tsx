"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { createRun } from "@/lib/api";

function ProposalNewForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [company, setCompany] = useState(params.get("company") ?? "");
  const [industry, setIndustry] = useState(params.get("industry") ?? "");
  const [lang, setLang] = useState<"en" | "ko">(
    (params.get("lang") as "en" | "ko") || "en",
  );
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
    <div className="max-w-xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">새 제안서 작성</h1>
        <p className="mt-1 text-sm text-slate-500">
          뉴스 검색 → 본문 추출 → 전처리 → RAG 매칭 → Sonnet 종합 → 초안 → 저장.
          Sonnet 2회 호출로 약 ~$0.30 / ~3분 소요.
        </p>
      </div>
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
          {busy ? "Starting..." : "제안서 생성 시작"}
        </button>
        {error && <p className="text-sm text-red-600">{error}</p>}
      </form>
    </div>
  );
}

export default function ProposalNewPage() {
  return (
    <Suspense fallback={<p className="text-sm text-slate-500">로딩 중...</p>}>
      <ProposalNewForm />
    </Suspense>
  );
}
