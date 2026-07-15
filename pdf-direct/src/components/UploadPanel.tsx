import { useState, useRef, useCallback } from "react";
import { Upload, FileText } from "lucide-react";

interface Props {
  onFile: (file: File) => void;
  loading: boolean;
  error: string | null;
}

export default function UploadPanel({ onFile, loading, error }: Props) {
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFile = useCallback(
    (file: File) => {
      if (!file.name.toLowerCase().endsWith(".pdf")) return;
      onFile(file);
    },
    [onFile],
  );

  return (
    <div className="h-full flex items-center justify-center p-8">
      <div className="max-w-lg w-full text-center">
        <div className="mb-8">
          <div className="w-20 h-20 rounded-2xl bg-brand/10 mx-auto flex items-center justify-center">
            <Upload className="w-9 h-9 text-brand" strokeWidth={1.5} />
          </div>
        </div>

        <h2 className="text-2xl font-bold text-slate-100 mb-2">
          PDF Direct Takeoff
        </h2>
        <p className="text-sm text-slate-400 mb-8 max-w-sm mx-auto leading-relaxed">
          Upload a floor plan PDF. Calibrate a known length, then trace rooms
          and exclusions directly on the plan. No DXF conversion needed.
        </p>

        <div
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            const f = e.dataTransfer.files[0];
            if (f) handleFile(f);
          }}
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
          {loading ? (
            <div className="flex flex-col items-center gap-3">
              <div className="flex gap-1">
                <span className="loading-dot w-2 h-2 rounded-full bg-brand" />
                <span className="loading-dot w-2 h-2 rounded-full bg-brand" />
                <span className="loading-dot w-2 h-2 rounded-full bg-brand" />
              </div>
              <span className="text-sm text-slate-400">Loading PDF...</span>
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

        {error && (
          <div className="mt-4 text-sm text-danger bg-danger/10 border border-danger/30 rounded-lg px-4 py-2">
            {error}
          </div>
        )}
      </div>
    </div>
  );
}
