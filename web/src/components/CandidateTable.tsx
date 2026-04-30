"use client";

import { useState } from "react";

import TierBadge from "@/components/TierBadge";
import {
  deleteDiscoveryCandidate,
  patchDiscoveryCandidate,
  promoteDiscoveryCandidate,
} from "@/lib/api";
import type { DiscoveryCandidate, WeightDimension } from "@/lib/types";
import { WEIGHT_DIMENSIONS } from "@/lib/types";

type Props = {
  candidates: DiscoveryCandidate[];
  onChanged: () => void;
};

const SHORT_LABEL: Record<WeightDimension, string> = {
  pain_severity: "pain",
  data_complexity: "data",
  governance_need: "gov",
  ai_maturity: "ai",
  buying_trigger: "buy",
  displacement_ease: "disp",
};

export default function CandidateTable({ candidates, onChanged }: Props) {
  const [editing, setEditing] = useState<number | null>(null);
  const [busy, setBusy] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  if (candidates.length === 0) {
    return (
      <p className="rounded-md border border-dashed border-slate-300 bg-white p-6 text-center text-sm text-slate-500">
        후보가 없습니다. 위 폼에서 새 Discovery 를 실행해보세요.
      </p>
    );
  }

  async function patch(id: number, body: Record<string, unknown>) {
    setBusy(true);
    setError(null);
    try {
      await patchDiscoveryCandidate(id, body);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onDelete(id: number) {
    if (!confirm("이 후보를 삭제할까요?")) return;
    setBusy(true);
    setError(null);
    try {
      await deleteDiscoveryCandidate(id);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onPromote(id: number) {
    setBusy(true);
    setError(null);
    try {
      const r = await promoteDiscoveryCandidate(id);
      alert(`Targets 에 등록됨 (target_id ${r.target_id}). Targets 탭에서 확인하세요.`);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-2">
      {error && (
        <p className="text-sm text-red-600">{error}</p>
      )}
      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
        <table className="min-w-full divide-y divide-slate-200 text-sm">
          <thead className="bg-slate-50 text-left text-xs">
            <tr>
              <th className="px-3 py-2 font-medium text-slate-700">Tier</th>
              <th className="px-3 py-2 font-medium text-slate-700">Score</th>
              <th className="px-3 py-2 font-medium text-slate-700">Company</th>
              <th className="px-3 py-2 font-medium text-slate-700">Industry</th>
              <th className="px-3 py-2 font-medium text-slate-700">Top signals</th>
              <th className="px-3 py-2 font-medium text-slate-700">Status</th>
              <th className="px-3 py-2"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {candidates.map((c) => (
              <CandidateRow
                key={c.id}
                cand={c}
                expanded={editing === c.id}
                busy={busy}
                onToggle={() => setEditing(editing === c.id ? null : c.id)}
                onSaveScores={(scores) => patch(c.id, { scores })}
                onSaveRationale={(rationale) => patch(c.id, { rationale })}
                onPromote={() => onPromote(c.id)}
                onDelete={() => onDelete(c.id)}
              />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function CandidateRow(props: {
  cand: DiscoveryCandidate;
  expanded: boolean;
  busy: boolean;
  onToggle: () => void;
  onSaveScores: (scores: Record<string, number>) => void;
  onSaveRationale: (rationale: string) => void;
  onPromote: () => void;
  onDelete: () => void;
}) {
  const { cand, expanded, busy, onToggle, onSaveScores, onSaveRationale, onPromote, onDelete } = props;
  const top = topSignals(cand.scores, 2);

  return (
    <>
      <tr className="hover:bg-slate-50">
        <td className="px-3 py-2">
          <TierBadge tier={cand.tier} />
        </td>
        <td className="px-3 py-2 tabular-nums text-slate-700">
          {cand.final_score.toFixed(2)}
        </td>
        <td className="px-3 py-2 font-medium text-slate-900">
          <button
            type="button"
            onClick={onToggle}
            className="hover:underline"
          >
            {cand.name}
          </button>
        </td>
        <td className="px-3 py-2 text-slate-600">{cand.industry}</td>
        <td className="px-3 py-2 text-xs text-slate-500">
          {top.map(([d, v]) => `${SHORT_LABEL[d as WeightDimension] ?? d}=${v}`).join(" · ")}
        </td>
        <td className="px-3 py-2 text-xs">
          <span
            className={
              cand.status === "promoted"
                ? "text-emerald-700"
                : cand.status === "archived"
                  ? "text-slate-400"
                  : "text-slate-600"
            }
          >
            {cand.status}
          </span>
        </td>
        <td className="px-3 py-2 text-right text-xs">
          {cand.status !== "promoted" && (
            <button
              type="button"
              onClick={onPromote}
              disabled={busy}
              className="mr-2 rounded border border-emerald-300 bg-emerald-50 px-2 py-0.5 text-emerald-700 hover:bg-emerald-100 disabled:opacity-50"
            >
              Promote
            </button>
          )}
          <button
            type="button"
            onClick={onDelete}
            disabled={busy}
            className="rounded border border-rose-300 bg-white px-2 py-0.5 text-rose-700 hover:bg-rose-50 disabled:opacity-50"
          >
            Delete
          </button>
        </td>
      </tr>
      {expanded && (
        <tr className="bg-slate-50">
          <td colSpan={7} className="px-3 py-3">
            <CandidateEditor
              cand={cand}
              busy={busy}
              onSaveScores={onSaveScores}
              onSaveRationale={onSaveRationale}
            />
          </td>
        </tr>
      )}
    </>
  );
}

function CandidateEditor({
  cand,
  busy,
  onSaveScores,
  onSaveRationale,
}: {
  cand: DiscoveryCandidate;
  busy: boolean;
  onSaveScores: (scores: Record<string, number>) => void;
  onSaveRationale: (rationale: string) => void;
}) {
  const [scores, setScores] = useState<Record<string, number>>(() =>
    Object.fromEntries(
      WEIGHT_DIMENSIONS.map((d) => [d, cand.scores[d] ?? 0]),
    ),
  );
  const [rationale, setRationale] = useState<string>(cand.rationale ?? "");

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-x-6 gap-y-2 md:grid-cols-3">
        {WEIGHT_DIMENSIONS.map((d) => (
          <label key={d} className="flex items-center gap-2 text-xs">
            <span className="w-32 text-slate-600">{d}</span>
            <input
              type="number"
              min={0}
              max={10}
              value={scores[d]}
              onChange={(e) => {
                const v = parseInt(e.target.value, 10);
                setScores({ ...scores, [d]: isNaN(v) ? 0 : v });
              }}
              className="w-16 rounded border border-slate-300 px-2 py-1 text-right tabular-nums"
            />
          </label>
        ))}
      </div>
      <div className="flex justify-end">
        <button
          type="button"
          onClick={() => onSaveScores(scores)}
          disabled={busy}
          className="rounded bg-slate-900 px-3 py-1 text-xs text-white hover:bg-slate-800 disabled:opacity-50"
        >
          점수 저장
        </button>
      </div>
      <div>
        <label className="block text-xs">
          <span className="font-medium text-slate-700">Rationale</span>
          <textarea
            value={rationale}
            onChange={(e) => setRationale(e.target.value)}
            rows={2}
            className="mt-1 block w-full rounded border border-slate-300 px-2 py-1 text-sm"
          />
        </label>
      </div>
      <div className="flex justify-end">
        <button
          type="button"
          onClick={() => onSaveRationale(rationale)}
          disabled={busy}
          className="rounded bg-slate-900 px-3 py-1 text-xs text-white hover:bg-slate-800 disabled:opacity-50"
        >
          rationale 저장
        </button>
      </div>
    </div>
  );
}

function topSignals(
  scores: Record<string, number>,
  k: number,
): [string, number][] {
  return Object.entries(scores)
    .sort((a, b) => b[1] - a[1])
    .slice(0, k);
}
