"use client";

import {
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useRouter, useSearchParams } from "next/navigation";

import RagDocumentDropzone from "@/components/RagDocumentDropzone";
import AddWorkspaceModal from "@/components/AddWorkspaceModal";
import RemoveWorkspaceModal from "@/components/RemoveWorkspaceModal";
import {
  createRagFolder,
  createRagNamespace,
  deleteRagDocument,
  deleteRagFolder,
  deleteRootFile,
  getCachedRagSummary,
  getIngestStatus,
  listRagNamespaces,
  listRagTree,
  listRootFiles,
  listWorkspaces,
  openRagFolder,
  openRagRoot,
  summarizeRagPath,
  triggerIngest,
  uploadRagDocument,
  uploadRootFile,
} from "@/lib/api";
import type {
  IngestStatus,
  RagDocumentSummary,
  RagNamespaceSummary,
  RagSummaryResponse,
  RagTreeEntry,
  RagTreeResponse,
  Workspace,
} from "@/lib/types";

// ── Path helpers ────────────────────────────────────────────────────────

/**
 * Phase 11: `?path=` is now `<workspace_slug>/<namespace>/<sub>` with up to
 * 3 levels. Empty → no workspace selected (top-level "Workspaces" view).
 * One segment → workspace selected, no namespace yet.
 * Two segments → namespace inside workspace.
 * Three+ → sub-folder inside namespace.
 */
function splitFullPath(fullPath: string): {
  ws: string;
  ns: string;
  sub: string;
} {
  if (!fullPath) return { ws: "", ns: "", sub: "" };
  const parts = fullPath.split("/");
  const [ws = "", ns = "", ...rest] = parts;
  return { ws, ns, sub: rest.join("/") };
}

function namespaceToTreeEntry(n: RagNamespaceSummary): RagTreeEntry {
  return {
    type: "folder",
    name: n.name,
    size_bytes: null,
    modified_at: n.updated_at,
    extension: null,
    indexed: null,
    chunk_count: n.chunk_count,
    child_count: n.document_count,
    needs_reindex: n.needs_reindex,
  };
}

function workspaceToTreeEntry(w: Workspace): RagTreeEntry {
  // Workspaces render as top-level folders in the tree. The label is the
  // workspace label (NOT the slug) so users see human-friendly names; the
  // navigate path uses the slug. We disambiguate via a custom field on
  // the tree row consumed by FileRow / FolderTree below — for now we just
  // surface the slug as `name` so navigation works, and FileRow shows
  // both label and slug when `is_workspace` is set.
  return {
    type: "folder",
    name: w.slug,
    size_bytes: null,
    modified_at: w.updated_at,
    extension: null,
    indexed: null,
    chunk_count: null,
    child_count: null,
    needs_reindex: null,
  };
}

function rootFileToTreeEntry(f: RagDocumentSummary): RagTreeEntry {
  return {
    type: "file",
    name: f.filename,
    size_bytes: f.size_bytes,
    modified_at: f.modified_at,
    extension: f.extension,
    indexed: f.indexed,
    chunk_count: f.chunk_count,
    child_count: null,
    needs_reindex: null,
  };
}

// ── Workspace shell ─────────────────────────────────────────────────────

export default function RagPage() {
  return (
    <Suspense fallback={null}>
      <RagWorkspace />
    </Suspense>
  );
}

type IndexJob = {
  status: string;
  message: string | null;
  task_id: string | null;
  startedAt: number;
};

