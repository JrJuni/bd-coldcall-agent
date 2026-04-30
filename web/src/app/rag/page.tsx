"use client";

import { useCallback, useEffect, useState } from "react";

import EmptyState from "@/components/EmptyState";
import RagDocumentDropzone from "@/components/RagDocumentDropzone";
import {
  createRagNamespace,
  deleteRagDocument,
  deleteRagNamespace,
  getIngestStatus,
  listRagDocuments,
  listRagNamespaces,
  triggerIngest,
} from "@/lib/api";
import type {
  IngestStatus,
  RagDocumentListResponse,
  RagDocumentSummary,
  RagNamespaceSummary,
} from "@/lib/types";

export default function RagPage() {
  const [namespaces, setNamespaces] = useState<RagNamespaceSummary[]>([]);
  const [active, setActive] = useState<string>("default");
  const [docs, setDocs] = useState<RagDocumentListResponse | null>(null);
  const [status, setStatus] = useState<IngestStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const refreshNamespaces = useCallback(async () => {
    const r = await listRagNamespaces();
    setNamespaces(r.namespaces);
    return r;
  }, []);

  const refreshDocs = useCallback(async (ns: string) => {
    try {
      const [d, s] = await Promise.all([
        listRagDocuments(ns),
        getIngestStatus().catch(() => null),
      ]);
      setDocs(d);
      setStatus(s);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const r = await refreshNamespaces();
        const initial =
          r.namespaces.find((n) => n.name === "default")?.name ??
          r.namespaces[0]?.name ??
          "default";
        setActive(initial);
        await refreshDocs(initial);
      } catch (e) {
        setErr(e instanceof Error ? e.message : String(e));
      }
    })();
  }, [refreshNamespaces, refreshDocs]);

  async function onCreateNamespace() {
    const name = prompt(
      "새 namespace 이름 (영문/숫자/-/_ 만 허용):",
      "",
    );
    if (!name) return;
    setBusy(true);
    setErr(null);
    setMsg(null);
    try {
      await createRagNamespace(name.trim());
      await refreshNamespaces();
      setActive(name.trim());
      await refreshDocs(name.trim());
      setMsg(`namespace ${name.trim()!} 생성 완료`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function onDeleteNamespace() {
    if (active === "default") return;
    const force = confirm(
      `namespace "${active}" 의 모든 문서·인덱스를 삭제할까요? 이 작업은 되돌릴 수 없습니다.`,
    );
    if (!force) return;
    setBusy(true);
    setErr(null);
    try {
      await deleteRagNamespace(active, { force: true });
      const r = await refreshNamespaces();
      const next =
        r.namespaces.find((n) => n.name === "default")?.name ??
        r.namespaces[0]?.name ??
        "default";
      setActive(next);
      await refreshDocs(next);
      setMsg(`namespace ${active} 삭제 완료`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function onDeleteDoc(doc: RagDocumentSummary) {
    if (!confirm(`${doc.filename} 을 삭제할까요? (인덱스 청크는 다음 Re-index 시 정리됩니다)`))
      return;
    setBusy(true);
    setErr(null);
    try {
      await deleteRagDocument(active, doc.filename);
      await refreshDocs(active);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function onReindex(dryRun: boolean) {
    setBusy(true);
    setErr(null);
    setMsg(null);
    try {
      const r = await triggerIngest({ notion: false, force: false, dry_run: dryRun });
      setMsg(
        `Task ${r.task_id}: ${r.status}${r.message ? " — " + r.message : ""} (백엔드 로그 확인)`,
      );
      setTimeout(() => refreshDocs(active), 2000);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function onSwitch(ns: string) {
    setActive(ns);
    setDocs(null);
    await refreshDocs(ns);
  }

  const activeMeta = namespaces.find((n) => n.name === active);

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold">RAG Docs</h1>
        <p className="mt-1 text-sm text-slate-500">
          Namespace 별로 참고 문서를 관리합니다. 업로드 → 문서 목록 확인 → Re-index 로
          ChromaDB 에 임베딩. Discovery·Proposal 탭에서 namespace 선택해서 사용.
        </p>
      </div>

      <section className="space-y-3 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-center gap-3">
          <label className="text-sm font-medium text-slate-700">Namespace</label>
          <select
            value={active}
            onChange={(e) => onSwitch(e.target.value)}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm"
          >
            {namespaces.map((n) => (
              <option key={n.name} value={n.name}>
                {n.name} {n.is_default ? "(default)" : ""} — {n.document_count}{" "}
                docs · {n.chunk_count} chunks
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={onCreateNamespace}
            disabled={busy}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50 disabled:opacity-50"
          >
            + 새 namespace
          </button>
          <button
            type="button"
            onClick={onDeleteNamespace}
            disabled={busy || active === "default"}
            className="rounded-md border border-rose-300 bg-white px-3 py-1.5 text-sm text-rose-700 hover:bg-rose-50 disabled:opacity-50"
            title={active === "default" ? "default 는 삭제할 수 없습니다" : ""}
          >
            namespace 삭제
          </button>
        </div>
        {activeMeta && (
          <p className="text-xs text-slate-500">
            인덱스 상태: {activeMeta.document_count} docs · {activeMeta.chunk_count}{" "}
            chunks · 갱신 {activeMeta.updated_at ?? "—"} ·
            {Object.entries(activeMeta.by_source_type)
              .map(([k, v]) => ` ${k}=${v}`)
              .join(",") || " —"}
          </p>
        )}
      </section>

      <section className="space-y-3 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-sm font-semibold text-slate-700">파일 업로드</h2>
        <RagDocumentDropzone
          namespace={active}
          onUploaded={() => refreshDocs(active)}
        />
      </section>

      <section className="space-y-3 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-sm font-semibold text-slate-700">
            문서 목록{" "}
            {docs && (
              <span className="ml-2 text-xs font-normal text-slate-500">
                ({docs.documents.length} files · {docs.indexed_doc_count}{" "}
                indexed)
              </span>
            )}
          </h2>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => onReindex(true)}
              disabled={busy}
              className="rounded-md border border-slate-300 px-3 py-1.5 text-xs hover:bg-slate-50 disabled:opacity-50"
            >
              Dry run
            </button>
            <button
              type="button"
              onClick={() => onReindex(false)}
              disabled={busy}
              className="rounded-md bg-slate-900 px-3 py-1.5 text-xs text-white hover:bg-slate-800 disabled:opacity-50"
            >
              Re-index
            </button>
          </div>
        </div>

        {!docs && <p className="text-sm text-slate-500">불러오는 중...</p>}
        {docs && docs.documents.length === 0 && (
          <EmptyState
            title="이 namespace 는 비어있습니다."
            description="위 드롭 영역으로 .md / .txt / .pdf 를 업로드하고 Re-index 를 눌러 ChromaDB 에 임베딩하세요."
          />
        )}
        {docs && docs.documents.length > 0 && (
          <div className="overflow-hidden rounded-md border border-slate-200">
            <table className="min-w-full divide-y divide-slate-200 text-sm">
              <thead className="bg-slate-50 text-left text-xs">
                <tr>
                  <th className="px-3 py-2 font-medium text-slate-700">File</th>
                  <th className="px-3 py-2 font-medium text-slate-700">Size</th>
                  <th className="px-3 py-2 font-medium text-slate-700">
                    Modified
                  </th>
                  <th className="px-3 py-2 font-medium text-slate-700">
                    Indexed
                  </th>
                  <th className="px-3 py-2 font-medium text-slate-700">
                    Chunks
                  </th>
                  <th className="px-3 py-2"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {docs.documents.map((d) => (
                  <tr key={d.filename} className="hover:bg-slate-50">
                    <td className="px-3 py-2 font-mono text-xs text-slate-800">
                      {d.filename}
                    </td>
                    <td className="px-3 py-2 tabular-nums text-slate-600">
                      {formatSize(d.size_bytes)}
                    </td>
                    <td className="px-3 py-2 text-xs text-slate-500">
                      {d.modified_at?.slice(0, 19).replace("T", " ") ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {d.indexed ? (
                        <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-emerald-800">
                          indexed
                        </span>
                      ) : (
                        <span className="rounded-full bg-amber-100 px-2 py-0.5 text-amber-800">
                          pending
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 tabular-nums text-slate-600">
                      {d.chunk_count}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <button
                        type="button"
                        onClick={() => onDeleteDoc(d)}
                        disabled={busy}
                        className="rounded border border-rose-300 bg-white px-2 py-0.5 text-xs text-rose-700 hover:bg-rose-50 disabled:opacity-50"
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {(msg || err) && (
        <div className="space-y-1 text-sm">
          {msg && <p className="text-emerald-700">{msg}</p>}
          {err && <p className="text-red-600">{err}</p>}
        </div>
      )}

      {status && status.manifest_exists && (
        <details className="rounded-md border border-slate-200 bg-white p-3 text-xs text-slate-600">
          <summary className="cursor-pointer font-medium text-slate-700">
            전체 인덱스 manifest (default namespace)
          </summary>
          <ul className="mt-2 space-y-1">
            <li>
              경로: <code>{status.manifest_path}</code>
            </li>
            <li>버전: {status.version ?? "—"}</li>
            <li>갱신: {status.updated_at ?? "—"}</li>
            <li>문서: {status.document_count} · 청크: {status.chunk_count}</li>
            <li>
              by source:{" "}
              {Object.entries(status.by_source_type)
                .map(([k, v]) => `${k}=${v}`)
                .join(", ") || "—"}
            </li>
          </ul>
        </details>
      )}
    </div>
  );
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
