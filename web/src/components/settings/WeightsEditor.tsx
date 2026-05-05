"use client";

import { useEffect, useMemo, useState } from "react";

import {
  getDiscoveryDimensions,
  getSettings,
  putSettings,
} from "@/lib/api";
import type {
  DiscoveryDimension,
  WeightsProfile,
  SettingsRead,
  WeightsDoc,
} from "@/lib/types";

// Phase 12 — form-first editor for `config/weights.yaml`. Sliders for the
// `default` weight map and per-profile overrides; YAML escape toggle for raw
// edit (dimension key add/remove still goes through YAML — keeps the form
// scope tight per the plan).
//
// Form mode does NOT mutate the `dimensions:` block; the GET dimensions
// response is the source of truth for which keys to render. To add a new
// dimension, switch to YAML mode, add the row + a `default:` weight, save,
// then come back to form mode.

export default function WeightsEditor({
  initial,
  onSaved,
}: {
  initial: SettingsRead | null;
  onSaved: (next: SettingsRead) => void;
}) {
  const [mode, setMode] = useState<"form" | "yaml">("form");
  const [dims, setDims] = useState<DiscoveryDimension[]>([]);
  const [dimWarn, setDimWarn] = useState<string | null>(null);
  const [doc, setDoc] = useState<WeightsDoc>(() => parseDoc(initial));
  const [yaml, setYaml] = useState<string>(initial?.raw_yaml ?? "");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  // Reseed when parent re-fetches.
  useEffect(() => {
    setDoc(parseDoc(initial));
    setYaml(initial?.raw_yaml ?? "");
  }, [initial]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await getDiscoveryDimensions();
        if (cancelled) return;
        setDims(r.dimensions);
        setDimWarn(r.config_warning);
      } catch (e) {
        if (cancelled) return;
        setDimWarn(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  function setDefaultWeight(key: string, value: number) {
    setDoc((d) => ({
      ...d,
      default: { ...(d.default ?? {}), [key]: value },
    }));
  }

  function setProfileWeight(profileKey: string, key: string, value: number) {
    setDoc((d) => {
      const profiles = { ...(d.profiles ?? {}) };
      const profileEntry: WeightsProfile = { ...(profiles[profileKey] ?? {}) };
      profileEntry.weights = { ...(profileEntry.weights ?? {}), [key]: value };
      profiles[profileKey] = profileEntry;
      return { ...d, profiles };
    });
  }

  function setProfileDescription(profileKey: string, value: string) {
    setDoc((d) => {
      const profiles = { ...(d.profiles ?? {}) };
      const profileEntry: WeightsProfile = { ...(profiles[profileKey] ?? {}) };
      profileEntry.description = value;
      profiles[profileKey] = profileEntry;
      return { ...d, profiles };
    });
  }

  function clearProfileOverride(profileKey: string, key: string) {
    setDoc((d) => {
      const profiles = { ...(d.profiles ?? {}) };
      const profileEntry: WeightsProfile = { ...(profiles[profileKey] ?? {}) };
      const w = { ...(profileEntry.weights ?? {}) };
      delete w[key];
      profileEntry.weights = w;
      profiles[profileKey] = profileEntry;
      return { ...d, profiles };
    });
  }

  async function reload() {
    try {
      const r = await getSettings("weights");
      setDoc(parseDoc(r));
      setYaml(r.raw_yaml);
      onSaved(r);
      setMsg(null);
      setErr(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  async function save() {
    setBusy(true);
    setMsg(null);
    setErr(null);
    try {
      const payload = mode === "form" ? docToYaml(doc, dims) : yaml;
      const r = await putSettings("weights", payload);
      setDoc(parseDoc(r));
      setYaml(r.raw_yaml);
      onSaved(r);
      setMsg(
        "Discovery weights 저장 완료. 다음 recompute / discover 부터 적용됩니다.",
      );
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const profilesEntries = useMemo(
    () => Object.entries(doc.profiles ?? {}),
    [doc.profiles],
  );

  return (
    <section className="space-y-3 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-700">
            Discovery weights
          </h2>
          <p className="text-xs text-slate-500">
            config/weights.yaml — yaml-driven 차원 + default/per-profile 가중치.
            폼 편집이 기본, raw YAML 토글로 fallback. 새 차원 추가는 YAML 편집
            (dimensions 블록).
          </p>
          <p className="mt-1 font-mono text-xs text-slate-500">
            {initial?.path ?? ""}
            {initial?.exists === false && (
              <span className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 text-amber-800">
                파일 없음 — 저장 시 새로 생성
              </span>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
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
              onClick={() => {
                if (mode === "form") setYaml(docToYaml(doc, dims));
                setMode("yaml");
              }}
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
            onClick={reload}
            disabled={busy}
            className="rounded border border-slate-300 px-3 py-1.5 text-xs hover:bg-slate-50 disabled:opacity-50"
          >
            다시 불러오기
          </button>
          <button
            type="button"
            onClick={save}
            disabled={busy}
            className="rounded bg-slate-900 px-3 py-1.5 text-xs text-white hover:bg-slate-800 disabled:opacity-50"
          >
            {busy ? "저장 중..." : "저장"}
          </button>
        </div>
      </div>

      {dimWarn && (
        <p className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          ⚠ {dimWarn}
        </p>
      )}

      {mode === "form" && (
        <div className="space-y-5">
          {dims.length === 0 ? (
            <p className="text-xs text-amber-700">
              차원이 없습니다. YAML 편집 모드에서{" "}
              <code className="font-mono">dimensions:</code> 블록을 먼저
              추가하세요.
            </p>
          ) : (
            <>
              <DefaultWeightsForm
                dims={dims}
                weights={doc.default ?? {}}
                onChange={setDefaultWeight}
              />

              <div className="space-y-3">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Per-profile overrides
                </h3>
                {profilesEntries.length === 0 && (
                  <p className="text-xs text-slate-500">
                    등록된 profile 이 없습니다. 새 profile 추가는 YAML 편집에서.
                  </p>
                )}
                {profilesEntries.map(([key, profileEntry]) => (
                  <ProfileWeightsForm
                    key={key}
                    profileKey={key}
                    profile={profileEntry}
                    dims={dims}
                    defaults={doc.default ?? {}}
                    onWeight={(d, v) => setProfileWeight(key, d, v)}
                    onDescription={(v) => setProfileDescription(key, v)}
                    onClear={(d) => clearProfileOverride(key, d)}
                  />
                ))}
              </div>
            </>
          )}
        </div>
      )}

      {mode === "yaml" && (
        <div className="space-y-2">
          <textarea
            rows={26}
            spellCheck={false}
            value={yaml}
            onChange={(e) => setYaml(e.target.value)}
            className="block w-full rounded border border-slate-300 px-3 py-2 font-mono text-xs"
          />
          <p className="text-xs text-slate-500">
            저장 시 YAML 문법 + pydantic 스키마 두 단계 검증 후 atomic write.
            폼 편집 모드 ↔ YAML 편집 모드 전환 시 폼 상태가 YAML 로
            직렬화됩니다 (수동 코멘트는 사라질 수 있음 — 보존이 필요하면 YAML
            모드에서만 편집하세요).
          </p>
        </div>
      )}

      {msg && <p className="text-xs text-emerald-700">{msg}</p>}
      {err && <p className="text-xs text-rose-700">{err}</p>}
    </section>
  );
}

function DefaultWeightsForm({
  dims,
  weights,
  onChange,
}: {
  dims: DiscoveryDimension[];
  weights: Record<string, number>;
  onChange: (key: string, value: number) => void;
}) {
  const total = dims.reduce((s, d) => s + (weights[d.key] ?? 0), 0);
  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          Default weights
        </h3>
        <span
          className={`text-xs ${
            Math.abs(total - 1.0) < 0.01 ? "text-slate-500" : "text-amber-700"
          }`}
        >
          합 {total.toFixed(2)}
          {Math.abs(total - 1.0) >= 0.01 ? " — 자동 정규화" : ""}
        </span>
      </div>
      <div className="space-y-2">
        {dims.map((d) => (
          <label key={d.key} className="flex items-center gap-3 text-sm">
            <span
              className="w-44 truncate text-slate-700"
              title={d.description || d.label}
            >
              {d.label}
              <span className="ml-1 text-xs text-slate-400">({d.key})</span>
            </span>
            <input
              type="range"
              min={0}
              max={1}
              step={0.01}
              value={weights[d.key] ?? 0}
              onChange={(e) => onChange(d.key, parseFloat(e.target.value))}
              className="flex-1"
            />
            <input
              type="number"
              min={0}
              max={1}
              step={0.01}
              value={weights[d.key] ?? 0}
              onChange={(e) => {
                const v = parseFloat(e.target.value);
                onChange(d.key, isNaN(v) ? 0 : v);
              }}
              className="w-20 rounded border border-slate-300 px-2 py-1 text-right tabular-nums text-xs"
            />
          </label>
        ))}
      </div>
    </div>
  );
}

function ProfileWeightsForm({
  profileKey,
  profile,
  dims,
  defaults,
  onWeight,
  onDescription,
  onClear,
}: {
  profileKey: string;
  profile: WeightsProfile;
  dims: DiscoveryDimension[];
  defaults: Record<string, number>;
  onWeight: (key: string, value: number) => void;
  onDescription: (value: string) => void;
  onClear: (key: string) => void;
}) {
  const overrides = profile.weights ?? {};
  return (
    <div className="rounded border border-slate-200 p-3">
      <div className="mb-2 flex items-center justify-between gap-3">
        <code className="font-mono text-xs text-slate-700">{profileKey}</code>
        <span className="text-xs text-slate-400">
          빈 값 = default 상속 · 좌측 값 = override
        </span>
      </div>
      <label className="block text-xs">
        <span className="text-slate-500">설명 (Discovery 폼 tooltip)</span>
        <textarea
          value={profile.description ?? ""}
          onChange={(e) => onDescription(e.target.value)}
          rows={2}
          className="mt-1 block w-full rounded border border-slate-300 px-2 py-1 text-xs"
        />
      </label>
      <div className="mt-3 grid grid-cols-1 gap-2 md:grid-cols-2">
        {dims.map((d) => {
          const has = Object.prototype.hasOwnProperty.call(overrides, d.key);
          const val = has ? (overrides[d.key] ?? 0) : "";
          return (
            <label
              key={d.key}
              className="flex items-center gap-2 text-xs"
              title={d.description || d.label}
            >
              <span className="w-32 truncate text-slate-600">{d.label}</span>
              <input
                type="number"
                min={0}
                max={1}
                step={0.01}
                value={val}
                placeholder={(defaults[d.key] ?? 0).toFixed(2)}
                onChange={(e) => {
                  const raw = e.target.value;
                  if (raw === "") {
                    onClear(d.key);
                    return;
                  }
                  const v = parseFloat(raw);
                  onWeight(d.key, isNaN(v) ? 0 : v);
                }}
                className="w-20 rounded border border-slate-300 px-2 py-1 text-right tabular-nums"
              />
              {has && (
                <button
                  type="button"
                  onClick={() => onClear(d.key)}
                  className="text-xs text-slate-400 hover:text-rose-600"
                  title="override 삭제"
                >
                  ×
                </button>
              )}
            </label>
          );
        })}
      </div>
    </div>
  );
}

function parseDoc(initial: SettingsRead | null): WeightsDoc {
  if (!initial?.parsed) return {};
  // The /settings/{kind} endpoint round-trips through pydantic so the parsed
  // payload conforms to WeightsDoc. Cast keeps the type-narrowing local.
  return initial.parsed as unknown as WeightsDoc;
}

// Serialize the form state to YAML deterministically. We don't try to round-
// trip user comments — the YAML escape mode is the path for comment-heavy
// edits. Numbers print with up to 2 decimals (matches yaml convention in
// the seed config); empty/undefined profile overrides are dropped.
function docToYaml(doc: WeightsDoc, dims: DiscoveryDimension[]): string {
  const lines: string[] = [];
  if (typeof doc.version === "number") {
    lines.push(`version: ${doc.version}`);
    lines.push("");
  }

  const dimList = dims.length
    ? dims
    : (doc.dimensions ?? []).map((d) => ({
        key: d.key,
        label: d.label ?? d.key,
        description: d.description ?? "",
        default_weight: 0,
      }));

  if (dimList.length > 0) {
    lines.push("dimensions:");
    for (const d of dimList) {
      lines.push(`  - key: ${d.key}`);
      lines.push(`    label: ${quoteIfNeeded(d.label || d.key)}`);
      const desc = (d.description ?? "").trim();
      if (desc) {
        if (desc.includes("\n")) {
          lines.push("    description: >");
          for (const ln of desc.split("\n")) {
            lines.push(`      ${ln}`);
          }
        } else {
          lines.push(`    description: ${quoteIfNeeded(desc)}`);
        }
      }
    }
    lines.push("");
  }

  const def = doc.default ?? {};
  lines.push("default:");
  for (const d of dimList) {
    const v = def[d.key] ?? 0;
    lines.push(`  ${d.key}: ${num(v)}`);
  }
  lines.push("");

  const profiles = doc.profiles ?? {};
  if (Object.keys(profiles).length > 0) {
    lines.push("profiles:");
    for (const [pkey, profile] of Object.entries(profiles)) {
      lines.push(`  ${pkey}:`);
      const desc = (profile.description ?? "").trim();
      if (desc) {
        if (desc.includes("\n")) {
          lines.push("    description: >");
          for (const ln of desc.split("\n")) {
            lines.push(`      ${ln}`);
          }
        } else {
          lines.push(`    description: ${quoteIfNeeded(desc)}`);
        }
      }
      const overrides = profile.weights ?? {};
      const overrideKeys = Object.keys(overrides);
      if (overrideKeys.length > 0) {
        lines.push("    weights:");
        for (const d of dimList) {
          if (!Object.prototype.hasOwnProperty.call(overrides, d.key)) continue;
          lines.push(`      ${d.key}: ${num(overrides[d.key])}`);
        }
      }
    }
  }

  return lines.join("\n") + "\n";
}

function num(v: number | undefined): string {
  if (v == null || isNaN(v)) return "0";
  // Trim trailing zeros while keeping reasonable precision.
  return Number(v.toFixed(4)).toString();
}

function quoteIfNeeded(s: string): string {
  // YAML scalars that contain `:`, `#`, or start with reserved chars need
  // quoting. Keep the rule simple — any char that may need escaping → quote.
  if (/[:#&*!|>'"%@`,\[\]\{\}]/.test(s) || /^\s|\s$/.test(s)) {
    return `"${s.replace(/"/g, '\\"')}"`;
  }
  return s;
}
