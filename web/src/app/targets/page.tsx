"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import TargetStageBadge from "@/components/TargetStageBadge";
import { createTarget, listTargets } from "@/lib/api";
import type { Target, TargetStage } from "@/lib/types";
import { TARGET_STAGES } from "@/lib/types";

export default function TargetsPage() {
  const [rows, setRows] = useState<Target[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [industry, setIndustry] = useState("");
  const [aliases, setAliases] = useState("");
  const [notes, setNotes] = useState("");
  const [stage, setStage] = useState<TargetStage>("planned");
  const [submitting, setSubmitting] = useState(false);

  async function refresh() {
    try {
      const r = await listTargets();
      setRows(r.targets);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const aliasList = aliases
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      await createTarget({
        name,
        industry,
        aliases: aliasList,
        notes: notes || null,
        stage,
      });
      setName("");
      setIndustry("");
      setAliases("");
      setNotes("");
      setStage("planned");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="max-w-5xl space-y-8">
      <div>
        <h1 className="text-2xl font-semibold">Targets (파이프라인)</h1>
        <p className="mt-1 text-sm text-slate-500">
          등록된 타겟 기업과 영업 단계 관리. Discovery 자동 promote 는 P10-2 에서 합류.
        </p>
      </div>

      <section className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="mb-4 text-lg font-medium">새 타겟 추가</h2>
        <form onSubmit={onSubmit} className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <label className="block">
            <span className="text-sm font-medium text-slate-700">Company *</span>
            <input
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2"
              placeholder="Stripe"
            />
          </label>
          <label className="block">
            <span className="text-sm font-medium text-slate-700">Industry *</span>
            <input
              required
              value={industry}
              onChange={(e) => setIndustry(e.target.value)}
              className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2"
              placeholder="Financial Services"
            />
          </label>
          <label className="block">
            <span className="text-sm font-medium text-slate-700">
              Aliases (쉼표 구분, optional)
            </span>
            <input
              value={aliases}
              onChange={(e) => setAliases(e.target.value)}
              className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2"
              placeholder="스트라이프, Stripe Inc."
            />
          </label>
          <label className="block">
            <span className="text-sm font-medium text-slate-700">Stage</span>
            <select
              value={stage}
              onChange={(e) => setStage(e.target.value as TargetStage)}
              className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2"
            >
              {TARGET_STAGES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          <label className="block md:col-span-2">
            <span className="text-sm font-medium text-slate-700">Notes (optional)</span>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={2}
              className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2"
              placeholder="contact, context, 결정 사유 등"
            />
          </label>
          <div className="md:col-span-2">
            <button
              type="submit"
              disabled={submitting}
              className="rounded-md bg-slate-900 px-4 py-2 text-white hover:bg-slate-800 disabled:opacity-50"
            >
              {submitting ? "추가 중..." : "추가"}
            </button>
            {error && <span className="ml-3 text-sm text-red-600">{error}</span>}
          </div>
        </form>
      </section>

      <section>
        <h2 className="mb-3 text-lg font-medium">등록된 타겟 ({rows.length})</h2>
        {loading ? (
          <p className="text-sm text-slate-500">불러오는 중...</p>
        ) : rows.length === 0 ? (
          <p className="rounded-md border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">
            아직 등록된 타겟이 없습니다. 위 폼에서 추가해 보세요.
          </p>
        ) : (
          <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
            <table className="min-w-full divide-y divide-slate-200 text-sm">
              <thead className="bg-slate-50 text-left">
                <tr>
                  <th className="px-4 py-2 font-medium text-slate-700">Company</th>
                  <th className="px-4 py-2 font-medium text-slate-700">Industry</th>
                  <th className="px-4 py-2 font-medium text-slate-700">Stage</th>
                  <th className="px-4 py-2 font-medium text-slate-700">From</th>
                  <th className="px-4 py-2 font-medium text-slate-700">Updated</th>
                  <th className="px-4 py-2"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {rows.map((t) => (
                  <tr key={t.id} className="hover:bg-slate-50">
                    <td className="px-4 py-2 font-medium">
                      <Link
                        href={`/targets/${t.id}`}
                        className="text-slate-900 hover:underline"
                      >
                        {t.name}
                      </Link>
                      {t.aliases.length > 0 && (
                        <div className="text-xs text-slate-500">
                          {t.aliases.join(", ")}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-2 text-slate-700">{t.industry}</td>
                    <td className="px-4 py-2">
                      <TargetStageBadge stage={t.stage} />
                    </td>
                    <td className="px-4 py-2 text-xs text-slate-500">
                      {t.created_from}
                    </td>
                    <td className="px-4 py-2 text-xs text-slate-500">
                      {t.updated_at.slice(0, 19).replace("T", " ")}
                    </td>
                    <td className="px-4 py-2 text-right text-xs">
                      <Link
                        href={`/proposals/new?company=${encodeURIComponent(
                          t.name,
                        )}&industry=${encodeURIComponent(t.industry)}`}
                        className="mr-3 font-medium text-emerald-700 hover:underline"
                      >
                        제안서 →
                      </Link>
                      <Link
                        href={`/targets/${t.id}`}
                        className="font-medium text-blue-600 hover:underline"
                      >
                        편집 →
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
