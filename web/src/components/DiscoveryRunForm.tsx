"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { createDiscoveryRun, listRagNamespaces } from "@/lib/api";
import type {
  DiscoveryRegion,
  DiscoveryRunCreateInput,
  DiscoveryRunSummary,
  RagNamespaceSummary,
} from "@/lib/types";
import { DISCOVERY_REGIONS } from "@/lib/types";

type Props = {
  onRunCreated: (run: DiscoveryRunSummary) => void;
  disabled?: boolean;
};

const COST_LABEL = "~$0.04 · ~30s · Sonnet 1 call";

export default function DiscoveryRunForm({ onRunCreated, disabled }: Props) {
  const [namespaces, setNamespaces] = useState<RagNamespaceSummary[]>([]);
  const [namespace, setNamespace] = useState<string>("default");
  const [region, setRegion] = useState<DiscoveryRegion>("any");
  const [product, setProduct] = useState<string>("databricks");
  const [seedSummary, setSeedSummary] = useState<string>("");
  const [seedQuery, setSeedQuery] = useState<string>("");
  const [showAdvanced, setShowAdvanced] = useState<boolean>(false);
  const [topK, setTopK] = useState<string>("");
  const [nIndustries, setNIndustries] = useState<string>("5");
  const [nPerIndustry, setNPerIndustry] = useState<string>("5");
  const [lang, setLang] = useState<"en" | "ko">("en");
  const [includeSectorLeaders, setIncludeSectorLeaders] =
    useState<boolean>(true);
  const [busy, setBusy] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listRagNamespaces()
      .then((r) => {
        setNamespaces(r.namespaces);
        if (r.namespaces.length > 0 && !r.namespaces.find((n) => n.name === namespace)) {
          setNamespace(r.namespaces[0].name);
        }
      })
      .catch(() => {
        // Empty list is acceptable; the page-level form still renders default
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const currentNs = namespaces.find((n) => n.name === namespace);
  const isEmptyNs = !currentNs || currentNs.chunk_count === 0;

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (disabled || busy) return;
    if (
      !confirm(
        `이 작업은 Anthropic Sonnet 1회 호출 (${COST_LABEL}) 을 발생시킵니다. 계속 진행하시겠습니까?`,
      )
    ) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const body: DiscoveryRunCreateInput = {
        namespace,
        region,
        product: product.trim() || "databricks",
        seed_summary: seedSummary.trim() || null,
        seed_query: seedQuery.trim() || null,
        top_k: topK ? parseInt(topK, 10) : null,
        n_industries: parseInt(nIndustries, 10) || 5,
        n_per_industry: parseInt(nPerIndustry, 10) || 5,
        lang,
        include_sector_leaders: includeSectorLeaders,
      };
      const run = await createDiscoveryRun(body);
      onRunCreated(run);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      onSubmit={onSubmit}
      className="space-y-4 rounded-lg border border-slate-200 bg-white p-6 shadow-sm"
    >
      <div className="flex items-baseline justify-between">
        <h2 className="text-lg font-medium">새 Discovery 실행</h2>
        <span className="text-xs text-slate-500">{COST_LABEL}</span>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <label className="block">
          <span className="text-sm font-medium text-slate-700">
            Knowledge base (RAG)
          </span>
          <select
            value={namespace}
            onChange={(e) => setNamespace(e.target.value)}
            className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2"
          >
            {namespaces.length === 0 ? (
              <option value="default">default (empty)</option>
            ) : (
              namespaces.map((n) => (
                <option key={n.name} value={n.name}>
                  {n.name}
                  {n.is_default ? " (default)" : ""} — {n.chunk_count} chunks
                </option>
              ))
            )}
          </select>
          {isEmptyNs && (
            <p className="mt-1 text-xs text-amber-700">
              이 namespace 에 인덱싱된 문서가 없습니다. 먼저{" "}
              <Link href="/rag" className="underline">
                RAG 탭
              </Link>{" "}
              에서 문서를 업로드하세요.
            </p>
          )}
        </label>

        <label className="block">
          <span className="text-sm font-medium text-slate-700">Region</span>
          <select
            value={region}
            onChange={(e) => setRegion(e.target.value as DiscoveryRegion)}
            className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2"
          >
            {DISCOVERY_REGIONS.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </label>

        <label className="block md:col-span-2">
          <span className="text-sm font-medium text-slate-700">
            Product key
            <span className="ml-2 text-xs font-normal text-slate-500">
              (weights.yaml::products.&lt;key&gt; — 기본 default 사용)
            </span>
          </span>
          <input
            value={product}
            onChange={(e) => setProduct(e.target.value)}
            className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2"
            placeholder="databricks"
          />
        </label>

        <label className="block md:col-span-2">
          <span className="text-sm font-medium text-slate-700">
            Seed prompt (optional)
            <span className="ml-2 text-xs font-normal text-slate-500">
              제품 한 문단 요약 — RAG 외 추가 컨텍스트
            </span>
          </span>
          <textarea
            value={seedSummary}
            onChange={(e) => setSeedSummary(e.target.value)}
            rows={3}
            className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2"
            placeholder="(비워두면 RAG 만으로 발굴)"
          />
        </label>

        <label className="block md:col-span-2">
          <span className="text-sm font-medium text-slate-700">
            Seed keyword (optional)
            <span className="ml-2 text-xs font-normal text-slate-500">
              RAG retrieve 쿼리 — 기본 &ldquo;core capabilities and target use cases&rdquo;
            </span>
          </span>
          <input
            value={seedQuery}
            onChange={(e) => setSeedQuery(e.target.value)}
            className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2"
            placeholder="core capabilities and target use cases"
          />
        </label>
      </div>

      <button
        type="button"
        onClick={() => setShowAdvanced((v) => !v)}
        className="text-xs text-slate-600 hover:underline"
      >
        {showAdvanced ? "▾ 고급 옵션" : "▸ 고급 옵션"}
      </button>

      {showAdvanced && (
        <div className="grid grid-cols-2 gap-4 rounded-md bg-slate-50 p-4 md:grid-cols-4">
          <label className="block">
            <span className="text-sm font-medium text-slate-700">Top-K (RAG)</span>
            <input
              type="number"
              min={1}
              max={100}
              value={topK}
              onChange={(e) => setTopK(e.target.value)}
              className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2"
              placeholder="20"
            />
          </label>
          <label className="block">
            <span className="text-sm font-medium text-slate-700">N industries</span>
            <input
              type="number"
              min={1}
              max={20}
              value={nIndustries}
              onChange={(e) => setNIndustries(e.target.value)}
              className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2"
            />
          </label>
          <label className="block">
            <span className="text-sm font-medium text-slate-700">N per industry</span>
            <input
              type="number"
              min={1}
              max={20}
              value={nPerIndustry}
              onChange={(e) => setNPerIndustry(e.target.value)}
              className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2"
            />
          </label>
          <label className="block">
            <span className="text-sm font-medium text-slate-700">Lang</span>
            <select
              value={lang}
              onChange={(e) => setLang(e.target.value as "en" | "ko")}
              className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2"
            >
              <option value="en">English</option>
              <option value="ko">한국어</option>
            </select>
          </label>
          <label className="flex items-center gap-2 md:col-span-4">
            <input
              type="checkbox"
              checked={includeSectorLeaders}
              onChange={(e) => setIncludeSectorLeaders(e.target.checked)}
            />
            <span className="text-sm text-slate-700">
              sector_leaders.yaml 시드 회사 포함 (mid-cap·local 편향 보완)
            </span>
          </label>
        </div>
      )}

      <div className="flex items-center gap-3">
        <button
          type="submit"
          disabled={busy || disabled}
          className="rounded-md bg-slate-900 px-4 py-2 text-white hover:bg-slate-800 disabled:opacity-50"
        >
          {busy ? "실행 중..." : "Run Discovery"}
        </button>
        {error && <span className="text-sm text-red-600">{error}</span>}
      </div>
    </form>
  );
}
