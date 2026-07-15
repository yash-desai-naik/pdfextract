import {
  Hexagon,
  Ban,
  Hand,
  Ruler,
  Square,
  Undo2,
  Redo,
  Check,
  Calculator,
  RotateCcw,
} from "lucide-react";
import type { ToolMode } from "../types";

interface Props {
  mode: ToolMode;
  onModeChange: (m: ToolMode) => void;
  onUndo: () => void;
  onRedo: () => void;
  canRedo: boolean;
  onFinish: () => void;
  onCalculate: () => void;
  calibrating: boolean;
  onResetCalibration: () => void;
  pxPerMetre: number;
  drawing: boolean;
  hasActiveDrawing: boolean;
  roomCount: number;
  hasCalibration: boolean;
}

export default function Toolbar({
  mode,
  onModeChange,
  onUndo,
  onRedo,
  canRedo,
  onFinish,
  onCalculate,
  calibrating,
  onResetCalibration,
  pxPerMetre,
  drawing,
  hasActiveDrawing,
  roomCount,
  hasCalibration,
}: Props) {
  const tools: { mode: ToolMode; icon: typeof Hexagon; label: string }[] = [
    { mode: "pan", icon: Hand, label: "Pan" },
    { mode: "calibrate", icon: Ruler, label: "Cal. Length" },
    { mode: "calibrate-area", icon: Square, label: "Cal. Area" },
    { mode: "room", icon: Hexagon, label: "Room" },
    { mode: "exclusion", icon: Ban, label: "Exclusion" },
  ];

  return (
    <div className="flex items-center gap-1.5 px-3 py-2 bg-slate-800/50 border-b border-slate-700/50 shrink-0 overflow-x-auto">
      {tools.map((t) => {
        const Icon = t.icon;
        const active = mode === t.mode;
        return (
          <button
            key={t.mode}
            onClick={() => onModeChange(t.mode)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all whitespace-nowrap ${
              active
                ? "bg-brand text-white shadow-sm"
                : "text-slate-400 hover:text-slate-200 hover:bg-slate-700/50"
            }`}
          >
            <Icon className="w-3.5 h-3.5" strokeWidth={1.5} />
            <span>{t.label}</span>
          </button>
        );
      })}

      <div className="w-px h-5 bg-slate-700 mx-2" />

      <button
        onClick={onUndo}
        disabled={!drawing}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs text-slate-400 hover:text-slate-200 hover:bg-slate-700/50 transition-all disabled:opacity-30 disabled:cursor-not-allowed"
      >
        <Undo2 className="w-3.5 h-3.5" strokeWidth={1.5} />
        <span>Undo</span>
      </button>
      <button
        onClick={onRedo}
        disabled={!canRedo}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs text-slate-400 hover:text-slate-200 hover:bg-slate-700/50 transition-all disabled:opacity-30 disabled:cursor-not-allowed"
      >
        <Redo className="w-3.5 h-3.5" strokeWidth={1.5} />
        <span>Redo</span>
      </button>

      <div className="flex-1" />

      {/* Calibration controls */}
      {(hasCalibration ||
        calibrating ||
        mode === "calibrate" ||
        mode === "calibrate-area") && (
        <div className="flex items-center gap-2 mr-2">
          {hasCalibration ? (
            <span className="text-xs text-brand font-mono">
              ✓ {pxPerMetre.toFixed(1)} px/m
            </span>
          ) : (
            <span className="text-xs text-warning font-mono">
              {mode === "calibrate"
                ? calibrating
                  ? "2nd point..."
                  : "Click 1st point"
                : ""}
              {mode === "calibrate-area" ? "Draw known area" : ""}
            </span>
          )}
          <button
            onClick={onResetCalibration}
            className="flex items-center gap-1 px-2 py-1 rounded text-xs text-slate-400 hover:text-danger hover:bg-slate-700/50 transition-all"
            title="Reset calibration"
          >
            <RotateCcw className="w-3 h-3" strokeWidth={1.5} />
          </button>
        </div>
      )}

      {!hasCalibration &&
        !calibrating &&
        mode !== "calibrate" &&
        mode !== "calibrate-area" && (
          <span className="text-xs text-warning font-medium mr-2">
            Calibrate first
          </span>
        )}

      {hasActiveDrawing &&
        (mode === "room" ||
          mode === "exclusion" ||
          mode === "calibrate-area") && (
          <button
            onClick={onFinish}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium bg-brand/20 text-brand hover:bg-brand/30 transition-all mr-2"
          >
            <Check className="w-3.5 h-3.5" strokeWidth={1.5} />
            <span>Finish</span>
          </button>
        )}

      <button
        onClick={onCalculate}
        disabled={roomCount === 0}
        className={`flex items-center gap-1.5 px-4 py-1.5 rounded-md text-xs font-medium transition-all ${
          roomCount > 0
            ? "bg-brand text-white hover:bg-brand-hover shadow-sm"
            : "bg-slate-700 text-slate-500 cursor-not-allowed"
        }`}
      >
        <Calculator className="w-3.5 h-3.5" strokeWidth={1.5} />
        <span>Takeoff</span>
      </button>
    </div>
  );
}