function RagWorkspace() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const fullPath = searchParams.get("path") ?? "";
  const { ws: activeWs, ns: activeNs, sub: activeSub } = splitFullPath(fullPath);
  // Three view levels (Phase 11):
  //   wsLevel  — no workspace selected (top of tree). Lists workspaces.
  //   nsLevel  — workspace selected, no namespace yet. Lists namespaces + root files.
  //   inside   — namespace + (optional) sub-folder. Normal file table.
  const wsLevel = activeWs === "";
  const nsLevel = !wsLevel && activeNs === "";
  const inside = !wsLevel && !nsLevel;

  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [namespaces, setNamespaces] = useState<RagNamespaceSummary[]>([]);
  const [tree, setTree] = useState<RagTreeResponse | null>(null);
  const [treeLoading, setTreeLoading] = useState(false);
  const [status, setStatus] = useState<IngestStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [indexJob, setIndexJob] = useState<IndexJob | null>(null);
  const [showAddWorkspace, setShowAddWorkspace] = useState(false);
  const [removeTargets, setRemoveTargets] = useState<Workspace[] | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // AI Summary cache (keyed by ws+ns+sub)
  const [summaryCache, setSummaryCache] = useState<
    Record<string, RagSummaryResponse>
  >({});
  const [summaryLoading, setSummaryLoading] = useState(false);

  const refreshWorkspaces = useCallback(async () => {
    const r = await listWorkspaces();
    setWorkspaces(r.workspaces);
    return r.workspaces;
  }, []);

  const refreshNamespaces = useCallback(async (ws: string) => {
    if (!ws) {
      setNamespaces([]);
      return [];
    }
    const r = await listRagNamespaces(ws);
    setNamespaces(r.namespaces);
    return r.namespaces;
  }, []);

  const refreshStatus = useCallback(async () => {
    try {
      const s = await getIngestStatus();
      setStatus(s);
    } catch {
      /* non-critical */
    }
  }, []);

  const refreshTree = useCallback(
    async (ws: string, ns: string, sub: string) => {
      setTreeLoading(true);
      try {
        if (!ws) {
          // Top-level — list workspaces as folder entries.
          const wsRows = await listWorkspaces();
          setWorkspaces(wsRows.workspaces);
          const entries = wsRows.workspaces.map(workspaceToTreeEntry);
          setTree({
            namespace: "",
            path: "",
            parent: null,
            entries,
          });
        } else if (!ns) {
          // Workspace level — namespaces + root files.
          const [nsList, rootFiles] = await Promise.all([
            listRagNamespaces(ws),
            listRootFiles(ws).catch(() => ({
              files: [] as RagDocumentSummary[],
            })),
          ]);
          setNamespaces(nsList.namespaces);
          const folderEntries = nsList.namespaces.map(namespaceToTreeEntry);
          const fileEntries = rootFiles.files.map(rootFileToTreeEntry);
          setTree({
            namespace: "",
            path: ws,
            parent: null,
            entries: [...folderEntries, ...fileEntries],
          });
        } else {
          const t = await listRagTree(ws, ns, sub);
          setTree(t);
        }
        setSelected(new Set());
        setErr(null);
      } catch (e) {
        setErr(e instanceof Error ? e.message : String(e));
        setTree({ namespace: ns, path: sub, parent: null, entries: [] });
      } finally {
        setTreeLoading(false);
      }
    },
    [],
  );

  // Initial load — workspaces + status.
  useEffect(() => {
    refreshWorkspaces().catch((e) =>
      setErr(e instanceof Error ? e.message : String(e)),
    );
    refreshStatus();
  }, [refreshWorkspaces, refreshStatus]);

  // Re-fetch tree when path changes.
  useEffect(() => {
    refreshTree(activeWs, activeNs, activeSub);
  }, [activeWs, activeNs, activeSub, refreshTree]);

  // Auto-load any cached AI Summary for the current folder.
  useEffect(() => {
    if (!inside) return;
    const key = `${activeWs}::${activeNs}::${activeSub}`;
    let cancelled = false;
    getCachedRagSummary(activeWs, activeNs, activeSub)
      .then((r) => {
        if (cancelled) return;
        if (r.summary) {
          setSummaryCache((prev) => ({ ...prev, [key]: r.summary! }));
        }
      })
      .catch(() => {
        /* non-critical — user can still click 생성 */
      });
    return () => {
      cancelled = true;
    };
  }, [activeWs, activeNs, activeSub, inside]);

  function navigate(nextPath: string) {
    const sp = new URLSearchParams(searchParams.toString());
    if (nextPath) sp.set("path", nextPath);
    else sp.delete("path");
    const qs = sp.toString();
    router.replace(qs ? `/rag?${qs}` : "/rag");
  }

  // ── Toolbar handlers ──────────────────────────────────────────────────

  async function onCreateFolder() {
    if (wsLevel) {
      // At top level, "create folder" is "Add workspace".
      setShowAddWorkspace(true);
      return;
    }
    const promptMsg = nsLevel
      ? "새 namespace 이름 (영문/숫자/-/_ 만):"
      : "새 폴더 이름:";
    const name = prompt(promptMsg, "");
    if (!name?.trim()) return;
    setBusy(true);
    setErr(null);
    setMsg(null);
    try {
      if (nsLevel) {
        const trimmed = name.trim();
        await createRagNamespace(activeWs, trimmed);
        await refreshNamespaces(activeWs);
        await refreshTree(activeWs, "", "");
      } else {
        const folderSub = activeSub
          ? `${activeSub}/${name.trim()}`
          : name.trim();
        await createRagFolder(activeWs, activeNs, folderSub);
        await refreshTree(activeWs, activeNs, activeSub);
      }
      setMsg(`폴더 ${name.trim()} 생성`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  function onUploadClick() {
    fileInputRef.current?.click();
  }

  async function onFileInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []);
    e.target.value = "";
    if (files.length === 0) return;
    if (wsLevel) {
      setErr("워크스페이스를 먼저 선택하세요.");
      return;
    }
    setBusy(true);
    setErr(null);
    setMsg(null);
    const failed: string[] = [];
    for (const f of files) {
      try {
        if (nsLevel) {
          await uploadRootFile(activeWs, f);
        } else {
          await uploadRagDocument(activeWs, activeNs, f, activeSub);
        }
      } catch (err) {
        failed.push(
          `${f.name}: ${err instanceof Error ? err.message : String(err)}`,
        );
      }
    }
    await refreshTree(activeWs, activeNs, activeSub);
    if (failed.length === 0) setMsg(`${files.length}개 업로드`);
    else setErr(`업로드 실패: ${failed.join("; ")}`);
    setBusy(false);
  }

  async function onDeleteSelected() {
    if (selected.size === 0) return;
    const items = Array.from(selected);
    const entries = items
      .map((name) => tree?.entries.find((e) => e.name === name))
      .filter((e): e is RagTreeEntry => !!e);

    // At ws/ns level, folders (= workspaces or namespaces) cannot be
    // deleted from the file table. Users delete those via the explorer
    // pane's kebab menus / Danger UI in a future PR.
    if ((wsLevel || nsLevel) && entries.some((e) => e.type === "folder")) {
      return;
    }

    if (!confirm(`선택된 ${entries.length}개 항목을 삭제할까요?`)) return;

    setBusy(true);
    setErr(null);
    setMsg(null);
    const failed: string[] = [];
    for (const entry of entries) {
      try {
        if (nsLevel) {
          // Only root files reach here (workspace folders blocked above).
          await deleteRootFile(activeWs, entry.name);
        } else if (inside) {
          const itemSub = activeSub
            ? `${activeSub}/${entry.name}`
            : entry.name;
          if (entry.type === "folder") {
            await deleteRagFolder(activeWs, activeNs, itemSub);
          } else {
            await deleteRagDocument(activeWs, activeNs, itemSub);
          }
        }
      } catch (err) {
        failed.push(
          `${entry.name}: ${err instanceof Error ? err.message : String(err)}`,
        );
      }
    }
    await refreshTree(activeWs, activeNs, activeSub);
    if (failed.length === 0) setMsg(`${entries.length}개 삭제`);
    else setErr(`일부 실패: ${failed.join("; ")}`);
    setBusy(false);
  }

  async function onOpenInExplorer() {
    if (wsLevel) {
      setErr("워크스페이스를 먼저 선택하세요.");
      return;
    }
    setBusy(true);
    setErr(null);
    setMsg(null);
    try {
      const r = nsLevel
        ? await openRagRoot(activeWs)
        : await openRagFolder(activeWs, activeNs, activeSub);
      if (!r.opened) setErr(`탐색기 열기 실패 (경로: ${r.abs_path})`);
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
      const r = await triggerIngest({
        notion: false,
        force: false,
        dry_run: dryRun,
        workspace: activeWs || "default",
        namespace: activeNs || "default",
      });
      setIndexJob({
        status: r.status,
        message: r.message,
        task_id: r.task_id,
        startedAt: Date.now(),
      });
      setMsg(`Re-index ${dryRun ? "(dry run) " : ""}— task ${r.task_id}`);
      setTimeout(() => {
        refreshTree(activeWs, activeNs, activeSub);
        refreshStatus();
        if (activeWs) refreshNamespaces(activeWs);
      }, 2000);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  function toggleSelect(name: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  function onToggleSelectAll() {
    if (!tree) return;
    if (selected.size === tree.entries.length && tree.entries.length > 0) {
      setSelected(new Set());
    } else {
      setSelected(new Set(tree.entries.map((e) => e.name)));
    }
  }

  // ── AI Summary ────────────────────────────────────────────────────────

  const summaryKey = `${activeWs}::${activeNs}::${activeSub}`;
  const cachedSummary = summaryCache[summaryKey];

  async function onGenerateSummary() {
    if (!inside) return;
    setSummaryLoading(true);
    setErr(null);
    try {
      const r = await summarizeRagPath(activeWs, activeNs, {
        path: activeSub,
        lang: "ko",
        sample_size: 20,
      });
      setSummaryCache((prev) => ({ ...prev, [summaryKey]: r }));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setSummaryLoading(false);
    }
  }

  function onClearSummary() {
    setSummaryCache((prev) => {
      const next = { ...prev };
      delete next[summaryKey];
      return next;
    });
  }

  // ── Derived ───────────────────────────────────────────────────────────

  const allSelected =
    !!tree && tree.entries.length > 0 && selected.size === tree.entries.length;
  const breadcrumbParts = useMemo(
    () => (fullPath ? fullPath.split("/") : []),
    [fullPath],
  );

  // Selected items distinguish folders vs files for delete-button logic.
  const selectedEntries = useMemo(() => {
    if (!tree) return [] as RagTreeEntry[];
    return Array.from(selected)
      .map((name) => tree.entries.find((e) => e.name === name))
      .filter((e): e is RagTreeEntry => !!e);
  }, [selected, tree]);
  const selectedHasFolder = selectedEntries.some((e) => e.type === "folder");
  const canDelete =
    selectedEntries.length > 0 &&
    !((wsLevel || nsLevel) && selectedHasFolder);

  // Toolbar context: at wsLevel "create folder" becomes "Add workspace";
  // at nsLevel it's "Create namespace"; inside a namespace it's "New folder".
  const createBtnLabel = wsLevel
    ? "+ Add Workspace"
    : nsLevel
      ? "Namespace 생성"
      : "새 폴더";
  const createBtnIcon = wsLevel ? "🗂" : nsLevel ? "📦" : "📁";
  const createBtnTitle = wsLevel
    ? "사용자 폴더를 RAG 워크스페이스로 등록"
    : nsLevel
      ? "namespace 생성 — 영문/숫자/-/_ 만"
      : "현재 폴더 안에 새 하위 폴더";

  return (
    <div className="-mx-6 -my-8 flex flex-col bg-[#f8fafc] text-[13px] text-slate-800">
      {/* Top bar */}
      <div className="flex items-center justify-between gap-3 border-b border-slate-200 bg-white px-4 py-2">
        <Breadcrumb
          parts={breadcrumbParts}
          workspaces={workspaces}
          onNavigate={navigate}
        />
        <IndexBadge job={indexJob} status={status} />
      </div>

      {/* 3-column workspace */}
      <div
        className="grid min-h-[calc(100vh-160px)]"
        style={{ gridTemplateColumns: "260px minmax(0, 1fr) 320px" }}
      >
        <ExplorerPane
          activePath={fullPath}
          onNavigate={navigate}
          workspaces={workspaces}
        />

        {/* Center */}
        <section className="flex min-w-0 flex-col border-x border-slate-200 bg-white">
          <div className="flex flex-wrap items-center gap-1 border-b border-slate-200 px-3 py-1.5">
            {wsLevel ? (
              <>
                {/* Workspace-management toolbar — visible only at the
                    top "Workspaces" view. Add/Remove are display-only:
                    source folders on disk are never touched. */}
                <ToolbarButton
                  onClick={() => setShowAddWorkspace(true)}
                  disabled={busy}
                  icon="🗂"
                  tone="primary"
                  title="사용자 폴더를 RAG 워크스페이스로 등록"
                >
                  + Add Workspace
                </ToolbarButton>
                {(() => {
                  const wsBySlug = new Map(
                    workspaces.map((w) => [w.slug, w]),
                  );
                  const selectedWs = Array.from(selected)
                    .map((slug) => wsBySlug.get(slug))
                    .filter(
                      (w): w is Workspace => !!w && !w.is_builtin,
                    );
                  const removeDisabled = busy || selectedWs.length === 0;
                  return (
                    <ToolbarButton
                      onClick={() => setRemoveTargets(selectedWs)}
                      disabled={removeDisabled}
                      icon="−"
                      tone="danger"
                      title={
                        selectedWs.length === 0
                          ? "워크스페이스를 선택하면 활성화됩니다 (built-in 제외)"
                          : "선택한 워크스페이스를 트리에서 제거"
                      }
                    >
                      Remove
                      {selectedWs.length > 0 ? ` (${selectedWs.length})` : ""}
                    </ToolbarButton>
                  );
                })()}
                <div className="ml-auto flex items-center gap-1">
                  <ToolbarButton
                    onClick={() =>
                      refreshTree(activeWs, activeNs, activeSub)
                    }
                    disabled={busy || treeLoading}
                    title="새로 고침"
                  >
                    ↻
                  </ToolbarButton>
                </div>
              </>
            ) : (
              <>
                <ToolbarButton
                  onClick={onCreateFolder}
                  disabled={busy}
                  icon={createBtnIcon}
                  title={createBtnTitle}
                >
                  {createBtnLabel}
                </ToolbarButton>
                <ToolbarButton
                  onClick={onUploadClick}
                  disabled={busy}
                  icon="⬆"
                  title="현재 폴더에 업로드"
                >
                  업로드
                </ToolbarButton>
                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  accept=".md,.txt,.pdf"
                  className="hidden"
                  onChange={onFileInputChange}
                />
                <ToolbarButton
                  onClick={onDeleteSelected}
                  disabled={busy || !canDelete}
                  icon="🗑"
                  tone="danger"
                  title={
                    nsLevel && selectedHasFolder
                      ? "namespace 는 namespace 자체 삭제로 (Phase 11 미지원)"
                      : "선택 항목 삭제"
                  }
                >
                  삭제
                  {selectedEntries.length > 0
                    ? ` (${selectedEntries.length})`
                    : ""}
                </ToolbarButton>
                <ToolbarButton
                  onClick={onOpenInExplorer}
                  disabled={busy}
                  icon="🗂"
                  title="현재 폴더를 OS 탐색기에서 열기"
                >
                  Explorer
                </ToolbarButton>
                <div className="ml-auto flex items-center gap-1">
                  <ToolbarButton
                    onClick={() =>
                      refreshTree(activeWs, activeNs, activeSub)
                    }
                    disabled={busy || treeLoading}
                    title="새로 고침"
                  >
                    ↻
                  </ToolbarButton>
                  <ToolbarButton
                    onClick={() => onReindex(true)}
                    disabled={busy}
                  >
                    Dry run
                  </ToolbarButton>
                  <ToolbarButton
                    onClick={() => onReindex(false)}
                    disabled={busy}
                    tone="primary"
                  >
                    Re-index
                  </ToolbarButton>
                </div>
              </>
            )}
          </div>

          {(err || msg) && (
            <div className="border-b border-slate-200">
              {err && (
                <Banner tone="error" onClose={() => setErr(null)}>
                  {err}
                </Banner>
              )}
              {msg && (
                <Banner tone="success" onClose={() => setMsg(null)}>
                  {msg}
                </Banner>
              )}
            </div>
          )}

          <div className="flex-1 overflow-auto">
            <FileTable
              tree={tree}
              loading={treeLoading}
              wsLevel={wsLevel}
              nsLevel={nsLevel}
              breadcrumbParts={breadcrumbParts}
              workspaces={workspaces}
              selected={selected}
              allSelected={allSelected}
              onToggleAll={onToggleSelectAll}
              onToggleOne={toggleSelect}
              onNavigateUp={() =>
                navigate(breadcrumbParts.slice(0, -1).join("/"))
              }
              onOpenFolder={(entry) =>
                navigate(fullPath ? `${fullPath}/${entry.name}` : entry.name)
              }
            />
          </div>

          {!wsLevel && (
            <div className="border-t border-slate-200 bg-slate-50 px-3 py-2">
              <RagDocumentDropzone
                wsSlug={activeWs}
                namespace={nsLevel ? "" : activeNs}
                path={nsLevel ? "" : activeSub}
                compact
                onUploaded={() => refreshTree(activeWs, activeNs, activeSub)}
                uploadAtRoot={nsLevel}
              />
            </div>
          )}
        </section>

        <SummaryPane
          inside={inside}
          activeWs={activeWs}
          activeNs={activeNs}
          activeSub={activeSub}
          summary={cachedSummary ?? null}
          loading={summaryLoading}
          onGenerate={onGenerateSummary}
          onClear={onClearSummary}
        />
      </div>

      {showAddWorkspace && (
        <AddWorkspaceModal
          onClose={() => setShowAddWorkspace(false)}
          onCreated={async (ws) => {
            setShowAddWorkspace(false);
            await refreshWorkspaces();
            navigate(ws.slug);
          }}
        />
      )}

      {removeTargets && removeTargets.length > 0 && (
        <RemoveWorkspaceModal
          workspaces={removeTargets}
          onClose={() => setRemoveTargets(null)}
          onRemoved={async () => {
            setRemoveTargets(null);
            await refreshWorkspaces();
            await refreshTree(activeWs, activeNs, activeSub);
            setSelected(new Set());
            setMsg(
              `워크스페이스 ${removeTargets.length}개 제거됨`,
            );
          }}
        />
      )}
    </div>
  );
}

// ── Sub-components ──────────────────────────────────────────────────────

function Breadcrumb({
  parts,
  workspaces,
  onNavigate,
}: {
  parts: string[];
  workspaces: Workspace[];
  onNavigate: (path: string) => void;
}) {
  // First segment is the workspace slug — display the label instead.
  const wsBySlug = new Map(workspaces.map((w) => [w.slug, w]));
  return (
    <nav className="flex flex-wrap items-center gap-0.5 text-xs">
      <button
        type="button"
        onClick={() => onNavigate("")}
        className="rounded px-1 py-0.5 font-medium text-slate-700 hover:bg-slate-100"
      >
        Workspaces
      </button>
      {parts.map((seg, i) => {
        const upTo = parts.slice(0, i + 1).join("/");
        const isLast = i === parts.length - 1;
        const display =
          i === 0 ? (wsBySlug.get(seg)?.label ?? seg) : seg;
        return (
          <span key={upTo} className="flex items-center gap-0.5">
            <span className="text-slate-300">/</span>
            {isLast ? (
              <span
                className={
                  i === 0
                    ? "rounded px-1 py-0.5 font-medium text-slate-900"
                    : "rounded px-1 py-0.5 font-mono text-slate-900"
                }
              >
                {display}
              </span>
            ) : (
              <button
                type="button"
                onClick={() => onNavigate(upTo)}
                className={
                  i === 0
                    ? "rounded px-1 py-0.5 font-medium text-slate-700 hover:bg-slate-100"
                    : "rounded px-1 py-0.5 font-mono text-slate-700 hover:bg-slate-100"
                }
              >
                {display}
              </button>
            )}
          </span>
        );
      })}
    </nav>
  );
}

function IndexBadge({
  job,
  status,
}: {
  job: IndexJob | null;
  status: IngestStatus | null;
}) {
  let label = "idle";
  let tone = "bg-slate-100 text-slate-600";
  if (job) {
    if (job.status === "running" || job.status === "queued") {
      label = "indexing";
      tone = "bg-amber-100 text-amber-800";
    } else if (job.status === "failed") {
      label = "failed";
      tone = "bg-rose-100 text-rose-800";
    } else if (job.status === "completed") {
      label = "completed";
      tone = "bg-emerald-100 text-emerald-800";
    }
  }
  const docs = status?.document_count ?? 0;
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="text-slate-500">{docs} files</span>
      <span
        className={`rounded-full px-2 py-0.5 font-medium ${tone}`}
        title={job?.message ?? ""}
      >
        {label}
      </span>
    </div>
  );
}

function ExplorerPane({
  activePath,
  onNavigate,
  workspaces,
}: {
  activePath: string;
  onNavigate: (p: string) => void;
  workspaces: Workspace[];
}) {
  return (
    <aside className="flex min-h-0 flex-col overflow-hidden bg-white">
      <div className="flex-1 overflow-y-auto px-1 py-1.5">
        <div className="px-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
          Workspaces
        </div>
        <FolderTree
          activePath={activePath}
          onSelect={onNavigate}
          rootWorkspaces={workspaces}
        />
      </div>
    </aside>
  );
}

// Folder tree: lazy-loaded. Top-level = workspaces; one level down =
// namespaces inside the workspace; below = folders. Root files are NOT
// in the tree — too noisy for navigation.
function FolderTree({
  activePath,
  onSelect,
  rootWorkspaces,
}: {
  activePath: string;
  onSelect: (p: string) => void;
  rootWorkspaces: Workspace[];
}) {
  const [cache, setCache] = useState<Record<string, RagTreeEntry[]>>({});
  const [labels, setLabels] = useState<Record<string, string>>({});
  const [expanded, setExpanded] = useState<Set<string>>(new Set([""]));
  const [loading, setLoading] = useState<Set<string>>(new Set());

  const loadPath = useCallback(
    async (fullPath: string) => {
      if (cache[fullPath]) return;
      setLoading((prev) => new Set(prev).add(fullPath));
      try {
        if (!fullPath) {
          const r = await listWorkspaces();
          setCache((prev) => ({
            ...prev,
            [""]: r.workspaces.map(workspaceToTreeEntry),
          }));
          setLabels((prev) => {
            const next = { ...prev };
            for (const w of r.workspaces) next[w.slug] = w.label;
            return next;
          });
        } else {
          const { ws, ns, sub } = splitFullPath(fullPath);
          if (!ns) {
            // Workspace level — list its namespaces.
            const r = await listRagNamespaces(ws);
            setCache((prev) => ({
              ...prev,
              [fullPath]: r.namespaces.map(namespaceToTreeEntry),
            }));
          } else {
            const r = await listRagTree(ws, ns, sub);
            const folders = r.entries.filter((e) => e.type === "folder");
            setCache((prev) => ({ ...prev, [fullPath]: folders }));
          }
        }
      } catch {
        /* swallow — main view shows the error */
      } finally {
        setLoading((prev) => {
          const next = new Set(prev);
          next.delete(fullPath);
          return next;
        });
      }
    },
    [cache],
  );

  useEffect(() => {
    if (cache[""]) return;
    setCache((prev) => ({
      ...prev,
      [""]: rootWorkspaces.map(workspaceToTreeEntry),
    }));
    setLabels((prev) => {
      const next = { ...prev };
      for (const w of rootWorkspaces) next[w.slug] = w.label;
      return next;
    });
  }, [rootWorkspaces, cache]);

  useEffect(() => {
    setExpanded((prev) => {
      const next = new Set(prev);
      next.add("");
      if (activePath) {
        const parts = activePath.split("/");
        for (let i = 1; i < parts.length; i++) {
          next.add(parts.slice(0, i).join("/"));
        }
      }
      return next;
    });
    if (activePath) {
      const parts = activePath.split("/");
      for (let i = 1; i < parts.length; i++) {
        loadPath(parts.slice(0, i).join("/"));
      }
    }
  }, [activePath, loadPath]);

  function toggleExpand(fullPath: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(fullPath)) next.delete(fullPath);
      else {
        next.add(fullPath);
        loadPath(fullPath);
      }
      return next;
    });
  }

  return (
    <div className="select-none font-mono text-xs">
      <TreeNode
        label="Workspaces"
        icon="🗂"
        path=""
        depth={0}
        cache={cache}
        labels={labels}
        loading={loading}
        expanded={expanded}
        activePath={activePath}
        onToggle={toggleExpand}
        onSelect={onSelect}
      />
    </div>
  );
}

