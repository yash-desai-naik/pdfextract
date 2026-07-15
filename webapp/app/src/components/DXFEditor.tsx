import { useEffect, useRef, useState, useCallback } from "react";
import { fabric } from "fabric";
import type { RoomData, EditorMode } from "../types";
import RoomPanel from "./RoomPanel";
import Toolbar from "./Toolbar";

interface Props {
  dxfPath: string;
  pdfPath?: string;
  bounds: number[];
  unitLabel: string;
  rooms: RoomData[];
  onRoomsChange: (rooms: RoomData[]) => void;
  onCalculate: () => void;
  calculating: boolean;
}

const ROOM_COLOR = "#10b981";
const EXCL_COLOR = "#ef4444";
const ROOM_FILL = "rgba(16, 185, 129, 0.08)";
const EXCL_FILL = "rgba(239, 68, 68, 0.15)";

// Persist viewport across remounts (editor coming back from results)
let _savedZoom = 1;
let _savedPanX = 0;
let _savedPanY = 0;

let roomIdCounter = 0;
function nextId() {
  return `room_${Date.now()}_${++roomIdCounter}`;
}

export default function DXFEditor({
  dxfPath,
  pdfPath,
  bounds,
  unitLabel,
  rooms,
  onRoomsChange,
  onCalculate,
  calculating,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const fabricRef = useRef<fabric.Canvas | null>(null);
  const [mode, setMode] = useState<EditorMode>("pan");
  const [currentRoom, setCurrentRoom] = useState<{
    vertices: number[][];
    exclusions: number[][][];
  } | null>(null);
  const [currentExcl, setCurrentExcl] = useState<number[][]>([]);
  const [isPanning, setIsPanning] = useState(false);
  const panStart = useRef({ x: 0, y: 0 });
  const [layerList, setLayerList] = useState<{ name: string; count: number }[]>(
    [],
  );
  const [selectedLayers, setSelectedLayers] = useState<Set<string>>(new Set());
  const [showLayers, setShowLayers] = useState(false);
  const [calFactor, setCalFactor] = useState<number | null>(null);
  const calFactorRef = useRef<number | null>(null);
  const [calibrating, setCalibrating] = useState(false);
  const calibratingRef = useRef(false);
  const calPointA = useRef<[number, number] | null>(null);
  const roomsRef = useRef(rooms);
  roomsRef.current = rooms;
  const SVG_RENDER_W = 2000;
  const SVG_RENDER_H = 1500;

  // Compute pixel → world transform from SVG viewBox + render size
  // SVG has viewBox="xmin ymin vw vh" rendered at SVG_RENDER_W × SVG_RENDER_H
  // with default preserveAspectRatio="xMidYMid meet"
  const pixelToMetres = (px: number, py: number): [number, number] => {
    const [xmin, ymin_raw, xmax, ymax_raw] = bounds;
    const vw = xmax - xmin;
    const vh = ymax_raw - ymin_raw;
    // SVG viewBox negates Y: ymin_vb = -ymax_raw
    const ymin_vb = -ymax_raw;
    const fitScale = Math.min(SVG_RENDER_W / vw, SVG_RENDER_H / vh);
    const offX = (SVG_RENDER_W - vw * fitScale) / 2;
    const offY = (SVG_RENDER_H - vh * fitScale) / 2;
    const c = fabricRef.current!;
    const svgPx = (px / c.width!) * SVG_RENDER_W;
    const svgPy = (py / c.height!) * SVG_RENDER_H;
    // Map to SVG viewBox coordinates (negated Y space)
    const viewX = xmin + (svgPx - offX) / fitScale;
    const viewY = ymin_vb + (svgPy - offY) / fitScale;
    // viewY is in SVG negated space → negate back to DXF Y-up, mm → m
    const result: [number, number] = [viewX / 1000, -viewY / 1000];
    // Log ~2% of clicks for debugging
    if (Math.random() < 0.02) {
      console.log(
        "[px2m] px=",
        px.toFixed(0),
        "py=",
        py.toFixed(0),
        "→",
        result[0].toFixed(3),
        result[1].toFixed(3),
      );
    }
    // Apply user calibration factor
    const cf = calFactorRef.current;
    if (cf !== null && cf !== 1.0) {
      result[0] *= cf;
      result[1] *= cf;
    }
    return result;
  };

  // Inverse: metres → canvas pixel (for rendering persisted rooms)
  const metresToPixel = (mx: number, my: number): [number, number] => {
    const [xmin, ymin_raw, xmax, ymax_raw] = bounds;
    const vw = xmax - xmin;
    const vh = ymax_raw - ymin_raw;
    const ymin_vb = -ymax_raw;
    const fitScale = Math.min(SVG_RENDER_W / vw, SVG_RENDER_H / vh);
    const offX = (SVG_RENDER_W - vw * fitScale) / 2;
    const offY = (SVG_RENDER_H - vh * fitScale) / 2;
    const c = fabricRef.current!;
    // metres → DXF mm → viewBox Y (negated)
    const mmX = mx * 1000;
    const mmY = -my * 1000; // negate Y-up back to SVG Y-down
    // viewBox coordinate → SVG pixel (inverse of pixelToMetres)
    const svgPx = (mmX - xmin) * fitScale + offX;
    const svgPy = (mmY - ymin_vb) * fitScale + offY;
    // SVG pixel → canvas pixel
    const cpx = (svgPx / SVG_RENDER_W) * c.width!;
    const cpy = (svgPy / SVG_RENDER_H) * c.height!;
    return [cpx, cpy];
  };

  // ===== Refs to avoid stale closures in Fabric event handlers =====
  const modeRef = useRef(mode);
  modeRef.current = mode;
  const currentRoomRef = useRef(currentRoom);
  currentRoomRef.current = currentRoom;
  const currentExclRef = useRef(currentExcl);
  currentExclRef.current = currentExcl;
  const isPanningRef = useRef(isPanning);
  isPanningRef.current = isPanning;

  // Toggle Fabric free-drawing mode when entering/exiting freeform
  useEffect(() => {
    const c = fabricRef.current;
    if (!c) return;
    if (mode === "freeform") {
      c.isDrawingMode = true;
      if (c.freeDrawingBrush) {
        c.freeDrawingBrush.width = 3;
        c.freeDrawingBrush.color = "#10b981";
      }
    } else {
      c.isDrawingMode = false;
    }
    c.selection = false;
  }, [mode]);

  // Store finishRoom/finishExclusion callbacks in refs to avoid stale closures
  const finishRoomRef = useRef<() => void>(() => {});
  const finishExclRef = useRef<() => void>(() => {});

  // ===== Init Fabric canvas =====
  useEffect(() => {
    if (!canvasRef.current || fabricRef.current) return;

    const container = containerRef.current!;
    const c = new fabric.Canvas(canvasRef.current, {
      width: container.clientWidth,
      height: container.clientHeight,
      selection: false,
      preserveObjectStacking: true,
      backgroundColor: "#1e293b",
    });
    fabricRef.current = c;

    c.on("mouse:wheel", (opt) => {
      const delta = opt.e.deltaY;
      let zoom = c.getZoom();
      zoom *= 0.998 ** delta;
      zoom = Math.min(Math.max(zoom, 0.05), 100);
      c.zoomToPoint(new fabric.Point(opt.e.offsetX, opt.e.offsetY), zoom);
      opt.e.preventDefault();
      opt.e.stopPropagation();
    });

    c.on("mouse:down", (opt) => {
      const m = modeRef.current;
      if (opt.e.button === 0) {
        if (m === "pan") {
          isPanningRef.current = true;
          panStart.current = { x: opt.e.clientX, y: opt.e.clientY };
          return;
        }
        if (m === "select") return;
        if (m === "freeform") return;
        if (m === "pan") return;
        if (m === "select") return;

        // Calibrate mode: click two points, then enter real distance
        if (calibratingRef.current) {
          const ptr = c.getPointer(opt.e);
          if (!calPointA.current) {
            calPointA.current = [ptr.x, ptr.y];
            console.log("[cal] Point A:", ptr.x, ptr.y);
          } else {
            const [ax, ay] = calPointA.current;
            const dx = ptr.x - ax;
            const dy = ptr.y - ay;
            const pixelDist = Math.sqrt(dx * dx + dy * dy);
            const realDistMm = prompt("Enter real-world distance (mm):");
            if (
              realDistMm &&
              !isNaN(Number(realDistMm)) &&
              Number(realDistMm) > 0
            ) {
              // Current pixelToMetres distance for these two pixels
              const [mx1, my1] = pixelToMetres(ax, ay);
              const [mx2, my2] = pixelToMetres(ptr.x, ptr.y);
              const metreDist = Math.sqrt((mx2 - mx1) ** 2 + (my2 - my1) ** 2);
              const realDistM = Number(realDistMm) / 1000;
              const factor = realDistM / metreDist;
              setCalFactor(factor);
              calFactorRef.current = factor;
              console.log(
                "[cal] Factor:",
                factor,
                "(pixelDist:",
                pixelDist.toFixed(0),
                "px, metreDist:",
                metreDist.toFixed(3),
                "m)",
              );
            }
            calPointA.current = null;
            setCalibrating(false);
            calibratingRef.current = false;
          }
          return;
        }

        const pointer = c.getPointer(opt.e);
        const ptPx: [number, number] = [pointer.x, pointer.y];

        if (m === "room") {
          setCurrentRoom((prev) => {
            const room = prev || { vertices: [], exclusions: [] };
            return { ...room, vertices: [...room.vertices, ptPx] };
          });
        } else if (m === "exclusion") {
          if (!currentRoomRef.current) {
            setCurrentRoom({ vertices: [], exclusions: [] });
          }
          setCurrentExcl((prev) => [...prev, ptPx]);
        }
      } else if (opt.e.button === 2) {
        if (m === "room" || m === "freeform") {
          finishRoomRef.current();
        } else if (m === "exclusion") {
          finishExclRef.current();
        }
      }
    });

    // Freeform drawing: capture path points on completion
    c.on("path:created", (opt) => {
      const m = modeRef.current;
      if (m !== "freeform" && m !== "room") return;
      const path = opt.path;
      if (!path) return;
      // Sample points from the drawn path (every ~5px to keep it manageable)
      const raw = path.path;
      const points: [number, number][] = [];
      const minDist = 5;
      let last: [number, number] | null = null;
      for (const cmd of raw) {
        const action = cmd[0] as string;
        // Fabric path commands: M x y, L x y, C x1 y1 x2 y2 x y, Q x1 y1 x y
        let x: number | undefined, y: number | undefined;
        if (action === "M" || action === "L") {
          x = cmd[1] as number;
          y = cmd[2] as number;
        } else if (action === "Q") {
          x = cmd[3] as number;
          y = cmd[4] as number;
        } else if (action === "C") {
          x = cmd[5] as number;
          y = cmd[6] as number;
        }
        if (x !== undefined && y !== undefined) {
          const pt: [number, number] = [x, y];
          if (!last || Math.hypot(x - last[0], y - last[1]) > minDist) {
            points.push(pt);
            last = pt;
          }
        }
      }
      if (points.length < 3) return;
      // Remove the drawn path (we'll render as polygon)
      c.remove(path);
      // Add sampled points to current room
      if (m === "freeform" || m === "room") {
        setCurrentRoom((prev) => {
          const room = prev || { vertices: [], exclusions: [] };
          return { ...room, vertices: [...room.vertices, ...points] };
        });
      }
    });

    c.on("mouse:move", (opt) => {
      if (isPanningRef.current && modeRef.current === "pan") {
        const vpt = c.viewportTransform!;
        vpt[4] += opt.e.clientX - panStart.current.x;
        vpt[5] += opt.e.clientY - panStart.current.y;
        c.requestRenderAll();
        panStart.current = { x: opt.e.clientX, y: opt.e.clientY };
      }
    });

    c.on("mouse:up", () => {
      isPanningRef.current = false;
    });

    // Restore saved viewport (zoom/pan) from previous session
    if (_savedZoom !== 1 || _savedPanX !== 0 || _savedPanY !== 0) {
      const vpt = c.viewportTransform!;
      vpt[0] = _savedZoom;
      vpt[3] = _savedZoom;
      vpt[4] = _savedPanX;
      vpt[5] = _savedPanY;
      c.requestRenderAll();
    }

    c.onContextMenu = () => false;

    const resize = () => {
      c.setWidth(container.clientWidth);
      c.setHeight(container.clientHeight);
      c.renderAll();
    };
    // Track zoom/pan for persistence
    c.on("mouse:wheel", () => {
      const vpt = c.viewportTransform!;
      _savedZoom = vpt[0];
      _savedPanX = vpt[4];
      _savedPanY = vpt[5];
    });

    window.addEventListener("resize", resize);
    return () => {
      // Save viewport before unmount
      const vpt = c.viewportTransform;
      if (vpt) {
        _savedZoom = vpt[0];
        _savedPanX = vpt[4];
        _savedPanY = vpt[5];
      }
      window.removeEventListener("resize", resize);
      c.dispose();
      fabricRef.current = null;
    };
  }, []);

  // Keep finishRoom/finishExclusion refs updated
  const finishRoom = useCallback(() => {
    if (!currentRoom || currentRoom.vertices.length < 3) return;
    // Convert pixel coords to metres before saving
    const toMetres = (v: number[][]) => v.map(([x, y]) => pixelToMetres(x, y));
    const name = `Room ${rooms.length + 1}`;
    const newRoom: RoomData = {
      id: nextId(),
      name,
      vertices: toMetres(currentRoom.vertices),
      pixelVertices: currentRoom.vertices.map((p) => [...p]),
      exclusions: currentRoom.exclusions.map((e) => toMetres(e)),
      pixelExclusions: currentRoom.exclusions.map((e) => e.map((p) => [...p])),
    };
    onRoomsChange([...rooms, newRoom]);
    setCurrentRoom(null);
    setCurrentExcl([]);
  }, [currentRoom, rooms, onRoomsChange]);

  const finishExclusion = useCallback(() => {
    if (currentExcl.length < 3 || !currentRoom) return;
    // Add exclusion to room data
    setCurrentRoom({
      ...currentRoom,
      exclusions: [...currentRoom.exclusions, [...currentExcl]],
    });
    // Draw a permanent visual for the finished exclusion on canvas
    const c = fabricRef.current;
    if (c) {
      const pts = currentExcl.map((p) => ({ x: p[0], y: p[1] }));
      const poly = new fabric.Polygon(pts, {
        fill: EXCL_FILL,
        stroke: EXCL_COLOR,
        strokeWidth: 1.5,
        selectable: false,
        evented: false,
        _type: "excl",
      });
      c.add(poly);
      c.renderAll();
    }
    setCurrentExcl([]);
  }, [currentExcl, currentRoom]);

  useEffect(() => {
    finishRoomRef.current = finishRoom;
  }, [finishRoom]);
  useEffect(() => {
    finishExclRef.current = finishExclusion;
  }, [finishExclusion]);

  // ===== Load layer list from DXF =====
  useEffect(() => {
    if (!dxfPath) return;
    fetch(`/api/dxf/layers?path=${encodeURIComponent(dxfPath)}`)
      .then((r) => r.json())
      .then((data) => {
        setLayerList(data.layers || []);
        setSelectedLayers(new Set((data.layers || []).map((l: any) => l.name)));
      })
      .catch(() => {});
  }, [dxfPath]);

  // ===== Load DXF SVG background with layer filter =====
  useEffect(() => {
    const c = fabricRef.current;
    if (!c || !dxfPath) return;
    const t = Date.now();
    const layersParam = Array.from(selectedLayers).join(",");
    const url = `/api/dxf/render?path=${encodeURIComponent(dxfPath)}&width=${SVG_RENDER_W}&height=${SVG_RENDER_H}&layers=${encodeURIComponent(layersParam)}&_=${t}`;
    console.log("[Editor] Loading DXF SVG background...");
    c.backgroundImage = undefined;
    c.setBackgroundImage(
      url,
      () => {
        const img = c.backgroundImage;
        if (img) {
          const sx = c.width! / SVG_RENDER_W;
          const sy = c.height! / SVG_RENDER_H;
          img.set({ scaleX: sx, scaleY: sy, left: 0, top: 0 });
          c.renderAll();
        }
        // Force room re-render after background loads (fixes vanish on back)
        drawRooms(c, roomsRef.current);
      },
      {
        scaleX: 1,
        scaleY: 1,
        originX: "left",
        originY: "top",
        left: 0,
        top: 0,
      },
    );
  }, [dxfPath, selectedLayers]);

  // Draw rooms on canvas (extracted for reuse)
  // Room vertices are in metres — convert to canvas pixels via metresToPixel
  const drawRooms = useCallback((c: fabric.Canvas, roomList: RoomData[]) => {
    const toRemove = c
      .getObjects()
      .filter(
        (o: any) =>
          o._type === "room" || o._type === "excl" || o._type === "label",
      );
    toRemove.forEach((o) => c.remove(o));

    for (const room of roomList) {
      if (room.vertices.length >= 3) {
        // Use exact pixel coords when available, fall back to metres→pixels
        const src = room.pixelVertices || room.vertices;
        const pts = src.map((p) => {
          if (room.pixelVertices) return { x: p[0], y: p[1] };
          const [px, py] = metresToPixel(p[0], p[1]);
          return { x: px, y: py };
        });
        c.add(
          new fabric.Polygon(pts, {
            fill: ROOM_FILL,
            stroke: ROOM_COLOR,
            strokeWidth: 1.5,
            selectable: false,
            evented: false,
            _type: "room",
          }),
        );
        const cx = pts.reduce((s, p) => s + p.x, 0) / pts.length;
        const cy = pts.reduce((s, p) => s + p.y, 0) / pts.length;
        c.add(
          new fabric.Text(`${room.name}\n${room.area?.toFixed(1) || ""}m²`, {
            left: cx,
            top: cy,
            fontSize: 10,
            fill: "#e2e8f0",
            originX: "center",
            originY: "center",
            selectable: false,
            evented: false,
            _type: "label",
          }),
        );
      }
      for (let i = 0; i < room.exclusions.length; i++) {
        const exc = room.exclusions[i];
        if (exc.length >= 3) {
          const pxSrc = room.pixelExclusions?.[i] || exc;
          const pts = pxSrc.map((p) => {
            if (room.pixelExclusions) return { x: p[0], y: p[1] };
            const [px, py] = metresToPixel(p[0], p[1]);
            return { x: px, y: py };
          });
          c.add(
            new fabric.Polygon(pts, {
              fill: EXCL_FILL,
              stroke: EXCL_COLOR,
              strokeWidth: 2,
              selectable: false,
              evented: false,
              _type: "excl",
            }),
          );
        }
      }
    }
    c.renderAll();
  }, []);

  // ===== Re-render rooms when they change =====
  useEffect(() => {
    const c = fabricRef.current;
    if (!c) {
      console.warn("[Rooms] No canvas");
      return;
    }
    console.log(
      "[Rooms] Drawing",
      rooms.length,
      "rooms, coords:",
      rooms[0]?.vertices.slice(0, 2),
    );
    drawRooms(c, rooms);
  }, [rooms, drawRooms]);

  // ===== Render current drawing =====
  useEffect(() => {
    const c = fabricRef.current;
    if (!c) return;
    const toRemove = c.getObjects().filter((o: any) => o._temp);
    toRemove.forEach((o) => c.remove(o));

    if (currentRoom && currentRoom.vertices.length >= 2) {
      const pts = currentRoom.vertices.map((p) => ({ x: p[0], y: p[1] }));
      if (pts.length >= 3) {
        c.add(
          new fabric.Polygon(pts, {
            fill: "rgba(16, 185, 129, 0.12)",
            stroke: ROOM_COLOR,
            strokeWidth: 2,
            selectable: false,
            evented: false,
            _temp: true,
          }),
        );
      }
      pts.forEach((p) => {
        c.add(
          new fabric.Circle({
            left: p.x - 3,
            top: p.y - 3,
            radius: 3,
            fill: ROOM_COLOR,
            selectable: false,
            evented: false,
            _temp: true,
          }),
        );
      });
    }

    if (currentExcl.length >= 2) {
      const pts = currentExcl.map((p) => ({ x: p[0], y: p[1] }));
      if (pts.length >= 3) {
        c.add(
          new fabric.Polygon(pts, {
            fill: "rgba(239, 68, 68, 0.15)",
            stroke: EXCL_COLOR,
            strokeWidth: 2,
            selectable: false,
            evented: false,
            _temp: true,
          }),
        );
      }
      pts.forEach((p) => {
        c.add(
          new fabric.Circle({
            left: p.x - 3,
            top: p.y - 3,
            radius: 3,
            fill: EXCL_COLOR,
            selectable: false,
            evented: false,
            _temp: true,
          }),
        );
      });
    }
    c.renderAll();
  }, [currentRoom, currentExcl]);

  const handleUndo = useCallback(() => {
    if (mode === "exclusion" && currentExcl.length > 0) {
      setCurrentExcl((p) => p.slice(0, -1));
      return;
    }
    if (currentRoom && currentRoom.vertices.length > 0) {
      setCurrentRoom((p) =>
        p ? { ...p, vertices: p.vertices.slice(0, -1) } : null,
      );
      return;
    }
    if (rooms.length > 0) onRoomsChange(rooms.slice(0, -1));
  }, [mode, currentExcl, currentRoom, rooms, onRoomsChange]);

  const handleDelete = useCallback(() => {
    if (rooms.length > 0) onRoomsChange(rooms.slice(0, -1));
  }, [rooms, onRoomsChange]);

  const handleFitView = useCallback(() => {
    const c = fabricRef.current;
    if (!c) return;
    c.setZoom(1);
    c.viewportTransform = [1, 0, 0, 1, 0, 0];
    c.requestRenderAll();
  }, []);

  const totalArea = rooms.reduce((s, r) => s + (r.area || 0), 0);

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center shrink-0">
        <Toolbar
          mode={mode}
          onModeChange={(m) => setMode(m)}
          onUndo={handleUndo}
          onFitView={handleFitView}
          onDelete={handleDelete}
          onFinishRoom={finishRoom}
          onFinishExclusion={finishExclusion}
          onCalculate={onCalculate}
          calculating={calculating}
          roomCount={rooms.length}
          totalArea={totalArea}
        />
        <button
          onClick={() => {
            if (calibratingRef.current) {
              setCalibrating(false);
              calibratingRef.current = false;
              calPointA.current = null;
            } else {
              setCalibrating(true);
              calibratingRef.current = true;
            }
          }}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all shrink-0 mr-1 ${
            calibrating
              ? "bg-warning/20 text-warning animate-pulse"
              : "text-slate-400 hover:text-slate-200 hover:bg-slate-700/50"
          }`}
          title="Calibrate scale by clicking two known points"
        >
          {calibrating
            ? "⚡ Click 2 points..."
            : calFactor
              ? `Cal ${calFactor.toFixed(3)}`
              : "Calibrate"}
        </button>
        <button
          onClick={() => setShowLayers(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs text-slate-400 hover:text-slate-200 hover:bg-slate-700/50 transition-all shrink-0 mr-1"
          title="Filter layers"
        >
          &#9776; Layers ({selectedLayers.size}/{layerList.length})
        </button>
        <a
          href={`/api/dxf/download?path=${encodeURIComponent(dxfPath)}`}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs text-slate-400 hover:text-slate-200 hover:bg-slate-700/50 transition-all shrink-0 mr-2"
          title="Download DXF file"
        >
          ⬇ DXF
        </a>
      </div>

      {/* Layers modal */}
      {showLayers && (
        <div
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: "rgba(0,0,0,0.5)",
            zIndex: 1000,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
          onClick={() => setShowLayers(false)}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              background: "#1e293b",
              border: "1px solid #334155",
              borderRadius: 12,
              padding: 20,
              maxWidth: 400,
              width: "90%",
              maxHeight: "70vh",
              overflowY: "auto",
            }}
          >
            <h3 style={{ color: "#e2e8f0", fontSize: 14, marginBottom: 12 }}>
              DXF Layers
            </h3>
            {layerList.map((layer) => (
              <label
                key={layer.name}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "6px 8px",
                  cursor: "pointer",
                  borderRadius: 4,
                  fontSize: 13,
                  color: "#cbd5e1",
                }}
              >
                <input
                  type="checkbox"
                  checked={selectedLayers.has(layer.name)}
                  onChange={() => {
                    const next = new Set(selectedLayers);
                    if (next.has(layer.name)) next.delete(layer.name);
                    else next.add(layer.name);
                    setSelectedLayers(next);
                  }}
                />
                <span>{layer.name}</span>
                <span
                  style={{ marginLeft: "auto", color: "#64748b", fontSize: 11 }}
                >
                  {layer.count}
                </span>
              </label>
            ))}
          </div>
        </div>
      )}

      <div className="flex-1 flex overflow-hidden">
        <div
          ref={containerRef}
          className="flex-1 relative overflow-hidden"
          style={{
            cursor:
              mode === "pan"
                ? "grab"
                : mode === "select"
                  ? "default"
                  : "crosshair",
          }}
        >
          <canvas ref={canvasRef} />
        </div>
        <RoomPanel
          rooms={rooms}
          onRoomsChange={onRoomsChange}
          currentRoom={currentRoom}
          currentExcl={currentExcl}
          onFinishRoom={finishRoom}
          onFinishExclusion={finishExclusion}
        />
      </div>
    </div>
  );
}
