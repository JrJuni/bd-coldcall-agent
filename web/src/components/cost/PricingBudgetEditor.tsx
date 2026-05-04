"use client";

import { useEffect, useState } from "react";

import { getSettings, putSettings } from "@/lib/api";
import type {
  CostBudgetDoc,
  PricingDoc,
  PricingModelRates,
} from "@/lib/types";

const RATE_FIELDS: Array<{
  key: keyof PricingModelRates;
  label: string;
}> = [
  { key: "input_per_mtok", label: "Input ($/Mtok)" },
  { key: "output_per_mtok", label: "Output ($/Mtok)" },
  { key: "cache_read_per_mtok", label: "Cache read ($/Mtok)" },
  { key: "cache_write_per_mtok", label: "Cache write ($/Mtok)" },
];

function emptyRates(): PricingModelRates {
  return {
    input_per_mtok: 0,
    output_per_mtok: 0,
    cache_read_per_mtok: 0,
    cache_write_per_mtok: 0,
  };
}

function pricingToYaml(p: PricingDoc): string {
  const lines: string[] = ["llm:"];
  for (const [model, rates] of Object.entries(p.llm)) {
    lines.push(`  ${model}:`);
    for (const f of RATE_FIELDS) {
      lines.push(`    ${f.key}: ${Number(rates[f.key]) || 0}`);
    }
  }
  lines.push("");
  lines.push("search:");
  for (const [name, val] of Object.entries(p.search ?? {})) {
    lines.push(`  ${name}:`);
    lines.push(`    per_query_usd: ${val.per_query_usd}`);
  }
  if (Object.keys(p.search ?? {}).length === 0) {
    lines.push("  brave:");
    lines.push("    per_query_usd: 0.0");
  }
  return lines.join("\n") + "\n";
}

function budgetToYaml(b: CostBudgetDoc): string {
  return `monthly_usd: ${b.monthly_usd}\nwarn_pct: ${b.warn_pct}\n`;
}