function TreeNode({
  label,
  icon,
  path,
  depth,
  cache,
  labels,
  loading,
  expanded,
  activePath,
  onToggle,
  onSelect,
}: {
  label: string;
  icon?: string;
  path: string;
  depth: number;
  cache: Record<string, RagTreeEntry[]>;
  labels: Record<string, string>;
  loading: Set<string>;
  expanded: Set<string>;
  activePath: string;
  onToggle: (p: string) => void;
  onSelect: (p: string) => void;
}) {
  const isExpanded = expanded.has(path);
  const isActive = activePath === path;
  const children = cache[path];
  const isLoading = loading.has(path);
  const indent = depth * 12;
  return (
    <>
      <div
        className={`group flex items-center gap-1 rounded px-1 py-0.5 ${
          isActive ? "bg-sky-100 text-sky-900" : "hover:bg-slate-100"
        }`}
        style={{ paddingLeft: indent + 4 }}
      >
        <button
          type="button"
          onClick={() => onToggle(path)}
          className="flex h-4 w-4 items-center justify-center text-slate-400 hover:text-slate-700"
          aria-label={isExpanded ? "Collapse" : "Expand"}
        >
          {isExpanded ? "▾" : "▸"}
        </button>
        <button
          type="button"
          onClick={() => onSelect(path)}
          className="min-w-0 flex-1 truncate text-left"
        >
          {icon ?? "📁"} {label}
        </button>
      </div>
      {isExpanded && (
        <div>
          {isLoading && !children && (
            <div
              className="px-2 py-0.5 text-[10px] text-slate-400"
              style={{ paddingLeft: indent + 24 }}
            >
              ...
            </div>
          )}
          {children && children.length === 0 && (
            <div
              className="px-2 py-0.5 text-[10px] text-slate-400"
              style={{ paddingLeft: indent + 24 }}
            >
              (no folders)
            </div>
          )}
          {children?.map((entry) => {
            const childPath = path ? `${path}/${entry.name}` : entry.name;
            // Top-level entry (depth 0 → child) is a workspace; show
            // human label, not slug.
            const childLabel =
              depth === 0
                ? (labels[entry.name] ?? entry.name)
                : entry.name;
            const childIcon = depth === 0 ? "📦" : undefined;
            return (
              <TreeNode
                key={childPath}
                label={childLabel}
                icon={childIcon}
                path={childPath}
                depth={depth + 1}
                cache={cache}
                labels={labels}
                loading={loading}
                expanded={expanded}
                activePath={activePath}
                onToggle={onToggle}
                onSelect={onSelect}
              />
            );
          })}
        </div>
      )}
    </>
  );
}

