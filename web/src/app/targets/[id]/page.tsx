"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";

import TargetStageBadge from "@/components/TargetStageBadge";
import { deleteTarget, getTarget, patchTarget } from "@/lib/api";
import type { Target, TargetStage } from "@/lib/types";
import { TARGET_STAGES } from "@/lib/types";

export default function TargetDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const id = parseInt(params.id, 10);

  const [target, setTarget] = useState<Target | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [industry, setIndustry] = useState("");
  const [aliases, setAliases] = useState("");
  const [notes, setNotes] = useState("");
  const [stage, setStage] = useState<TargetStage>("planned");
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);

  function applyToForm(t: Target) {
    setName(t.name);
    setIndustry(t.industry);
    setAliases(t.aliases.join(", "));
    setNotes(t.notes ?? "");
    setStage(t.stage);
  }

  useEffect(() => {
    if (Number.isNaN(id)) {
      setError("Invalid target id");
      setLoading(false);
      return;
    }
    getTarget(id)
      .then((t) => {
        setTarget(t);
        applyToForm(t);
        setError(null);
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false));
  }, [id]);

  async function onSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const aliasList = aliases
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      const updated = await patchTarget(id, {
        name,
        industry,
        aliases: aliasList,
        notes: notes || null,
        stage,
      });
      setTarget(updated);
      applyToForm(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  async function onDelete() {
    if (!confirm(`Delete target "${target?.name}"? 이 작업은 되돌릴 수 없습니다.`))
      return;
    setDeleting(true);
    try {
      await deleteTarget(id);
      router.push("/targets");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setDeleting(false);
    }
  }

  if (loading) {
    return <p className="text-sm text-slate-500">불러오는 중...</p>;
  }
  if (error && !target) {
    return (
      <div className="space-y-3">
        <p className="text-sm text-red-600">{error}</p>
        <Link href="/targets" className="text-sm text-blue-600 hover:underline">
          ← 목록으로
        </Link>
      </div>
    );
  }
  if (!target) return null;

  return (
    <div className="max-w-2xl space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <Link
            href="/targets"
            className="text-xs text-slate-500 hover:underline"
          >
            ← Targets
          </Link>
          <h1 className="mt-2 text-2xl font-semibold">{target.name}</h1>
          <div className="mt-2 flex items-center gap-2">
            <TargetStageBadge stage={target.stage} />
            <span className="text-xs text-slate-500">
              {target.created_from} · id {target.id}
            </span>
          </div>
        </div>
        <button
          type="button"
          onClick={onDelete}
          disabled={deleting}
          className="rounded-md border border-rose-300 bg-white px-3 py-1.5 text-sm text-rose-700 hover:bg-rose-50 disabled:opacity-50"
        >
          {deleting ? "삭제 중..." : "삭제"}
        </button>
      </div>

      <form
        onSubmit={onSave}
        className="space-y-4 rounded-lg border border-slate-200 bg-white p-6 shadow-sm"
      >
        <label className="block">
          <span className="text-sm font-medium text-slate-700">Company</span>
          <input
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2"
          />
        </label>
        <label className="block">
          <span className="text-sm font-medium text-slate-700">Industry</span>
          <input
            required
            value={industry}
            onChange={(e) => setIndustry(e.target.value)}
            className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2"
          />
        </label>
        <label className="block">
          <span className="text-sm font-medium text-slate-700">
            Aliases (쉼표 구분)
          </span>
          <input
            value={aliases}
            onChange={(e) => setAliases(e.target.value)}
            className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2"
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
        <label className="block">
          <span className="text-sm font-medium text-slate-700">Notes</span>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={3}
            className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2"
          />
        </label>
        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={saving}
            className="rounded-md bg-slate-900 px-4 py-2 text-white hover:bg-slate-800 disabled:opacity-50"
          >
            {saving ? "저장 중..." : "저장"}
          </button>
          {error && <span className="text-sm text-red-600">{error}</span>}
        </div>
      </form>

      <div className="text-xs text-slate-500">
        Created {target.created_at.slice(0, 19).replace("T", " ")} · Updated{" "}
        {target.updated_at.slice(0, 19).replace("T", " ")}
      </div>
    </div>
  );
}
