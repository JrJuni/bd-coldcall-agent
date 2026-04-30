"use client";

import { useCallback, useEffect, useState } from "react";

import EmptyState from "@/components/EmptyState";
import {
  createInteraction,
  deleteInteraction,
  listInteractions,
  patchInteraction,
} from "@/lib/api";
import type {
  Interaction,
  InteractionKind,
  InteractionOutcome,
} from "@/lib/types";
import { INTERACTION_KINDS, INTERACTION_OUTCOMES } from "@/lib/types";

type FormState = {
  company_name: string;
  kind: InteractionKind;
  occurred_at: string;
  outcome: InteractionOutcome | "";
  raw_text: string;
  contact_role: string;
};

const EMPTY_FORM: FormState = {
  company_name: "",
  kind: "call",
  occurred_at: "",
  outcome: "pending",
  raw_text: "",
  contact_role: "",
};

function todayLocal(): string {
  const d = new Date();
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

export default function InteractionsPage() {
  const [rows, setRows] = useState<Interaction[]>([]);
  const [companyFilter, setCompanyFilter] = useState<string>("");
  const [search, setSearch] = useState<string>("");
  const [pendingSearch, setPendingSearch] = useState<string>("");
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState<boolean>(false);

  const [form, setForm] = useState<FormState>(() => ({
    ...EMPTY_FORM,
    occurred_at: todayLocal(),
  }));
  const [editingId, setEditingId] = useState<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      const r = await listInteractions({
        company: companyFilter.trim() || undefined,
        q: search.trim() || undefined,
      });
      setRows(r.interactions);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [companyFilter, search]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  function startEdit(row: Interaction) {
    setEditingId(row.id);
    setForm({
      company_name: row.company_name,
      kind: row.kind,
      occurred_at: row.occurred_at.slice(0, 10),
      outcome: row.outcome ?? "",
      raw_text: row.raw_text ?? "",
      contact_role: row.contact_role ?? "",
    });
  }

  function resetForm() {
    setEditingId(null);
    setForm({ ...EMPTY_FORM, occurred_at: todayLocal() });
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    const body = {
      company_name: form.company_name,
      kind: form.kind,
      occurred_at: form.occurred_at,
      outcome: form.outcome === "" ? null : form.outcome,
      raw_text: form.raw_text || null,
      contact_role: form.contact_role || null,
    };
    try {
      if (editingId == null) {
        await createInteraction(body);
      } else {
        await patchInteraction(editingId, body);
      }
      resetForm();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function onDelete(row: Interaction) {
    if (!confirm(`${row.company_name} 의 ${row.kind} 기록을 삭제할까요?`))
      return;
    try {
      await deleteInteraction(row.id);
      if (editingId === row.id) resetForm();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  function applySearch(e: React.FormEvent) {
    e.preventDefault();
    setSearch(pendingSearch);
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold">사업 기록</h1>
        <p className="mt-1 text-sm text-slate-500">
          콜·미팅·이메일·메모 결과를 텍스트로 캡처. 회사·outcome·일시 메타로
          SQLite 저장, 키워드 LIKE 검색. 임베딩·KG 는 후속 단계.
        </p>
      </div>

      <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="mb-3 text-lg font-medium">
          {editingId == null ? "새 기록 추가" : `기록 #${editingId} 편집`}
        </h2>
        <form
          onSubmit={onSubmit}
          className="grid grid-cols-1 gap-3 md:grid-cols-2"
        >
          <label className="block">
            <span className="text-sm font-medium text-slate-700">Company *</span>
            <input
              required
              value={form.company_name}
              onChange={(e) =>
                setForm({ ...form, company_name: e.target.value })
              }
              className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2"
              placeholder="Stripe"
            />
          </label>
          <div className="flex gap-3">
            <label className="block flex-1">
              <span className="text-sm font-medium text-slate-700">Kind</span>
              <select
                value={form.kind}
                onChange={(e) =>
                  setForm({ ...form, kind: e.target.value as InteractionKind })
                }
                className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2"
              >
                {INTERACTION_KINDS.map((k) => (
                  <option key={k} value={k}>
                    {k}
                  </option>
                ))}
              </select>
            </label>
            <label className="block flex-1">
              <span className="text-sm font-medium text-slate-700">Outcome</span>
              <select
                value={form.outcome}
                onChange={(e) =>
                  setForm({
                    ...form,
                    outcome: e.target.value as InteractionOutcome | "",
                  })
                }
                className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2"
              >
                <option value="">—</option>
                {INTERACTION_OUTCOMES.map((o) => (
                  <option key={o} value={o}>
                    {o}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label className="block">
            <span className="text-sm font-medium text-slate-700">When *</span>
            <input
              required
              type="date"
              value={form.occurred_at.slice(0, 10)}
              onChange={(e) =>
                setForm({ ...form, occurred_at: e.target.value })
              }
              className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2"
            />
          </label>
          <label className="block">
            <span className="text-sm font-medium text-slate-700">
              Contact role
            </span>
            <input
              value={form.contact_role}
              onChange={(e) =>
                setForm({ ...form, contact_role: e.target.value })
              }
              className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2"
              placeholder="VP Engineering, Head of Data ..."
            />
          </label>
          <label className="block md:col-span-2">
            <span className="text-sm font-medium text-slate-700">Notes</span>
            <textarea
              value={form.raw_text}
              onChange={(e) => setForm({ ...form, raw_text: e.target.value })}
              rows={4}
              className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2"
              placeholder="대화 요약 / 다음 액션 / 의사결정 컨텍스트"
            />
          </label>
          <div className="md:col-span-2 flex items-center gap-3">
            <button
              type="submit"
              disabled={submitting}
              className="rounded-md bg-slate-900 px-4 py-2 text-white hover:bg-slate-800 disabled:opacity-50"
            >
              {submitting
                ? "저장 중..."
                : editingId == null
                  ? "추가"
                  : "변경 저장"}
            </button>
            {editingId != null && (
              <button
                type="button"
                onClick={resetForm}
                className="rounded-md border border-slate-300 px-3 py-2 text-sm hover:bg-slate-50"
              >
                취소
              </button>
            )}
            {error && (
              <span className="text-sm text-red-600">{error}</span>
            )}
          </div>
        </form>
      </section>

      <section className="space-y-3">
        <div className="flex flex-wrap items-end gap-3">
          <label className="block">
            <span className="text-xs text-slate-600">회사 필터 (정확)</span>
            <input
              value={companyFilter}
              onChange={(e) => setCompanyFilter(e.target.value)}
              className="mt-1 block w-48 rounded-md border border-slate-300 px-3 py-1.5 text-sm"
              placeholder="Stripe"
            />
          </label>
          <form onSubmit={applySearch} className="flex items-end gap-2">
            <label className="block">
              <span className="text-xs text-slate-600">
                내용 검색 (LIKE)
              </span>
              <input
                value={pendingSearch}
                onChange={(e) => setPendingSearch(e.target.value)}
                className="mt-1 block w-64 rounded-md border border-slate-300 px-3 py-1.5 text-sm"
                placeholder="lakehouse migration"
              />
            </label>
            <button
              type="submit"
              className="rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50"
            >
              검색
            </button>
            {(search || pendingSearch) && (
              <button
                type="button"
                onClick={() => {
                  setSearch("");
                  setPendingSearch("");
                }}
                className="rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50"
              >
                초기화
              </button>
            )}
          </form>
        </div>

        <h2 className="text-lg font-medium">
          기록 ({rows.length})
          {(companyFilter || search) && (
            <span className="ml-2 text-xs font-normal text-slate-500">
              필터링됨
            </span>
          )}
        </h2>

        {loading && <p className="text-sm text-slate-500">불러오는 중...</p>}

        {!loading && rows.length === 0 && (
          <EmptyState
            title="아직 기록이 없습니다."
            description="위 폼에 콜·미팅·메모를 캡처하면 여기에 누적됩니다. 회사 단위 필터와 텍스트 검색이 가능합니다."
          />
        )}

        {rows.length > 0 && (
          <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
            <table className="min-w-full divide-y divide-slate-200 text-sm">
              <thead className="bg-slate-50 text-left text-xs">
                <tr>
                  <th className="px-3 py-2 font-medium text-slate-700">When</th>
                  <th className="px-3 py-2 font-medium text-slate-700">
                    Company
                  </th>
                  <th className="px-3 py-2 font-medium text-slate-700">Kind</th>
                  <th className="px-3 py-2 font-medium text-slate-700">
                    Outcome
                  </th>
                  <th className="px-3 py-2 font-medium text-slate-700">
                    Contact
                  </th>
                  <th className="px-3 py-2 font-medium text-slate-700">Notes</th>
                  <th className="px-3 py-2"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {rows.map((r) => (
                  <tr key={r.id} className="align-top hover:bg-slate-50">
                    <td className="px-3 py-2 text-xs tabular-nums text-slate-500">
                      {r.occurred_at.slice(0, 10)}
                    </td>
                    <td className="px-3 py-2 font-medium text-slate-900">
                      {r.company_name}
                    </td>
                    <td className="px-3 py-2 text-xs">
                      <KindBadge kind={r.kind} />
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {r.outcome ? (
                        <OutcomeBadge outcome={r.outcome} />
                      ) : (
                        <span className="text-slate-400">—</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-xs text-slate-600">
                      {r.contact_role ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-xs text-slate-700">
                      <p className="line-clamp-2 whitespace-pre-wrap">
                        {r.raw_text ?? ""}
                      </p>
                    </td>
                    <td className="px-3 py-2 text-right text-xs">
                      <button
                        type="button"
                        onClick={() => startEdit(r)}
                        className="mr-2 rounded border border-slate-300 px-2 py-0.5 hover:bg-slate-50"
                      >
                        편집
                      </button>
                      <button
                        type="button"
                        onClick={() => onDelete(r)}
                        className="rounded border border-rose-300 bg-white px-2 py-0.5 text-rose-700 hover:bg-rose-50"
                      >
                        삭제
                      </button>
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

function KindBadge({ kind }: { kind: InteractionKind }) {
  const styles: Record<InteractionKind, string> = {
    call: "bg-blue-100 text-blue-800",
    meeting: "bg-violet-100 text-violet-800",
    email: "bg-amber-100 text-amber-800",
    note: "bg-slate-100 text-slate-700",
  };
  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${styles[kind]}`}
    >
      {kind}
    </span>
  );
}

function OutcomeBadge({ outcome }: { outcome: InteractionOutcome }) {
  const styles: Record<InteractionOutcome, string> = {
    positive: "bg-emerald-100 text-emerald-800",
    neutral: "bg-slate-100 text-slate-700",
    negative: "bg-rose-100 text-rose-800",
    pending: "bg-amber-100 text-amber-800",
  };
  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${styles[outcome]}`}
    >
      {outcome}
    </span>
  );
}