function FileTable({
  tree,
  loading,
  wsLevel,
  nsLevel,
  breadcrumbParts,
  workspaces,
  selected,
  allSelected,
  onToggleAll,
  onToggleOne,
  onNavigateUp,
  onOpenFolder,
}: {
  tree: RagTreeResponse | null;
  loading: boolean;
  wsLevel: boolean;
  nsLevel: boolean;
  breadcrumbParts: string[];
  workspaces: Workspace[];
  selected: Set<string>;
  allSelected: boolean;
  onToggleAll: () => void;
  onToggleOne: (name: string) => void;
  onNavigateUp: () => void;
  onOpenFolder: (entry: RagTreeEntry) => void;
}) {
  if (!tree && loading) {
    return (
      <div className="flex h-32 items-center justify-center text-xs text-slate-400">
        Loading...
      </div>
    );
  }
  if (!tree) {
    return (
      <div className="flex h-32 items-center justify-center text-xs text-slate-400">
        —
      </div>
    );
  }
  const empty = tree.entries.length === 0;
  return (
    <table className="w-full border-collapse text-xs">
      <thead className="sticky top-0 z-10 bg-slate-50 text-left text-[11px] font-medium text-slate-600">
        <tr>
          <th className="w-8 border-b border-slate-200 px-2 py-1.5">
            <input
              type="checkbox"
              checked={allSelected}
              onChange={onToggleAll}
              aria-label="전체 선택"
            />
          </th>
          <th className="border-b border-slate-200 px-2 py-1.5 font-medium">
            Name
          </th>
          <th className="w-20 border-b border-slate-200 px-2 py-1.5 font-medium">
            Size
          </th>
          <th className="w-36 border-b border-slate-200 px-2 py-1.5 font-medium">
            Modified
          </th>
          <th className="w-20 border-b border-slate-200 px-2 py-1.5 font-medium">
            Status
          </th>
        </tr>
      </thead>
      <tbody>
        {breadcrumbParts.length > 0 && (
          <tr
            className="cursor-pointer hover:bg-slate-50"
            onClick={onNavigateUp}
          >
            <td className="border-b border-slate-100 px-2 py-1.5"></td>
            <td className="border-b border-slate-100 px-2 py-1.5 font-mono text-slate-500">
              📁 ..
            </td>
            <td
              colSpan={3}
              className="border-b border-slate-100 px-2 py-1.5 text-[11px] text-slate-400"
            >
              상위 폴더
            </td>
          </tr>
        )}
        {empty && (
          <tr>
            <td
              colSpan={5}
              className="px-2 py-12 text-center text-xs text-slate-400"
            >
              {wsLevel ? (
                <>
                  등록된 워크스페이스가 없습니다. 상단{" "}
                  <code>+ Add Workspace</code> 로 사용자 폴더를 추가하세요.
                </>
              ) : nsLevel ? (
                <>
                  비어있습니다. 상단 <code>📦 Namespace 생성</code> 또는{" "}
                  <code>⬆ 업로드</code> 로 시작하세요.
                </>
              ) : (
                "빈 폴더"
              )}
            </td>
          </tr>
        )}
        {tree.entries.map((entry) => {
          // Top-level rows are workspaces — surface label not slug.
          const wsBySlug = new Map(workspaces.map((w) => [w.slug, w]));
          const ws = wsLevel ? wsBySlug.get(entry.name) : undefined;
          return (
            <FileRow
              key={entry.name}
              entry={entry}
              displayLabel={ws ? ws.label : entry.name}
              detail={ws ? ws.abs_path : undefined}
              selected={selected.has(entry.name)}
              onToggle={() => onToggleOne(entry.name)}
              onOpenFolder={() => onOpenFolder(entry)}
            />
          );
        })}
      </tbody>
    </table>
  );
}