export default function PricingBudgetEditor({
  onSaved,
}: {
  onSaved: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"form" | "yaml">("form");
  const [pricing, setPricing] = useState<PricingDoc | null>(null);
  const [budget, setBudget] = useState<CostBudgetDoc | null>(null);
  const [pricingYaml, setPricingYaml] = useState("");
  const [budgetYaml, setBudgetYaml] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    try {
      const [pr, bu] = await Promise.all([
        getSettings("pricing"),
        getSettings("cost_budget"),
      ]);
      const pdoc: PricingDoc = (pr.parsed as PricingDoc | null) ?? {
        llm: {},
        search: {},
      };
      const bdoc: CostBudgetDoc = (bu.parsed as CostBudgetDoc | null) ?? {
        monthly_usd: 100,
        warn_pct: 0.8,
      };
      setPricing(pdoc);
      setBudget(bdoc);
      setPricingYaml(pr.raw_yaml || pricingToYaml(pdoc));
      setBudgetYaml(bu.raw_yaml || budgetToYaml(bdoc));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    if (open && pricing == null) void load();
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  function setRate(
    model: string,
    field: keyof PricingModelRates,
    raw: string,
  ) {
    setPricing((p) => {
      if (!p) return p;
      const num = Number(raw);
      const next: PricingDoc = {
        ...p,
        llm: {
          ...p.llm,
          [model]: { ...p.llm[model], [field]: isNaN(num) ? 0 : num },
        },
      };
      setPricingYaml(pricingToYaml(next));
      return next;
    });
  }

  function addModel() {
    const name = prompt("새 모델 ID (예: claude-haiku-4-5-20251001)");
    if (!name) return;
    setPricing((p) => {
      if (!p) return p;
      if (p.llm[name]) return p;
      const next: PricingDoc = {
        ...p,
        llm: { ...p.llm, [name]: emptyRates() },
      };
      setPricingYaml(pricingToYaml(next));
      return next;
    });
  }

  function removeModel(model: string) {
    setPricing((p) => {
      if (!p) return p;
      const { [model]: _, ...rest } = p.llm;
      const next = { ...p, llm: rest };
      setPricingYaml(pricingToYaml(next));
      return next;
    });
  }

  function setBudgetField(field: keyof CostBudgetDoc, raw: string) {
    setBudget((b) => {
      if (!b) return b;
      const num = Number(raw);
      const next = { ...b, [field]: isNaN(num) ? 0 : num };
      setBudgetYaml(budgetToYaml(next));
      return next;
    });
  }

  async function save() {
    if (!pricing || !budget) return;
    setBusy(true);
    setErr(null);
    setMsg(null);
    try {
      const yamlP = mode === "form" ? pricingToYaml(pricing) : pricingYaml;
      const yamlB = mode === "form" ? budgetToYaml(budget) : budgetYaml;
      await putSettings("pricing", yamlP);
      await putSettings("cost_budget", yamlB);
      setMsg("단가 & 예산 저장 완료. KPI 재계산됩니다.");
      onSaved();
      // After YAML save, refresh local state from canonical persisted yaml
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-lg border border-slate-200 bg-white shadow-sm">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between p-5 text-left"
      >
        <div>
          <h2 className="text-sm font-semibold text-slate-700">
            단가 &amp; 예산 설정
          </h2>
          <p className="text-xs text-slate-500">
            모델 토큰 단가($/Mtok)와 월 예산(USD)을 편집합니다. YAML 직접
            편집도 가능합니다.
          </p>
        </div>
        <span className="text-xs text-slate-400">{open ? "닫기 −" : "열기 +"}</span>
      </button>

      {open && (
        <div className="space-y-5 border-t border-slate-200 p-5">
          <div className="flex items-center justify-between">
            <div className="flex gap-1 text-xs">
              <button
                type="button"
                onClick={() => setMode("form")}
                className={
                  "rounded border px-2 py-1 transition " +
                  (mode === "form"
                    ? "border-slate-900 bg-slate-900 text-white"
                    : "border-slate-300 text-slate-600 hover:bg-slate-50")
                }
              >
                폼 편집
              </button>
              <button
                type="button"
                onClick={() => setMode("yaml")}
                className={
                  "rounded border px-2 py-1 transition " +
                  (mode === "yaml"
                    ? "border-slate-900 bg-slate-900 text-white"
                    : "border-slate-300 text-slate-600 hover:bg-slate-50")
                }
              >
                YAML 편집
              </button>
            </div>
            <button
              type="button"
              onClick={save}
              disabled={busy || !pricing || !budget}
              className="rounded bg-slate-900 px-3 py-1.5 text-xs text-white hover:bg-slate-800 disabled:opacity-50"
            >
              {busy ? "저장 중..." : "저장"}
            </button>
          </div>

          {pricing == null && (
            <p className="text-xs text-slate-500">불러오는 중...</p>
          )}

          {pricing && budget && mode === "form" && (
            <div className="space-y-5">
              <div>
                <div className="mb-2 flex items-center justify-between">
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    모델별 단가
                  </h3>
                  <button
                    type="button"
                    onClick={addModel}
                    className="text-xs text-blue-700 hover:underline"
                  >
                    + 모델 추가
                  </button>
                </div>
                <div className="space-y-3">
                  {Object.entries(pricing.llm).length === 0 && (
                    <p className="text-xs text-amber-700">
                      등록된 모델이 없습니다. + 모델 추가 클릭.
                    </p>
                  )}
                  {Object.entries(pricing.llm).map(([model, rates]) => (
                    <div
                      key={model}
                      className="rounded border border-slate-200 p-3"
                    >
                      <div className="mb-2 flex items-center justify-between">
                        <code className="font-mono text-xs text-slate-700">
                          {model}
                        </code>
                        <button
                          type="button"
                          onClick={() => removeModel(model)}
                          className="text-xs text-rose-600 hover:underline"
                        >
                          삭제
                        </button>
                      </div>
                      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
                        {RATE_FIELDS.map((f) => (
                          <label key={f.key} className="block text-xs">
                            <span className="text-slate-500">{f.label}</span>
                            <input
                              type="number"
                              step="0.01"
                              min="0"
                              value={Number(rates[f.key]) || 0}
                              onChange={(e) =>
                                setRate(model, f.key, e.target.value)
                              }
                              className="mt-1 block w-full rounded border border-slate-300 px-2 py-1 font-mono text-xs"
                            />
                          </label>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  월 예산
                </h3>
                <div className="grid grid-cols-2 gap-3">
                  <label className="block text-xs">
                    <span className="text-slate-500">monthly_usd</span>
                    <input
                      type="number"
                      step="1"
                      min="0"
                      value={budget.monthly_usd}
                      onChange={(e) =>
                        setBudgetField("monthly_usd", e.target.value)
                      }
                      className="mt-1 block w-full rounded border border-slate-300 px-2 py-1 font-mono text-xs"
                    />
                  </label>
                  <label className="block text-xs">
                    <span className="text-slate-500">warn_pct (0-1)</span>
                    <input
                      type="number"
                      step="0.05"
                      min="0"
                      max="1"
                      value={budget.warn_pct}
                      onChange={(e) =>
                        setBudgetField("warn_pct", e.target.value)
                      }
                      className="mt-1 block w-full rounded border border-slate-300 px-2 py-1 font-mono text-xs"
                    />
                  </label>
                </div>
              </div>
            </div>
          )}

          {pricing && budget && mode === "yaml" && (
            <div className="space-y-3">
              <div>
                <p className="mb-1 text-xs font-semibold text-slate-500">
                  pricing.yaml
                </p>
                <textarea
                  rows={14}
                  spellCheck={false}
                  value={pricingYaml}
                  onChange={(e) => setPricingYaml(e.target.value)}
                  className="block w-full rounded border border-slate-300 px-3 py-2 font-mono text-xs"
                />
              </div>
              <div>
                <p className="mb-1 text-xs font-semibold text-slate-500">
                  cost_budget.yaml
                </p>
                <textarea
                  rows={4}
                  spellCheck={false}
                  value={budgetYaml}
                  onChange={(e) => setBudgetYaml(e.target.value)}
                  className="block w-full rounded border border-slate-300 px-3 py-2 font-mono text-xs"
                />
              </div>
              <p className="text-xs text-slate-500">
                저장 시 YAML 문법 + pydantic 스키마 두 단계 검증 후 atomic write.
              </p>
            </div>
          )}

          {msg && <p className="text-xs text-emerald-700">{msg}</p>}
          {err && <p className="text-xs text-rose-700">{err}</p>}
        </div>
      )}
    </section>
  );
}
