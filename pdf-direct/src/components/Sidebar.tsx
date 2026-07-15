import { useState } from "react";
import { Trash2, Pencil, Hexagon, Ban, Ruler } from "lucide-react";
import type { MarkedArea } from "../types";

interface Props {
  areas: MarkedArea[];
  onRemove: (id: string) => void;
  onRename: (id: string, name: string) => void;
  pxPerMetre: number;
}

export default function Sidebar({ areas, onRemove, onRename, pxPerMetre }: Props) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");

  const rooms = areas.filter((a) => a.type === "room");
  const exclusions = areas.filter((a) => a.type === "exclusion");

  const totalArea = rooms.reduce((s, r) => s + r.areaM2, 0);
  const totalExcluded = exclusions.reduce((s, e) => s + e.areaM2, 0);

  return (
    <div className="w-72 bg-slate-800/30 border-l border-slate-700/50 flex flex-col shrink-0 overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b border-slate-700/50">
        <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
          Marked Areas
        </h3>
        <p className="text-xs text-slate-600 mt-0.5">
          {rooms.length} rooms · {totalArea.toFixed(1)} m²
        </p>
        {pxPerMetre > 0 && (
          <p className="text-xs text-slate-600 mt-0.5 font-mono">
            {pxPerMetre.toFixed(1)} px/m
          </p>
        )}
      </div>

      {/* Area list */}
      <div className="flex-1 overflow-y-auto p-2 space-y-1.5">
        {areas.length === 0 && (
          <div className="text-center py-8 text-slate-600">
            <Hexagon className="w-8 h-8 mx-auto mb-2 opacity-30" strokeWidth={1.5} />
            <p className="text-xs">Select Room tool</p>
            <p className="text-xs">and click on the plan</p>
            <p className="text-xs mt-2 text-slate-700">Right-click to close shape</p>
          </div>
        )}

        {areas.map((area) => {
          const isRoom = area.type === "room";
          const color = isRoom ? "brand" : "danger";
          const Icon = isRoom ? Hexagon : Ban;
          return (
            <div
              key={area.id}
              className={`group bg-slate-800 rounded-lg p-3 border transition-colors ${
                isRoom ? "border-slate-700/50 hover:border-brand/30" : "border-slate-700/50 hover:border-danger/30"
              }`}
            >
              <div className="flex items-start justify-between">
                {editingId === area.id ? (
                  <input
                    autoFocus
                    value={editName}
                    onChange={(e) => setEditName(e.target.value)}
                    onBlur={() => {
                      onRename(area.id, editName || area.name);
                      setEditingId(null);
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        onRename(area.id, editName || area.name);
                        setEditingId(null);
                      }
                    }}
                    className="bg-slate-700 text-sm text-slate-100 px-2 py-0.5 rounded border border-slate-600 outline-none w-full"
                  />
                ) : (
                  <div
                    className="text-sm font-medium text-slate-200 cursor-pointer hover:text-brand transition-colors flex items-center gap-1.5"
                    onClick={() => {
                      setEditingId(area.id);
                      setEditName(area.name);
                    }}
                  >
                    <Icon className={`w-3 h-3 text-${color}`} strokeWidth={1.5} />
                    <span>{area.name}</span>
                  </div>
                )}
                <button
                  onClick={() => onRemove(area.id)}
                  className="opacity-0 group-hover:opacity-100 text-slate-500 hover:text-danger transition-all p-0.5"
                >
                  <Trash2 className="w-3.5 h-3.5" strokeWidth={1.5} />
                </button>
              </div>

              <div className="flex flex-col gap-0.5 mt-1.5 text-xs text-slate-500">
                <span>{area.dimensions}</span>
                <span className={`font-mono font-medium ${isRoom ? "text-brand" : "text-danger/70"}`}>
                  {area.areaM2.toFixed(2)} m²
                </span>
                <span className="text-slate-600">
                  {area.vertices.length} pts · {area.perimeterM.toFixed(1)} m
                </span>
              </div>
            </div>
          );
        })}
      </div>

      {/* Totals footer */}
      {rooms.length > 0 && (
        <div className="px-4 py-3 border-t border-slate-700/50 bg-slate-800/50">
          <div className="space-y-1 text-xs">
            <div className="flex justify-between text-slate-400">
              <span>Total rooms</span>
              <span className="font-mono">{rooms.length}</span>
            </div>
            <div className="flex justify-between text-brand font-medium">
              <span>Gross area</span>
              <span className="font-mono">{totalArea.toFixed(1)} m²</span>
            </div>
            {exclusions.length > 0 && (
              <div className="flex justify-between text-danger/70">
                <span>Excluded</span>
                <span className="font-mono">-{totalExcluded.toFixed(1)} m²</span>
              </div>
            )}
            <div className="flex justify-between text-slate-200 font-medium pt-1 border-t border-slate-700/50">
              <span>Net heatable</span>
              <span className="font-mono">{(totalArea - totalExcluded).toFixed(1)} m²</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
