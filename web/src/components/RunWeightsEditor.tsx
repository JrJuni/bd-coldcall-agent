"use client";

import { useEffect, useMemo, useState } from "react";

import type { DiscoveryDimension, DiscoveryProfile } from "@/lib/types";

const EPS = 1e-6;

type Props = {
  /** Dimensions metadata (key/label/description). Pre-fetched by parent. */
  dimensions: DiscoveryDimension[];
  /** Currently selected profile (carries `effective_weights`). */
  profile: DiscoveryProfile | undefined;
  /**
   * Called whenever the user moves a slider OR resets back to the
   * profile's effective weights. Receives:
   *   - `null` if current state matches `profile.effective_weights`
   *     (idempotent — backend uses load_weights(profile) lookup)
   *   - a complete dict snapshot otherwise (every active dimension key)
   */
  onChange: (snapshot: Record<string, number> | null) => void;
  disabled?: boolean;
};

/**
 * Phase 12 follow-up (B5) — first-run weights editor.
 *
 * Lives inside `DiscoveryRunForm` as a collapsible "▾ 가중치" section.
 * Replaces the post-run results-page `WeightSliders` (deleted) — gathering
 * the "select profile → adjust weights → run" flow into one box.
 *
 * Contract with backend:
 *   - Sliders seed from `profile.effective_weights` (server-derived merge
 *     of `default` + `profiles.<key>.weights`, normalized).
 *   - When user values match effective (within EPS) → emit `null` so the
 *     backend uses `load_weights(profile)` (single source of truth).
 *   - Otherwise → emit complete snapshot (every dimension key) so the
 *     backend's `extra="forbid"` + complete-snapshot validator accepts it.
 */
export default function RunWeightsEditor({
  dimensions,
  profile,
  onChange,
  disabled,
}: Props) {
  const [open, setOpen] = useState(false);
  const [weights, setWeights] = useState<Record<string, number>>({});

  // Reset slider state whenever the parent picks a different profile.
  useEffect(() => {
    if (!profile || dimensions.length === 0) return;
    const seed: Record<string, number> = {};
    for (const d of dimensions) {
      seed[d.key] = profile.effective_weights[d.key] ?? 0;
    }
    setWeights(seed);
    onChange(null); // matches effective
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profile?.key, dimensions]);

  const isModified = useMemo(() => {
    if (!profile) return false;
    for (const d of dimensions) {
      const here = weights[d.key] ?? 0;
      const there = profile.effective_weights[d.key] ?? 0;
      if (Math.abs(here - there) > EPS) return true;
    }
    return false;
  }, [weights, dimensions, profile]);

  const total = useMemo(
    () => dimensions.reduce((s, d) => s + (weights[d.key] ?? 0), 0),
    [weights, dimensions],
  );

  function setOne(key: string, value: number) {
    setWeights((w) => {
      const next = { ...w, [key]: value };
      // Decide payload: null if matches effective, otherwise complete dict.
      if (!profile) {
        onChange(snapshotOf(next, dimensions));
        return next;
      }
      let modified = false;
      for (const d of dimensions) {
        const here = next[d.key] ?? 0;
        const there = profile.effective_weights[d.key] ?? 0;
        if (Math.abs(here - there) > EPS) {
          modified = true;
          break;
        }
      }
      onChange(modified ? snapshotOf(next, dimensions) : null);
      return next;
    });
  }

  function reset() {
    if (!profile) return;
    const seed: Record<string, number> = {};
    for (const d of dimensions) {
      seed[d.key] = profile.effective_weights[d.key] ?? 0;
    }
    setWeights(seed);
    onChange(null);
  }

  if (dimensions.length === 0 || !profile) {
    return null;
  }

  return (
    <div className="mt-1 rounded-md border border-slate-200 bg-slate-50">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={disabled}
        className="flex w-full items-center justify-between px-3 py-2 text-left text-xs text-slate-600 hover:text-slate-800"
      >
        <span>
          {open ? "▾" : "▸"} 가중치 미리보기 / 편집
          <span className="ml-2 text-slate-400">
            (이 run 에만 적용 — 저장하려면 Settings → Discovery weights)
          </span>
        </span>
        {isModified && (
          <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-medium text-amber-800">
            ● 수정됨
          </span>
        )}
      </button>

      {open && (
        <div className="space-y-2 border-t border-slate-200 p-3">
          {dimensions.map((d) => (
            <label
              key={d.key}
              className="flex items-center gap-3 text-sm"
              title={d.description || d.label}
            >
              <span className="w-40 truncate text-slate-700">{d.label}</span>
              <input
                type="range"
                min={0}
                max={1}
                step={0.01}
                value={weights[d.key] ?? 0}
                onChange={(e) => setOne(d.key, parseFloat(e.target.value))}
                disabled={disabled}
                className="flex-1"
              />
              <span className="w-12 text-right tabular-nums text-slate-600">
                {(weights[d.key] ?? 0).toFixed(2)}
              </span>
            </label>
          ))}
          <div className="flex items-center justify-between pt-1 text-xs">
            <span
              className={
                Math.abs(total - 1.0) < 0.02
                  ? "text-slate-500"
                  : "text-amber-700"
              }
            >
              합 {total.toFixed(2)}
              {Math.abs(total - 1.0) >= 0.02 ? " — 백엔드가 정규화" : ""}
            </span>
            <button
              type="button"
              onClick={reset}
              disabled={disabled || !isModified}
              className="rounded border border-slate-300 px-2 py-0.5 text-slate-600 hover:bg-white disabled:opacity-50"
            >
              기본값으로
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function snapshotOf(
  weights: Record<string, number>,
  dimensions: DiscoveryDimension[],
): Record<string, number> {
  const out: Record<string, number> = {};
  for (const d of dimensions) {
    out[d.key] = weights[d.key] ?? 0;
  }
  return out;
}
