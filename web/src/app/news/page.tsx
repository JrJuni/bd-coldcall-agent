"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import EmptyState from "@/components/EmptyState";
import {
  getNewsRun,
  getNewsToday,
  listRagNamespaces,
  refreshNews,
} from "@/lib/api";
import type {
  NewsArticle,
  NewsRunDetail,
  RagNamespaceSummary,
} from "@/lib/types";

export default function DailyNewsPage() {
  const [namespaces, setNamespaces] = useState<RagNamespaceSummary[]>([]);
  const [namespace, setNamespace] = useState<string>("default");
  const [seedQuery, setSeedQuery] = useState<string>("");
  const [lang, setLang] = useState<"en" | "ko">("en");
  const [days, setDays] = useState<number>(30);
  const [count, setCount] = useState<number>(10);

  const [today, setToday] = useState<NewsRunDetail | null>(null);
  const [active, setActive] = useState<NewsRunDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPoll = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const refreshToday = useCallback(async (ns: string) => {
    try {
      const t = await getNewsToday(ns);
      setToday(t);
      setActive(t);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await listRagNamespaces();
        if (cancelled) return;
        setNamespaces(r.namespaces);
        const initial = r.namespaces.find((n) => n.name === "default")
          ? "default"
          : r.namespaces[0]?.name ?? "default";
        setNamespace(initial);
        await refreshToday(initial);
      } catch (e) {
        if (!cancelled)
          setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
      stopPoll();
    };
  }, [refreshToday, stopPoll]);

  async function onSwitch(ns: string) {
    setNamespace(ns);
    setActive(null);
    setToday(null);
    stopPoll();
    await refreshToday(ns);
  }

  async function onRefresh(e: React.FormEvent) {
    e.preventDefault();
    if (!seedQuery.trim()) {
      setError("seed query 를 입력하세요.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const r = await refreshNews({
        namespace,
        seed_query: seedQuery.trim(),
        lang,
        days,
        count,
      });
      stopPoll();
      const startTs = Date.now();
      pollRef.current = setInterval(async () => {
        try {
          const detail = await getNewsRun(r.task_id);
          setActive(detail);
          if (detail.status === "completed" || detail.status === "failed") {
            stopPoll();
            setBusy(false);
            if (detail.status === "completed") {
              setToday(detail);
            } else {
              setError(detail.error_message ?? "news refresh failed");
            }
          } else if (Date.now() - startTs > 90_000) {
            stopPoll();
            setBusy(false);
            setError("Timed out waiting for news refresh.");
          }
        } catch (err) {
          stopPoll();
          setBusy(false);
          setError(err instanceof Error ? err.message : String(err));
        }
      }, 1500);
    } catch (err) {
      setBusy(false);
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Daily News</h1>
        <p className="mt-1 text-sm text-slate-500">
          Namespace 별 시드 키워드로 최근 뉴스를 모아 캐시합니다. Brave Search 1회
          호출 (ko 시 en+ko 2회). Sonnet 코멘트는 후속 PR 합류 예정.
        </p>
      </div>

      <section className="space-y-3 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <form
          onSubmit={onRefresh}
          className="grid grid-cols-1 gap-3 md:grid-cols-2"
        >
          <label className="block">
            <span className="text-sm font-medium text-slate-700">RAG namespace</span>
            <select
              value={namespace}
              onChange={(e) => onSwitch(e.target.value)}
              className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            >
              {namespaces.map((n) => (
                <option key={n.name} value={n.name}>
                  {n.name} {n.is_default ? "(default)" : ""}
                </option>
              ))}
              {namespaces.length === 0 && (
                <option value="default">default</option>
              )}
            </select>
          </label>
          <label className="block">
            <span className="text-sm font-medium text-slate-700">Seed query</span>
            <input
              required
              value={seedQuery}
              onChange={(e) => setSeedQuery(e.target.value)}
              className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              placeholder="AI infrastructure, lakehouse, data platform"
            />
          </label>
          <label className="block">
            <span className="text-sm font-medium text-slate-700">Language</span>
            <select
              value={lang}
              onChange={(e) => setLang(e.target.value as "en" | "ko")}
              className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            >
              <option value="en">English</option>
              <option value="ko">한국어 (en+ko bilingual blend)</option>
            </select>
          </label>
          <div className="flex gap-3">
            <label className="block flex-1">
              <span className="text-sm font-medium text-slate-700">Days</span>
              <input
                type="number"
                min={1}
                max={365}
                value={days}
                onChange={(e) => setDays(parseInt(e.target.value, 10) || 30)}
                className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              />
            </label>
            <label className="block flex-1">
              <span className="text-sm font-medium text-slate-700">Count</span>
              <input
                type="number"
                min={1}
                max={20}
                value={count}
                onChange={(e) => setCount(parseInt(e.target.value, 10) || 10)}
                className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              />
            </label>
          </div>
          <div className="md:col-span-2">
            <button
              type="submit"
              disabled={busy}
              className="rounded-md bg-slate-900 px-4 py-2 text-sm text-white hover:bg-slate-800 disabled:opacity-50"
            >
              {busy ? "refresh 중..." : "Refresh"}
            </button>
            {error && (
              <span className="ml-3 text-sm text-red-600">{error}</span>
            )}
          </div>
        </form>
      </section>

      {loading && <p className="text-sm text-slate-500">불러오는 중...</p>}

      {!loading && !active && (
        <EmptyState
          title="아직 캐시된 뉴스가 없습니다."
          description="위 폼에 시드 키워드를 입력하고 Refresh 를 누르면 Brave Search 가 결과를 모아 캐시합니다."
        />
      )}

      {active && (
        <section className="space-y-3 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex flex-wrap items-center gap-3 text-xs text-slate-500">
            <span>
              <strong>{active.namespace}</strong> · {active.lang} · 최근 {active.days}일
            </span>
            <span>· seed: {active.seed_query ?? "—"}</span>
            <span>· {active.article_count} 건</span>
            <span>· 생성 {active.generated_at.slice(0, 19).replace("T", " ")}</span>
            <StatusPill status={active.status} />
          </div>
          {active.status === "failed" && active.error_message && (
            <p className="text-xs text-rose-700">{active.error_message}</p>
          )}
          {active.articles.length === 0 && active.status === "completed" && (
            <p className="text-sm text-slate-500">결과가 없습니다.</p>
          )}
          <ul className="space-y-3">
            {active.articles.map((a, i) => (
              <ArticleCard key={i} article={a} />
            ))}
          </ul>
        </section>
      )}

      {today && active && active.task_id !== today.task_id && (
        <p className="text-xs text-slate-500">
          가장 최근 캐시된 entry: {today.generated_at.slice(0, 19).replace("T", " ")}
        </p>
      )}
    </div>
  );
}

function ArticleCard({ article }: { article: NewsArticle }) {
  return (
    <li className="rounded-md border border-slate-200 bg-slate-50 p-3">
      <a
        href={article.url}
        target="_blank"
        rel="noreferrer noopener"
        className="text-sm font-medium text-slate-900 hover:underline"
      >
        {article.title}
      </a>
      <div className="mt-1 flex flex-wrap gap-2 text-xs text-slate-500">
        {article.hostname && <span>{article.hostname}</span>}
        {article.lang && <span>· {article.lang}</span>}
        {article.published && (
          <span>· {article.published.slice(0, 19).replace("T", " ")}</span>
        )}
      </div>
      {article.snippet && (
        <p className="mt-2 text-sm text-slate-700">{article.snippet}</p>
      )}
    </li>
  );
}

function StatusPill({ status }: { status: string }) {
  const styles =
    status === "completed"
      ? "bg-emerald-100 text-emerald-800"
      : status === "failed"
        ? "bg-rose-100 text-rose-800"
        : status === "running"
          ? "bg-blue-100 text-blue-800"
          : "bg-slate-100 text-slate-700";
  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${styles}`}
    >
      {status}
    </span>
  );
}
