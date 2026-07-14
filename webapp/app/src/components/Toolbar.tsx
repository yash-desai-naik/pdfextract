import {
  MousePointer2,
  Hexagon,
  Ban,
  Hand,
  Pen,
  Undo2,
  Trash2,
  Maximize2,
  Calculator,
  Check,
} from "lucide-react";
import type { EditorMode } from "../types";

interface Props {
  mode: EditorMode;
  onModeChange: (m: EditorMode) => void;
  onUndo: () => void;
  onFitView: () => void;
  onDelete: () => void;
  onFinishRoom: () => void;
  onFinishExclusion: () => void;
  onCalculate: () => void;
  calculating: boolean;
  roomCount: number;
  totalArea: number;
}

export default function Toolbar({
  mode,
  onModeChange,
  onUndo,
  onFitView,
  onDelete,
  onFinishRoom,
  onFinishExclusion,
  onCalculate,
  calculating,
  roomCount,
  totalArea,
}: Props) {
  const tools: {
    mode: EditorMode;
    icon: typeof Hexagon;
    label: string;
    shortcut: string;
  }[] = [
    { mode: "select", icon: MousePointer2, label: "Select", shortcut: "S" },
    { mode: "room", icon: Hexagon, label: "Room", shortcut: "R" },
    { mode: "freeform", icon: Pen, label: "Freeform", shortcut: "F" },
    { mode: "exclusion", icon: Ban, label: "Exclusion", shortcut: "E" },
    { mode: "pan", icon: Hand, label: "Pan", shortcut: "P" },
  ];
  return (
    <div className="flex items-center gap-1.5 px-3 py-2 bg-slate-800/50 border-b border-slate-700/50 shrink-0">
      {/* Drawing tools */}
      {tools.map((t) => {
        const Icon = t.icon;
        const active = mode === t.mode;
        return (
          <button
            key={t.mode}
            onClick={() => onModeChange(t.mode)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
              active
                ? "bg-brand text-white shadow-sm"
                : "text-slate-400 hover:text-slate-200 hover:bg-slate-700/50"
            }`}
            title={`${t.label} (${t.shortcut})`}
          >
            <Icon className="w-3.5 h-3.5" strokeWidth={1.5} />
            <span>{t.label}</span>
          </button>
        );
      })}

      <div className="w-px h-5 bg-slate-700 mx-2" />

      {/* Actions */}
      <button
        onClick={onUndo}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs text-slate-400 hover:text-slate-200 hover:bg-slate-700/50 transition-all"
        title="Undo (Ctrl+Z)"
      >
        <Undo2 className="w-3.5 h-3.5" strokeWidth={1.5} />
        <span>Undo</span>
      </button>
      <button
        onClick={onDelete}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs text-slate-400 hover:text-danger hover:bg-danger/10 transition-all"
        title="Remove last room"
      >
        <Trash2 className="w-3.5 h-3.5" strokeWidth={1.5} />
        <span>Remove</span>
      </button>
      <button
        onClick={onFitView}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs text-slate-400 hover:text-slate-200 hover:bg-slate-700/50 transition-all"
        title="Fit view (F)"
      >
        <Maximize2 className="w-3.5 h-3.5" strokeWidth={1.5} />
        <span>Fit</span>
      </button>

      <div className="flex-1" />

      {/* Room count */}
      <span className="text-xs text-slate-500 font-mono mr-3">
        {roomCount} rooms · {totalArea.toFixed(1)} m²
      </span>

      {/* Finish room (shown when drawing) */}
      {(mode === "room" || mode === "exclusion") && (
        {(mode === "room" || mode === "freeform" || mode === "exclusion") && (
          <button
            onClick={mode === "exclusion" ? onFinishExclusion : onFinishRoom}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium bg-brand/20 text-brand hover:bg-brand/30 transition-all mr-2"
          >
            <Check className="w-3.5 h-3.5" strokeWidth={1.5} />
            <span>{mode === "exclusion" ? "Finish Exclusion" : "Finish"}</span>
          </button>
        )}

      {/* Calculate */}
      <button
        onClick={onCalculate}
        disabled={roomCount === 0 || calculating}
        className={`flex items-center gap-1.5 px-4 py-1.5 rounded-md text-xs font-medium transition-all ${
          roomCount > 0 && !calculating
            ? "bg-brand text-white hover:bg-brand-hover shadow-sm"
            : "bg-slate-700 text-slate-500 cursor-not-allowed"
        }`}
      >
        <Calculator className="w-3.5 h-3.5" strokeWidth={1.5} />
        <span>{calculating ? "Calculating..." : "Calculate"}</span>
      </button>
    </div>
  );
}
