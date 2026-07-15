import { useState, useCallback, useEffect, useRef } from "react";
import { Sun, Moon } from "lucide-react";
import { usePdf } from "./hooks/usePdf";
import { useCalibration } from "./hooks/useCalibration";
import { useDrawing } from "./hooks/useDrawing";
import UploadPanel from "./components/UploadPanel";
import PdfEditor from "./components/PdfEditor";
import Toolbar from "./components/Toolbar";
import Sidebar from "./components/Sidebar";
import ResultsPanel from "./components/ResultsPanel";
import type { ToolMode } from "./types";

type AppMode = "upload" | "editor" | "results";

export default function App() {
  const {
    canvasRef,
    pdfCacheRef,
    loading,
    error,
    loadPdf,
    pageWidth,
    pageHeight,
    pdfReady,
    renderTick,
    reRender,
  } = usePdf();
  const {
    calibration,
    setPoint1,
    setPoint2,
    setKnownLength,
    addPolygonPt,
    undoPolygonPt,
    setKnownArea,
    computeScale,
    reset: resetCal,
  } = useCalibration();
  const {
    mode,
    setMode,
    areas,
    currentPts,
    addPoint,
    undoPoint,
    clearPoints,
    finishArea,
    removeArea,
    renameArea,
    reset: resetDrawing,
  } = useDrawing(calibration.pxPerMetre);

  const [appMode, setAppMode] = useState<AppMode>("upload");
  const [fileName, setFileName] = useState("");
  const [light, setLight] = useState(
    () => localStorage.getItem("theme") === "light",
  );

  useEffect(() => {
    document.body.classList.toggle("light", light);
    localStorage.setItem("theme", light ? "light" : "dark");
  }, [light]);
  const [calAreaPts, setCalAreaPts] = useState<number[][] | null>(null);
  const [pendingName, setPendingName] = useState<{
    type: "room" | "exclusion";
  } | null>(null);

  const handleFile = useCallback(
    (file: File) => {
      setFileName(file.name);
      loadPdf(file);
      setAppMode("editor");
      resetCal();
      resetDrawing();
    },
    [loadPdf, resetCal, resetDrawing],
  );

  const handleModeChange = useCallback(
    (m: ToolMode) => {
      if ((m === "room" || m === "exclusion") && calibration.pxPerMetre === 0) {
        setMode("calibrate");
        return;
      }
      setMode(m);
      // Start fresh polygon when entering area calibration
      if (m === "calibrate-area") {
        resetCal();
      }
    },
    [calibration.pxPerMetre, setMode, resetCal],
  );

  const handleCalPoint1 = useCallback(
    (pt: [number, number]) => {
      setPoint1(pt);
    },
    [setPoint1],
  );

  const handleCalPoint2 = useCallback(
    (pt: [number, number]) => {
      setPoint2(pt);
    },
    [setPoint2],
  );

  const handleKnownLength = useCallback(
    (m: number) => {
      setKnownLength(m);
      computeScale(m); // auto-compute scale when length entered
    },
    [setKnownLength, computeScale],
  );

  // Undo: calibration → polygon vertex → last room
  const handleUndo = useCallback(() => {
    if (mode === "calibrate-area") {
      if (currentPts.length > 0) undoPoint();
    } else if (calibration.method === "length") {
      if (calibration.point2) {
        setPoint2(null as any);
      } else if (calibration.point1) {
        setPoint1(null as any);
      } else if (currentPts.length > 0) {
        undoPoint();
      } else if (areas.length > 0) {
        removeArea(areas[areas.length - 1].id);
      }
    } else {
      if (currentPts.length > 0) undoPoint();
      else if (areas.length > 0) removeArea(areas[areas.length - 1].id);
    }
  }, [
    mode,
    calibration,
    currentPts,
    undoPoint,
    areas,
    removeArea,
    setPoint1,
    setPoint2,
  ]);

  const handleFinish = useCallback(() => {
    if (mode === "calibrate-area") {
      if (currentPts.length >= 3) {
        setCalAreaPts([...currentPts]);
        clearPoints();
      }
    } else if (currentPts.length >= 3) {
      // Show naming modal for room/exclusion
      setPendingName({ type: mode === "exclusion" ? "exclusion" : "room" });
    }
  }, [mode, currentPts, clearPoints]);

  const handleNameConfirm = useCallback(
    (name: string) => {
      if (pendingName) {
        finishArea(pendingName.type, name || undefined);
        setPendingName(null);
      }
    },
    [pendingName, finishArea],
  );

  const handleNameCancel = useCallback(() => {
    setPendingName(null);
  }, []);

  const handleConfirmCalArea = useCallback(
    (m2: number) => {
      // Pass the drawn polygon vertices explicitly so computeScale can use them
      computeScale(m2, calAreaPts ?? undefined);
      setCalAreaPts(null);
    },
    [computeScale, calAreaPts],
  );

  const handleCancelCalArea = useCallback(() => {
    setCalAreaPts(null);
  }, []);

  const handleCalculate = useCallback(() => {
    if (areas.filter((a) => a.type === "room").length === 0) return;
    setAppMode("results");
  }, [areas]);

  const handleBackToEditor = useCallback(() => {
    setAppMode("editor");
  }, []);

  const handleNewUpload = useCallback(() => {
    setAppMode("upload");
    setFileName("");
    resetDrawing();
    resetCal();
  }, [resetDrawing, resetCal]);

  const isDrawing = currentPts.length > 0;
  const canUndo = isDrawing || areas.length > 0 || !!calibration.point1;

  return (
    <div className="h-screen flex flex-col bg-slate-900">
      {/* Header */}
      <header className="flex items-center justify-between px-5 py-3 border-b border-slate-700/50 shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-brand flex items-center justify-center text-white font-bold text-sm">
            P
          </div>
          <h1 className="text-lg font-semibold text-slate-100">PDF Direct</h1>
          {fileName && appMode !== "upload" && (
            <span className="text-xs text-slate-500 font-mono ml-2">
              {fileName}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {appMode !== "upload" && (
            <button
              onClick={handleNewUpload}
              className="text-xs text-slate-400 hover:text-slate-200 px-3 py-1.5 rounded-md hover:bg-slate-800 transition-colors"
            >
              New Drawing
            </button>
          )}
          <button
            onClick={() => setLight((p) => !p)}
            className="text-slate-400 hover:text-slate-200 p-1.5 rounded-md hover:bg-slate-800 transition-colors"
            title="Toggle theme"
          >
            {light ? (
              <Moon className="w-4 h-4" strokeWidth={1.5} />
            ) : (
              <Sun className="w-4 h-4" strokeWidth={1.5} />
            )}
          </button>
        </div>
      </header>

      {/* Content */}
      <main className="flex-1 overflow-hidden flex flex-col">
        {appMode === "upload" && (
          <UploadPanel onFile={handleFile} loading={loading} error={error} />
        )}

        {appMode === "editor" && (
          <>
            <Toolbar
              mode={mode}
              onModeChange={handleModeChange}
              onUndo={handleUndo}
              onFinish={handleFinish}
              onCalculate={handleCalculate}
              calibrating={!!(calibration.point1 && !calibration.point2)}
              onResetCalibration={resetCal}
              pxPerMetre={calibration.pxPerMetre}
              drawing={canUndo}
              hasActiveDrawing={isDrawing}
              roomCount={areas.filter((a) => a.type === "room").length}
              hasCalibration={calibration.pxPerMetre > 0}
            />
            <div className="flex-1 flex overflow-hidden">
              <div className="flex-1 relative">
                <PdfEditor
                  canvasRef={canvasRef}
                  pdfCacheRef={pdfCacheRef}
                  pdfReady={pdfReady}
                  renderTick={renderTick}
                  reRender={reRender}
                  pageWidth={pageWidth}
                  pageHeight={pageHeight}
                  mode={mode}
                  areas={areas}
                  currentPts={currentPts}
                  onAddPoint={addPoint}
                  onFinish={handleFinish}
                  calibration={calibration}
                  onSetCalPoint1={handleCalPoint1}
                  onSetCalPoint2={handleCalPoint2}
                  pxPerMetre={calibration.pxPerMetre}
                  onSetKnownLength={handleKnownLength}
                  calAreaPts={calAreaPts}
                  onConfirmCalArea={handleConfirmCalArea}
                  onCancelCalArea={handleCancelCalArea}
                />
              </div>
              <Sidebar
                areas={areas}
                onRemove={removeArea}
                onRename={renameArea}
                pxPerMetre={calibration.pxPerMetre}
              />
            </div>
          </>
        )}

        {appMode === "results" && (
          <ResultsPanel
            areas={areas}
            pxPerMetre={calibration.pxPerMetre}
            onBack={handleBackToEditor}
          />
        )}
      </main>

      {/* Name modal for room/exclusion */}
      {pendingName && (
        <NameModal
          defaultName={
            pendingName.type === "room"
              ? `Room ${areas.filter((a) => a.type === "room").length + 1}`
              : `Exclusion ${areas.filter((a) => a.type === "exclusion").length + 1}`
          }
          onConfirm={handleNameConfirm}
          onCancel={handleNameCancel}
        />
      )}
    </div>
  );
}

function NameModal({
  defaultName,
  onConfirm,
  onCancel,
}: {
  defaultName: string;
  onConfirm: (name: string) => void;
  onCancel: () => void;
}) {
  const [val, setVal] = useState(defaultName);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);

  return (
    <div className="fixed inset-0 flex items-center justify-center bg-black/40 z-30">
      <div className="bg-slate-800 border border-slate-600 rounded-xl p-6 shadow-2xl w-80 animate-fade-in">
        <h3 className="text-sm font-semibold text-slate-100 mb-1">
          Name this area
        </h3>
        <p className="text-xs text-slate-400 mb-4">
          Enter a name for this area:
        </p>
        <input
          ref={inputRef}
          type="text"
          value={val}
          onChange={(e) => setVal(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") onConfirm(val);
            if (e.key === "Escape") onCancel();
          }}
          className="bg-slate-700 text-sm text-slate-100 px-3 py-2 rounded-lg border border-slate-600 outline-none w-full font-mono mb-4"
        />
        <div className="flex justify-end gap-2">
          <button
            onClick={() => onCancel()}
            className="text-xs text-slate-400 px-3 py-2 rounded-lg hover:bg-slate-700/50 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={() => onConfirm(val)}
            className="bg-brand text-white text-xs font-medium px-4 py-2 rounded-lg hover:bg-brand-hover transition-colors"
          >
            OK
          </button>
        </div>
      </div>
    </div>
  );
}
