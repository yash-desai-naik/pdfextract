import { useState, useRef, useCallback } from "react";
import { Upload, FileText, AlertCircle } from "lucide-react";
import type { DXFData } from "../types";

interface Props {
  onComplete: (path: string, data: DXFData, scale: Record<string, any>) => void;
  onError: (msg: string) => void;
}

export default function UploadPanel({ onComplete, onError }: Props) {
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFile = useCallback(
    async (file: File) => {
      if (!file.name.toLowerCase().endsWith(".pdf")) {
        onError("Only PDF files are accepted");
        return;
      }

      setUploading(true);
      const formData = new FormData();
      formData.append("file", file);

      console.log("[Upload] Starting conversion for:", file.name, file.size);
      try {
        // Step 1: Convert PDF → DXF (with 120s timeout)
        console.log("[Upload] POST /api/convert");
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 120000);
        const convResp = await fetch("/api/convert", {
          method: "POST",
          body: formData,
          signal: controller.signal,
        });
        clearTimeout(timeout);
        console.log("[Upload] /api/convert status:", convResp.status);
        if (!convResp.ok) {
          const err = await convResp.text();
          console.error("[Upload] Convert failed:", err);
          throw new Error(err);
        }
        const convResult = await convResp.json();
        console.log(
          "[Upload] Convert OK:",
          convResult.entity_count,
          "entities, scale:",
          convResult.scale,
        );

        // Step 2: Load DXF entities
        console.log("[Upload] GET /api/dxf/entities");
        const dxfResp = await fetch(
          `/api/dxf/entities?path=${encodeURIComponent(convResult.dxf_path)}`,
        );
        if (!dxfResp.ok) throw new Error("Failed to load DXF");
        const dxfData: DXFData = await dxfResp.json();
        console.log("[Upload] DXF loaded:", dxfData.entity_count, "features");

        onComplete(convResult.dxf_path, dxfData, convResult.scale || {});
      } catch (e: any) {
        console.error("[Upload] Error:", e);
        if (e.name === "AbortError") {
          onError("Conversion timed out after 120s — try a smaller PDF");
        } else {
          onError(e.message || "Upload failed");
        }
      } finally {
        setUploading(false);
      }
    },
    [onComplete, onError],
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const file = e.dataTransfer.files[0];
      if (file) handleFile(file);
    },
    [handleFile],
  );

  return (
    <div className="h-full flex items-center justify-center p-8">
      <div className="max-w-lg w-full text-center">
        {/* Icon */}
        <div className="mb-8">
          <div className="w-20 h-20 rounded-2xl bg-brand/10 mx-auto flex items-center justify-center">
            <Upload className="w-9 h-9 text-brand" strokeWidth={1.5} />
          </div>
        </div>

        {/* Title */}
        <h2 className="text-2xl font-bold text-slate-100 mb-2">
          Underfloor Heating Takeoff
        </h2>
        <p className="text-sm text-slate-400 mb-8 max-w-sm mx-auto leading-relaxed">
          Upload a PDF architectural drawing. We'll convert it to DXF, then you
          can trace rooms and calculate Warmset heating requirements.
        </p>

        {/* Drop zone */}
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
          onClick={() => inputRef.current?.click()}
          className={`border-2 border-dashed rounded-xl p-10 cursor-pointer transition-all duration-200 ${
            dragOver
              ? "border-brand bg-brand/5"
              : "border-slate-700 hover:border-slate-500 bg-slate-800/30"
          }`}
        >
          <input
            ref={inputRef}
            type="file"
            accept=".pdf"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) handleFile(f);
            }}
          />
          {uploading ? (
            <div className="flex flex-col items-center gap-3">
              <div className="flex gap-1">
                <span className="loading-dot w-2 h-2 rounded-full bg-brand" />
                <span className="loading-dot w-2 h-2 rounded-full bg-brand" />
                <span className="loading-dot w-2 h-2 rounded-full bg-brand" />
              </div>
              <span className="text-sm text-slate-400">Converting PDF...</span>
            </div>
          ) : (
            <div className="flex flex-col items-center gap-3">
              <FileText className="w-8 h-8 text-slate-500" strokeWidth={1.5} />
              <div>
                <p className="text-sm text-slate-300 font-medium">
                  Drop your PDF here, or click to browse
                </p>
                <p className="text-xs text-slate-500 mt-1">PDF format only</p>
              </div>
            </div>
          )}
        </div>

        {/* Info */}
        <div className="mt-6 flex items-center justify-center gap-2 text-xs text-slate-600">
          <AlertCircle className="w-3.5 h-3.5" strokeWidth={1.5} />
          <span>
            Drawing stays on your machine — no data is uploaded to any cloud
          </span>
        </div>
      </div>
    </div>
  );
}
