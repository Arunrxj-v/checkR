import { useRef, useState } from "react";

import { Icon } from "@/components/ui/Icon";
import { Modal } from "@/components/ui/Modal";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { Spinner } from "@/components/ui/Spinner";
import { submissionApi } from "@/lib/api";
import type { Submission } from "@/lib/types";

const ACCEPT = ".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg";

interface UploadModalProps {
  open: boolean;
  onClose: () => void;
  examId: string;
  examTitle?: string;
  onUploaded: (submissions: Submission[]) => void;
}

export function UploadModal({ open, onClose, examId, examTitle, onUploaded }: UploadModalProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [name, setName] = useState("");
  const [roll, setRoll] = useState("");
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  const reset = () => {
    setFiles([]);
    setName("");
    setRoll("");
    setProgress(null);
    setError(null);
  };

  const addFiles = (incoming: FileList | null) => {
    if (!incoming) return;
    setError(null);
    setFiles((prev) => [...prev, ...Array.from(incoming)]);
  };

  const submit = async () => {
    if (files.length === 0) {
      setError("Choose at least one answer-sheet file.");
      return;
    }
    setError(null);
    setProgress(0);
    try {
      const created = await submissionApi.upload(
        examId,
        files,
        files.length === 1 ? { student_name: name || undefined, student_roll: roll || undefined } : undefined,
        setProgress,
      );
      onUploaded(created);
      reset();
      onClose();
    } catch (err) {
      setProgress(null);
      setError(err instanceof Error ? err.message : "Upload failed.");
    }
  };

  return (
    <Modal
      open={open}
      onClose={() => {
        if (progress !== null) return;
        reset();
        onClose();
      }}
      title="Upload answer sheets"
      description={examTitle ? `Scripts are queued for processing against “${examTitle}”.` : undefined}
      width="max-w-xl"
      footer={
        <>
          <button type="button" className="btn-secondary px-space-md py-1.5  text-label-md" onClick={() => { reset(); onClose(); }} disabled={progress !== null}>
            Cancel
          </button>
          <button type="button" className="btn-primary px-space-md py-1.5  text-label-md" onClick={submit} disabled={progress !== null || files.length === 0}>
            {progress !== null ? <Spinner className="h-3.5 w-3.5 border-white/40 border-t-white" /> : <Icon name="cloud_upload" className="text-[16px]" />}
            Upload {files.length > 0 ? `(${files.length})` : ""}
          </button>
        </>
      }
    >
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          addFiles(e.dataTransfer.files);
        }}
        className={`flex flex-col items-center gap-space-xs rounded-lg border-2 border-dashed px-space-lg py-8 text-center transition-colors ${
          dragging ? "border-secondary bg-secondary-fixed/40" : "border-outline-variant bg-surface-container-low"
        }`}
      >
        <Icon name="upload_file" className="text-[28px] text-outline" />
        <p className=" text-body-sm text-on-surface">
          Drop PDF, PNG or JPG files here, or{" "}
          <button type="button" className="text-secondary hover:underline" onClick={() => inputRef.current?.click()}>
            browse
          </button>
        </p>
        <p className=" text-label-sm text-outline">
          One file = one candidate script. Multi-page PDFs are split automatically.
        </p>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={ACCEPT}
          className="hidden"
          onChange={(e) => {
            addFiles(e.target.files);
            e.target.value = "";
          }}
        />
      </div>

      {files.length > 0 ? (
        <ul className="mt-space-md max-h-40 divide-y divide-outline-variant overflow-y-auto rounded border border-outline-variant">
          {files.map((file, index) => (
            <li key={`${file.name}-${index}`} className="flex items-center justify-between px-space-sm py-1.5  text-body-sm">
              <span className="flex min-w-0 items-center gap-space-sm">
                <Icon name={file.type === "application/pdf" ? "picture_as_pdf" : "image"} className="text-[16px] text-outline" />
                <span className="truncate text-on-surface">{file.name}</span>
                <span className="shrink-0 font-mono text-label-sm text-outline">{(file.size / 1024 / 1024).toFixed(2)} MB</span>
              </span>
              <button
                type="button"
                aria-label={`Remove ${file.name}`}
                className="text-outline hover:text-critical"
                onClick={() => setFiles((prev) => prev.filter((_, i) => i !== index))}
                disabled={progress !== null}
              >
                <Icon name="close" className="text-[16px]" />
              </button>
            </li>
          ))}
        </ul>
      ) : null}

      {files.length === 1 ? (
        <div className="mt-space-md grid grid-cols-2 gap-space-md">
          <label className="flex flex-col gap-1  text-label-md text-on-surface-variant">
            Candidate name
            <input className="field" value={name} onChange={(e) => setName(e.target.value)} placeholder="Marcus Vance" disabled={progress !== null} />
          </label>
          <label className="flex flex-col gap-1  text-label-md text-on-surface-variant">
            Roll number
            <input className="field font-mono" value={roll} onChange={(e) => setRoll(e.target.value)} placeholder="2026-CS-084" disabled={progress !== null} />
          </label>
        </div>
      ) : files.length > 1 ? (
        <p className="mt-space-sm rounded border border-outline-variant bg-surface-container-low px-space-sm py-1.5  text-body-sm text-on-surface-variant">
          <Icon name="info" className="mr-1 text-[14px] align-[-2px]" />
          Candidate names are inferred from each filename; you can correct them per sheet afterwards.
        </p>
      ) : null}

      {progress !== null ? (
        <div className="mt-space-md flex flex-col gap-1">
          <div className="flex justify-between  text-label-sm text-on-surface-variant">
            <span>Uploading…</span>
            <span className="font-mono">{progress}%</span>
          </div>
          <ProgressBar value={progress} tone="info" height="h-1.5" />
        </div>
      ) : null}

      {error ? (
        <p className="mt-space-sm flex items-center gap-space-xs rounded border border-critical-border bg-critical-bg px-space-sm py-1.5  text-body-sm text-critical-fg">
          <Icon name="error" className="text-[16px]" />
          {error}
        </p>
      ) : null}
    </Modal>
  );
}
