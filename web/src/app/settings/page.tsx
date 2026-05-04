"use client";

import { useEffect, useState } from "react";

import {
  getSecretsView,
  getSettings,
  listSettingsKinds,
  putSettings,
} from "@/lib/api";
import type { SecretsView, SettingsRead } from "@/lib/types";
import { SETTINGS_KINDS } from "@/lib/types";

// Settings page only renders the seven user-facing config kinds.
// pricing / cost_budget are reachable through PUT /settings/{kind} but
// are edited from the Cost page, not here.
type ConfigKind = (typeof SETTINGS_KINDS)[number];

const KIND_LABELS: Record<ConfigKind, string> = {
  settings: "Runtime defaults",
  weights: "Discovery weights",
  tier_rules: "Tier thresholds",
  competitors: "Competitors",
  intent_tiers: "Intent tiers",
  sector_leaders: "Sector leaders",
  targets: "Targets (user data)",
};

const KIND_HINTS: Record<ConfigKind, string> = {
  settings: "config/settings.yaml — committed defaults (LLM, search, RAG).",
  weights: "config/weights.yaml — Phase 9.1 6-dim scoring weights.",
  tier_rules: "config/tier_rules.yaml — final_score → tier 임계값.",
  competitors: "config/competitors.yaml — Competitor 채널 키워드.",
  intent_tiers: "config/intent_tiers.yaml — Related 채널 intent tier.",
  sector_leaders: "config/sector_leaders.yaml — mega-cap bias mitigation seed.",
  targets: "config/targets.yaml — user 타겟 회사 + Notion ID. gitignored.",
};

const TAB_ORDER: (ConfigKind | "secrets")[] = [
  ...SETTINGS_KINDS,
  "secrets",
];

export default function SettingsPage() {
  const [active, setActive] = useState<ConfigKind | "secrets">("settings");
  const [byKind, setByKind] = useState<Record<string, SettingsRead | null>>(
    {},
  );
  const [draft, setDraft] = useState<string>("");
  const [secrets, setSecrets] = useState<SecretsView | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  async function refreshKind(kind: ConfigKind) {
    try {
      const r = await getSettings(kind);
      setByKind((prev) => ({ ...prev, [kind]: r }));
      if (kind === active) setDraft(r.raw_yaml);
      return r;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return null;
    }
  }

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        // Confirm endpoint up + lazy-load each kind.
        await listSettingsKinds();
        await Promise.all(
          SETTINGS_KINDS.map(async (k) => {
            const r = await getSettings(k);
            if (cancelled) return;
            setByKind((prev) => ({ ...prev, [k]: r }));
          }),
        );
        if (cancelled) return;
        const sv = await getSecretsView();
        if (cancelled) return;
        setSecrets(sv);
      } catch (err) {
        if (!cancelled)
          setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (active === "secrets") return;
    const cached = byKind[active];
    if (cached) setDraft(cached.raw_yaml);
    else void refreshKind(active);
    setError(null);
    setMsg(null);
  }, [active]); // eslint-disable-line react-hooks/exhaustive-deps

  async function onSave() {
    if (active === "secrets") return;
    setBusy(true);
    setError(null);
    setMsg(null);
    try {
      const r = await putSettings(active, draft);
      setByKind((prev) => ({ ...prev, [active]: r }));
      setMsg(`${KIND_LABELS[active]} 저장 완료 (캐시 무효화됨).`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  function onReload() {
    if (active === "secrets") return;
    void refreshKind(active);
    setMsg(null);
    setError(null);
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Settings</h1>
        <p className="mt-1 text-sm text-slate-500">
          config/*.yaml 직접 편집 — YAML 문법 + pydantic 스키마 두 단계 검증 후
          atomic 쓰기. 저장 시 loader lru_cache 무효화로 다음 호출부터 즉시 반영.
          API 키는 .env 에서만 관리 (이 화면은 존재 여부만 확인).
        </p>
      </div>

      <nav className="flex flex-wrap gap-2 border-b border-slate-200">
        {TAB_ORDER.map((k) => (
          <button
            key={k}
            type="button"
            onClick={() => setActive(k)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm transition ${
              active === k
                ? "border-slate-900 font-medium text-slate-900"
                : "border-transparent text-slate-500 hover:text-slate-700"
            }`}
          >
            {k === "secrets" ? "API keys" : KIND_LABELS[k]}
          </button>
        ))}
      </nav>

      {loading && <p className="text-sm text-slate-500">불러오는 중...</p>}

      {!loading && active === "secrets" && (
        <SecretsPanel secrets={secrets} />
      )}

      {!loading && active !== "secrets" && (
        <section className="space-y-3 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-slate-700">
                {KIND_LABELS[active]}
              </h2>
              <p className="text-xs text-slate-500">{KIND_HINTS[active]}</p>
              <p className="mt-1 font-mono text-xs text-slate-500">
                {byKind[active]?.path ?? ""}
                {byKind[active]?.exists === false && (
                  <span className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 text-amber-800">
                    파일 없음 — 저장 시 새로 생성
                  </span>
                )}
              </p>
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={onReload}
                disabled={busy}
                className="rounded border border-slate-300 px-3 py-1.5 text-xs hover:bg-slate-50 disabled:opacity-50"
              >
                다시 불러오기
              </button>
              <button
                type="button"
                onClick={onSave}
                disabled={busy}
                className="rounded bg-slate-900 px-3 py-1.5 text-xs text-white hover:bg-slate-800 disabled:opacity-50"
              >
                {busy ? "저장 중..." : "저장"}
              </button>
            </div>
          </div>
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={24}
            spellCheck={false}
            className="block w-full rounded border border-slate-300 px-3 py-2 font-mono text-xs"
          />
          {msg && <p className="text-xs text-emerald-700">{msg}</p>}
          {error && <p className="text-xs text-red-600">{error}</p>}
        </section>
      )}
    </div>
  );
}

function SecretsPanel({ secrets }: { secrets: SecretsView | null }) {
  if (!secrets) return null;
  const rows: { key: keyof SecretsView; label: string; hint: string }[] = [
    {
      key: "anthropic_api_key",
      label: "ANTHROPIC_API_KEY",
      hint: "Sonnet 호출 (synthesize / draft / discover)",
    },
    {
      key: "brave_search_api_key",
      label: "BRAVE_SEARCH_API_KEY",
      hint: "뉴스/웹 검색 (Phase 1, Daily News)",
    },
    {
      key: "notion_token",
      label: "NOTION_TOKEN",
      hint: "Notion RAG 인덱싱 (`--notion`)",
    },
  ];
  return (
    <section className="space-y-3 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="text-sm font-semibold text-slate-700">API keys</h2>
      <p className="text-xs text-slate-500">
        값은 .env 에서 관리. 이 화면은 존재 여부만 표시 — 키 자체는 절대 응답에
        포함되지 않습니다.
      </p>
      <ul className="space-y-2">
        {rows.map((row) => {
          const present = secrets[row.key];
          return (
            <li
              key={row.key}
              className="flex items-center justify-between rounded border border-slate-200 px-3 py-2 text-sm"
            >
              <div>
                <code className="font-mono">{row.label}</code>
                <p className="text-xs text-slate-500">{row.hint}</p>
              </div>
              {present ? (
                <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-800">
                  set
                </span>
              ) : (
                <span className="rounded-full bg-rose-100 px-2 py-0.5 text-xs font-medium text-rose-800">
                  missing
                </span>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
