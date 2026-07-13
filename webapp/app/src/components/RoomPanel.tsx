import { useState } from "react";
import { Pencil, Trash2, Plus, Hexagon, Ban } from "lucide-react";
import type { RoomData } from "../types";

interface Props {
  rooms: RoomData[];
  onRoomsChange: (rooms: RoomData[]) => void;
  currentRoom: { vertices: number[][]; exclusions: number[][][] } | null;
  currentExcl: number[][];
  onFinishRoom: () => void;
  onFinishExclusion: () => void;
}

export default function RoomPanel({
  rooms,
  onRoomsChange,
  currentRoom,
  currentExcl,
  onFinishRoom,
  onFinishExclusion,
}: Props) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");

  const handleRename = (id: string) => {
    onRoomsChange(
      rooms.map((r) => (r.id === id ? { ...r, name: editName || r.name } : r)),
    );
    setEditingId(null);
  };

  const handleDelete = (id: string) => {
    onRoomsChange(rooms.filter((r) => r.id !== id));
  };

  return (
    <div className="w-72 bg-slate-800/30 border-l border-slate-700/50 flex flex-col shrink-0 overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b border-slate-700/50">
        <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
          Rooms
        </h3>
        <p className="text-xs text-slate-600 mt-0.5">
          {rooms.length} rooms traced
        </p>
      </div>

      {/* Room list */}
      <div className="flex-1 overflow-y-auto p-2 space-y-1.5">
        {rooms.map((room) => {
          return (
            <div
              key={room.id}
              className="group bg-slate-800 rounded-lg p-3 border border-slate-700/50 hover:border-slate-600 transition-colors"
            >
              <div className="flex items-start justify-between">
                {editingId === room.id ? (
                  <input
                    autoFocus
                    value={editName}
                    onChange={(e) => setEditName(e.target.value)}
                    onBlur={() => handleRename(room.id)}
                    onKeyDown={(e) =>
                      e.key === "Enter" && handleRename(room.id)
                    }
                    className="bg-slate-700 text-sm text-slate-100 px-2 py-0.5 rounded border border-slate-600 outline-none w-full"
                  />
                ) : (
                  <div
                    className="text-sm font-medium text-slate-200 cursor-pointer hover:text-brand transition-colors"
                    onClick={() => {
                      setEditingId(room.id);
                      setEditName(room.name);
                    }}
                  >
                    {room.name}
                  </div>
                )}
                <button
                  onClick={() => handleDelete(room.id)}
                  className="opacity-0 group-hover:opacity-100 text-slate-500 hover:text-danger transition-all p-0.5"
                >
                  <Trash2 className="w-3.5 h-3.5" strokeWidth={1.5} />
                </button>
              </div>
              <div className="flex items-center gap-3 mt-1.5 text-xs text-slate-500">
                <span>{room.vertices.length} pts</span>
                {room.exclusions.length > 0 && (
                  <span className="text-danger/70">
                    {room.exclusions.length} excl
                  </span>
                )}
              </div>
            </div>
          );
        })}

        {/* Empty state */}
        {rooms.length === 0 && !currentRoom && (
          <div className="text-center py-8 text-slate-600">
            <Hexagon
              className="w-8 h-8 mx-auto mb-2 opacity-30"
              strokeWidth={1.5}
            />
            <p className="text-xs">Select Room tool</p>
            <p className="text-xs">and click on the plan</p>
            <p className="text-xs mt-2 text-slate-700">
              Right-click to close shape
            </p>
          </div>
        )}

        {/* Current drawing indicator */}
        {currentRoom && currentRoom.vertices.length > 0 && (
          <div className="bg-brand/5 border border-brand/20 rounded-lg p-3 animate-fade-in">
            <div className="flex items-center gap-2 text-xs text-brand font-medium">
              <Hexagon className="w-3.5 h-3.5" strokeWidth={1.5} />
              <span>Drawing room...</span>
            </div>
            <div className="text-xs text-slate-500 mt-1">
              {currentRoom.vertices.length} points
              {currentRoom.exclusions.length > 0 && (
                <> · {currentRoom.exclusions.length} exclusions</>
              )}
            </div>
          </div>
        )}

        {currentExcl.length > 0 && (
          <div className="bg-danger/5 border border-danger/20 rounded-lg p-3 animate-fade-in">
            <div className="flex items-center gap-2 text-xs text-danger font-medium">
              <Ban className="w-3.5 h-3.5" strokeWidth={1.5} />
              <span>Drawing exclusion...</span>
            </div>
            <div className="text-xs text-slate-500 mt-1">
              {currentExcl.length} points
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