function FileRow({
  entry,
  displayLabel,
  detail,
  selected,
  onToggle,
  onOpenFolder,
}: {
  entry: RagTreeEntry;
  displayLabel?: string;
  detail?: string | undefined;
  selected: boolean;
  onToggle: () => void;
  onOpenFolder: () => void;
}) {
  const isFolder = entry.type === "folder";
  const label = displayLabel ?? entry.name;
  return (
    <tr
      className={`group ${selected ? "bg-sky-50" : "hover:bg-slate-50"}`}
      style={{ height: 30 }}
    >
      <td className="border-b border-slate-100 px-2">
        <input
          type="checkbox"
          checked={selected}
          onChange={onToggle}
          onClick={(e) => e.stopPropagation()}
        />
      </td>
      <td
        className={`border-b border-slate-100 px-2 font-mono text-xs ${isFolder ? "cursor-pointer text-slate-800" : "text-slate-700"}`}
        onClick={isFolder ? onOpenFolder : undefined}
        title={detail}
      >
        {isFolder ? "📁" : "📄"} {label}
        {detail && (
          <span className="ml-2 font-normal text-[10px] text-slate-400">
            {detail}
          </span>
        )}
      </td>
      <td className="border-b border-slate-100 px-2 tabular-nums text-slate-500">
        {isFolder ? "—" : formatSize(entry.size_bytes ?? 0)}
      </td>
      <td className="border-b border-slate-100 px-2 text-[11px] text-slate-500">
        {entry.modified_at?.slice(0, 16).replace("T", " ") ?? "—"}
      </td>
      <td className="border-b border-slate-100 px-2">
        {isFolder ? (
          entry.needs_reindex ? (
            <span
              className="rounded-full bg-amber-100 px-1.5 py-0 text-[10px] text-amber-800"
              title="이 폴더 안에 인덱싱되지 않은 파일 또는 수정된 파일이 있습니다"
            >
              Pending
            </span>
          ) : (
            <span className="text-slate-400">—</span>
          )
        ) : entry.indexed ? (
          <span className="rounded-full bg-emerald-100 px-1.5 py-0 text-[10px] text-emerald-800">
            Ready
          </span>
        ) : (
          <span className="rounded-full bg-amber-100 px-1.5 py-0 text-[10px] text-amber-800">
            Pending
          </span>
        )}
      </td>
    </tr>
  );
}

