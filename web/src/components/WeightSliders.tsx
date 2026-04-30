"use client";

import { useEffect, useState } from "react";

import type { WeightDimension } from "@/lib/types";
import { WEIGHT_DIMENSIONS } from "@/lib/types";

const DEFAULT_WEIGHTS: Record<WeightDimension, number> = {
  pain_severity: 0.25,
  data_complexity: 0.2,
  governance_need: 0.15,
  ai_maturity: 0.15,
  buying_trigger: 0.15,
  displacement_ease: 0.1,
};

const LABELS: Record<WeightDimension, string> = {
  pain_severity: "Pain severity",
  data_complexity: "Data complexity",
  governance_need: "Governance need",
  ai_maturity: "AI maturity",
  buying_trigger: "Buying trigger",
  displacement_ease: "Displacement ease",
};

type Props = {
  initial?: Record<string, number>;
  onRecompute: (weights: Record<WeightDimension, number>) => void | Promise<void>;
  busy?: boolean;
};

export default function WeightSliders({ initial, onRecompute, busy }: Props) {
  const [weights, setWeights] = useState<Record<WeightDimension, number>>(
    () => normalize(initial) ?? { ...DEFAULT_WEIGHTS },
  );

  useEffect(() => {
    if (initial) {
      const n = normalize(initial);
      if (n) setWeights(n);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initial]);

  const total = WEIGHT_DIMENSIONS.reduce((s, d) => s + weights[d], 0);

  function setOne(dim: WeightDimension, value: number) {
    setWeights({ ...weights, [dim]: value });
  }

  function reset() {
    setWeights({ ...DEFAULT_WEIGHTS });
  }

  return (
    <div className="space-y-3 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-slate-800">
          Weights & recompute
          <span className="ml-2 text-xs font-normal text-slate-500">
            (LLM 호출 0원, 즉시 재계산)
          </span>
        </h3>
        <span
          className={`text-xs ${
            Math.abs(total - 1.0) < 0.01 ? "text-slate-500" : "text-amber-700"
          }`}
        >
          합 {total.toFixed(2)}
          {Math.abs(total - 1.0) >= 0.01 ? " — auto-normalize" : ""}
        </span>
      </div>
      <div className="space-y-2">
        {WEIGHT_DIMENSIONS.map((d) => (
          <label key={d} className="flex items-center gap-3 text-sm">
            <span className="w-36 text-slate-700">{LABELS[d]}</span>
            <input
              type="range"
              min={0}
              max={1}
              step={0.01}
              value={weights[d]}
              onChange={(e) => setOne(d, parseFloat(e.target.value))}
              className="flex-1"
            />
            <span className="w-12 text-right tabular-nums text-slate-600">
              {weights[d].toFixed(2)}
            </span>
          </label>
        ))}
      </div>
      <div className="flex items-center gap-2 pt-1">
        <button
          type="button"
          onClick={() => onRecompute(weights)}
          disabled={busy}
          className="rounded-md bg-slate-900 px-3 py-1.5 text-sm text-white hover:bg-slate-800 disabled:opacity-50"
        >
          {busy ? "계산 중..." : "Recompute"}
        </button>
        <button
          type="button"
          onClick={reset}
          className="rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
        >
          기본값으로
        </button>
      </div>
    </div>
  );
}

function normalize(
  w: Record<string, number> | undefined,
): Record<WeightDimension, number> | null {
  if (!w) return null;
  const out: Partial<Record<WeightDimension, number>> = {};
  for (const d of WEIGHT_DIMENSIONS) {
    if (typeof w[d] !== "number") return null;
    out[d] = w[d];
  }
  return out as Record<WeightDimension, number>;
}
