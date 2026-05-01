"use client";

import { useCallback, useState } from "react";
import { useDropzone, type FileRejection } from "react-dropzone";

import { uploadRagDocument, uploadRootFile } from "@/lib/api";

type Props = {
  namespace: string;
  onUploaded: () => void;
  path?: string;
  compact?: boolean;
  /**
   * When true, files are uploaded to the workspace root (namespace + path
   * are ignored). Used by the RAG tab when the user is at the top level.
   */
  uploadAtRoot?: boolean;
};

const ACCEPT = {
  "text/markdown": [".md"],
  "text/plain": [".txt"],
  "application/pdf": [".pdf"],
};

export default function RagDocumentDropzone({
  namespace,
  onUploaded,
  path = "",
  compact = false,
  uploadAtRoot = false,
}: Props) {
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<string | null>(null);
  const [errors, setErrors] = useState<string[]>([]);

  const onDrop = useCallback(
    async (accepted: File[], rejected: FileRejection[]) => {
      setErrors(rejected.map((r) => `${r.file.name} — ${r.errors[0]?.message ?? "거부됨"}`));
      if (accepted.length === 0) return;
      setBusy(true);
      const failed: string[] = [];
      for (let i = 0; i < accepted.length; i += 1) {
        const f = accepted[i];
        setProgress(`(${i + 1}/${accepted.length}) ${f.name} 업로드 중...`);
        try {
          if (uploadAtRoot) {
            await uploadRootFile(f);
          } else {
            await uploadRagDocument(namespace, f, path);
          }
        } catch (err) {
          failed.push(`${f.name} — ${err instanceof Error ? err.message : String(err)}`);
        }
      }
      setProgress(null);
      setBusy(false);
      if (failed.length > 0) {
        setErrors((prev) => [...prev, ...failed]);
      }
      onUploaded();
    },
    [namespace, onUploaded, path, uploadAtRoot],
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: ACCEPT,
    disabled: busy,
    maxSize: 25 * 1024 * 1024,
  });

  if (compact) {
    return (
      <div className="space-y-1">
        <div
          {...getRootProps()}
          className={`flex cursor-pointer items-center justify-between rounded border border-dashed px-2.5 py-1.5 text-xs transition ${
            isDragActive
              ? "border-emerald-400 bg-emerald-50"
              : "border-slate-300 bg-white hover:bg-slate-50"
          } ${busy ? "opacity-60" : ""}`}
        >
          <input {...getInputProps()} />
          <span className="text-slate-600">
            {isDragActive
              ? "여기에 놓으세요"
              : "여기로 드래그하거나 클릭해서 업로드"}
          </span>
          <span className="text-[10px] text-slate-400">
            .md · .txt · .pdf · ≤25MB
            {path && ` · /${path}`}
          </span>
        </div>
        {progress && <p className="text-[10px] text-slate-500">{progress}</p>}
        {errors.length > 0 && (
          <ul className="space-y-0.5 text-[10px] text-rose-700">
            {errors.map((e, i) => (
              <li key={i}>• {e}</li>
            ))}
          </ul>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div
        {...getRootProps()}
        className={`flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed px-6 py-8 text-center transition ${
          isDragActive
            ? "border-emerald-400 bg-emerald-50"
            : "border-slate-300 bg-slate-50 hover:bg-white"
        } ${busy ? "opacity-60" : ""}`}
      >
        <input {...getInputProps()} />
        <p className="text-sm font-medium text-slate-700">
          {isDragActive
            ? "여기에 놓으세요"
            : "파일을 드래그하거나 클릭해서 업로드"}
        </p>
        <p className="mt-1 text-xs text-slate-500">
          .md · .txt · .pdf — 최대 25 MB · namespace{" "}
          <code className="rounded bg-white px-1 py-0.5">{namespace}</code>
          {path && (
            <>
              {" "}· 경로{" "}
              <code className="rounded bg-white px-1 py-0.5">/{path}</code>
            </>
          )}
        </p>
      </div>
      {progress && <p className="text-xs text-slate-500">{progress}</p>}
      {errors.length > 0 && (
        <ul className="space-y-1 text-xs text-rose-700">
          {errors.map((e, i) => (
            <li key={i}>• {e}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