function SummaryPane({
  inside,
  activeWs,
  activeNs,
  activeSub,
  summary,
  loading,
  onGenerate,
  onClear,
}: {
  inside: boolean;
  activeWs: string;
  activeNs: string;
  activeSub: string;
  summary: RagSummaryResponse | null;
  loading: boolean;
  onGenerate: () => void;
  onClear: () => void;
}) {
  return (
    <aside className="flex min-h-0 flex-col overflow-y-auto bg-white">
      <div className="flex items-center justify-between border-b border-slate-200 px-3 py-2">
        <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
          AI Summary
        </div>
        {summary && (
          <button
            type="button"
            onClick={onClear}
            className="text-[10px] text-slate-400 hover:text-slate-700"
          >
            지우기
          </button>
        )}
      </div>
      <div className="space-y-3 px-3 py-3 text-xs">
        {!inside ? (
          <div className="rounded border border-slate-200 bg-slate-50 px-2 py-2 text-[11px] text-slate-500">
            namespace 안으로 들어가야 AI Summary 를 생성할 수 있습니다.
          </div>
        ) : (
          <>
            <div className="text-[11px] text-slate-500">
              현재 폴더:{" "}
              <span className="font-mono text-slate-800">
                {activeSub
                  ? `${activeWs}/${activeNs}/${activeSub}`
                  : `${activeWs}/${activeNs}`}
              </span>
            </div>
            {summary && (
              <div className="text-[10px] text-slate-400">
                생성: {summary.generated_at.slice(0, 16).replace("T", " ")}
                {summary.is_stale && (
                  <span
                    className="ml-1.5 rounded-full bg-amber-100 px-1.5 py-0 text-[10px] text-amber-800"
                    title="이 폴더가 재인덱싱된 후 summary 가 갱신되지 않았습니다"
                  >
                    재인덱싱 후 갱신 필요
                  </span>
                )}
              </div>
            )}
            <button
              type="button"
              onClick={onGenerate}
              disabled={loading}
              className={`w-full rounded border px-2 py-1.5 text-xs font-medium disabled:opacity-50 ${
                summary?.is_stale
                  ? "border-amber-300 bg-amber-50 text-amber-800 hover:bg-amber-100"
                  : "border-slate-300 bg-white hover:bg-slate-50"
              }`}
            >
              {loading
                ? "생성 중..."
                : !summary
                  ? "✨ AI Summary 생성"
                  : summary.is_stale
                    ? "Update ⚠"
                    : "다시 생성"}
            </button>
            {summary && <SummaryBody text={summary.summary} />}
          </>
        )}
      </div>
    </aside>
  );
}

