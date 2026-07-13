import { useState, useCallback } from "react";
import type { AppMode, DXFData, RoomData, TakeoffResult } from "./types";
import UploadPanel from "./components/UploadPanel";
import DXFEditor from "./components/DXFEditor";
import ResultsPanel from "./components/ResultsPanel";

export default function App() {
  const [mode, setMode] = useState<AppMode>("upload");
  const [dxfData, setDxfData] = useState<DXFData | null>(null);
  const [dxfPath, setDxfPath] = useState<string>("");
  const [rooms, setRooms] = useState<RoomData[]>([]);
  const [results, setResults] = useState<TakeoffResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [scale, setScale] = useState<Record<string, any> | null>(null);

  const handleUploadComplete = useCallback(
    (path: string, data: DXFData, scaleInfo: Record<string, any>) => {
      setDxfPath(path);
      setDxfData(data);
      setScale(scaleInfo);
      setMode("editor");
      setError(null);
    },
    []
  );

  const handleRoomsChange = useCallback((newRooms: RoomData[]) => {
    setRooms(newRooms);
  }, []);

  const handleCalculate = useCallback(async () => {
    if (rooms.length === 0) return;
    setLoading(true);
    setError(null);
    try {
      const resp = await fetch("/api/takeoff", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          rooms: rooms.map((r) => ({
            name: r.name,
            vertices: r.vertices,
            exclusions: r.exclusions,
          })),
          dxf_path: dxfPath,
        }),
      });
      if (!resp.ok) {
        const text = await resp.text();
        throw new Error(text);
      }
      const result: TakeoffResult = await resp.json();
      setResults(result);
      setMode("results");
    } catch (e: any) {
      setError(e.message || "Calculation failed");
    } finally {
      setLoading(false);
    }
  }, [rooms, dxfPath]);

  const handleBackToEditor = useCallback(() => {
    setMode("editor");
  }, []);

  const handleNewUpload = useCallback(() => {
    setMode("upload");
    setDxfData(null);
    setDxfPath("");
    setRooms([]);
    setResults(null);
    setError(null);
  }, []);

  const handleBackToUpload = useCallback(() => {
    setMode("upload");
  }, []);

  return (
    <div className="h-screen flex flex-col bg-slate-900">
      {/* Header */}
      <header className="flex items-center justify-between px-5 py-3 border-b border-slate-700/50 shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-brand flex items-center justify-center text-white font-bold text-sm">
            W
          </div>
          <h1 className="text-lg font-semibold text-slate-100">Warmset</h1>
          {dxfData && mode !== "upload" && (
            <span className="text-xs text-slate-500 font-mono ml-2">
              {dxfData.entity_count} entities · {dxfData.unit}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {mode !== "upload" && (
            <button
              onClick={handleNewUpload}
              className="text-xs text-slate-400 hover:text-slate-200 px-3 py-1.5 rounded-md hover:bg-slate-800 transition-colors"
            >
              New Upload
            </button>
          )}
          {scale && mode === "editor" && (
            <span className="text-xs text-slate-500 font-mono bg-slate-800 px-2 py-1 rounded">
              {scale.confidence === "high" ? "\u2713" : "?"} 1:{scale.scale_ratio}
            </span>
          )}
        </div>
      </header>

      {/* Main content */}
      <main className="flex-1 overflow-hidden">
        {mode === "upload" && (
          <UploadPanel
            onComplete={handleUploadComplete}
            onError={setError}
          />
        )}
        {mode === "editor" && dxfData && (
          <DXFEditor
            dxfData={dxfData}
            rooms={rooms}
            onRoomsChange={handleRoomsChange}
            onCalculate={handleCalculate}
            calculating={loading}
          />
        )}
        {mode === "results" && results && (
          <ResultsPanel
            results={results}
            rooms={rooms}
            onBack={handleBackToEditor}
            onNewUpload={handleNewUpload}
            scale={scale}
          />
        )}
      </main>

      {/* Error toast */}
      {error && (
        <div className="fixed bottom-6 right-6 bg-danger/10 border border-danger/30 text-danger px-4 py-2.5 rounded-lg text-sm shadow-lg z-50 animate-fade-in">
          <div className="flex items-center gap-2">
            <span className="text-danger">!</span>
            <span>{error}</span>
            <button
              onClick={() => setError(null)}
              className="text-slate-400 hover:text-slate-200 ml-2"
            >
              x
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