function SummaryBody({ text }: { text: string }) {
  const lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
  return (
    <ul className="space-y-1 text-[12px] leading-relaxed text-slate-700">
      {lines.map((line, i) => {
        const stripped = line.replace(/^[-*]\s*/, "");
        const html = stripped.replace(
          /\*\*(.+?)\*\*/g,
          '<strong class="font-semibold text-slate-900">$1</strong>',
        );
        return (
          <li
            key={i}
            className="flex gap-1.5 before:content-['•'] before:text-slate-400"
          >
            <span dangerouslySetInnerHTML={{ __html: html }} />
          </li>
        );
      })}
    </ul>
  );
}

function ToolbarButton({
  children,
  onClick,
  disabled,
  icon,
  tone = "default",
  title,
}: {
  children: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
  icon?: string;
  tone?: "default" | "primary" | "danger";
  title?: string;
}) {
  // NOTE: base `className` no longer hard-codes a background — Tailwind's
  // generated CSS order would otherwise let `bg-white` win over the
  // tone's `bg-*`, which made primary buttons render white-on-white.
  const toneCls =
    tone === "primary"
      ? "bg-sky-600 text-white hover:bg-sky-700 border-sky-700"
      : tone === "danger"
        ? "bg-white border-rose-300 text-rose-700 hover:bg-rose-50"
        : "bg-white border-slate-300 text-slate-700 hover:bg-slate-50";
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`inline-flex items-center gap-1 rounded border px-2 py-1 text-xs font-medium disabled:opacity-50 ${toneCls}`}
    >
      {icon && <span>{icon}</span>}
      {children}
    </button>
  );
}

function Banner({
  tone,
  children,
  onClose,
}: {
  tone: "error" | "success";
  children: React.ReactNode;
  onClose: () => void;
}) {
  const cls =
    tone === "error"
      ? "bg-rose-50 text-rose-800 [&>button]:text-rose-500 [&>button:hover]:text-rose-700"
      : "bg-emerald-50 text-emerald-800 [&>button]:text-emerald-500 [&>button:hover]:text-emerald-700";
  return (
    <div className={`flex items-start gap-2 px-3 py-1.5 text-xs ${cls}`}>
      <span>{tone === "error" ? "⚠" : "✓"}</span>
      <span className="font-mono">{children}</span>
      <button type="button" onClick={onClose} className="ml-auto">
        ✕
      </button>
    </div>
  );
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
