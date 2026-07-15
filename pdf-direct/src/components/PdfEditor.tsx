import { useEffect, useRef, useCallback, useState } from "react";
import {
  TransformWrapper,
  TransformComponent,
  useTransformContext,
} from "react-zoom-pan-pinch";
import type { MarkedArea, ToolMode } from "../types";
import { dist } from "../geometry";

interface Props {
  canvasRef: React.RefObject<HTMLCanvasElement | null>;
  pdfCacheRef: React.RefObject<HTMLCanvasElement | null>;
  pageWidth: number;
  pageHeight: number;
  pdfReady: boolean;
  renderTick: number;
  reRender: (scale: number) => void;
  mode: ToolMode;
  areas: MarkedArea[];
  currentPts: number[][];
  onAddPoint: (pt: [number, number]) => void;
  onFinish: () => void;
  calibration: {
    method: "length" | "area";
    point1: [number, number] | null;
    point2: [number, number] | null;
    knownLengthM: number;
    polygon: number[][];
    knownAreaM2: number;
    pxPerMetre: number;
  };
  onSetCalPoint1: (pt: [number, number]) => void;
  onSetCalPoint2: (pt: [number, number]) => void;
  pxPerMetre: number;
  onSetKnownLength: (m: number) => void;
  calAreaPts: number[][] | null;
  onConfirmCalArea: (m2: number) => void;
  onCancelCalArea: () => void;
}

const ROOM_COLOR = "#10b981";
const EXCL_COLOR = "#ef4444";
const CAL_COLOR = "#f59e0b";
const ROOM_FILL = "rgba(16, 185, 129, 0.12)";
const EXCL_FILL = "rgba(239, 68, 68, 0.15)";

/** Inner component that has access to transform context for coordinate conversion */
function CanvasContent({
  pdfCacheRef,
  pdfReady,
  renderTick,
  reRender,
  mode,
  areas,
  currentPts,
  onAddPoint,
  onFinish,
  calibration,
  onSetCalPoint1,
  onSetCalPoint2,
  pxPerMetre,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { state } = useTransformContext();
  const { scale, positionX, positionY } = state;
  const modeRef = useRef(mode);
  modeRef.current = mode;
  const cursorPos = useRef<[number, number] | null>(null);
  const lastRenderZoom = useRef(1.5);

  // Re-render PDF at higher resolution when zoomed in
  useEffect(() => {
    const targetScale = 1.5 * scale;
    const ratio = targetScale / lastRenderZoom.current;
    // Re-render when zoom changes by >30% or drops below 1x
    if (ratio < 0.7 || ratio > 1.3 || targetScale < 1) {
      lastRenderZoom.current = Math.max(targetScale, 1.5);
      reRender(lastRenderZoom.current);
    }
  }, [scale, reRender]);

  const natW = pdfCacheRef.current?.width || 1200;
  const natH = pdfCacheRef.current?.height || 1600;

  // Convert screen coords (relative to canvas rect) → content coords
  // getBoundingClientRect() already accounts for the CSS transform,
  // so no need to subtract positionX/Y — just un-scale.
  const screenToContent = useCallback(
    (sx: number, sy: number): [number, number] => {
      return [sx / scale, sy / scale];
    },
    [scale],
  );

  // Get mouse position relative to the content canvas
  const mouseContent = useCallback(
    (e: { clientX: number; clientY: number }): [number, number] => {
      const r = canvasRef.current!.getBoundingClientRect();
      return screenToContent(e.clientX - r.left, e.clientY - r.top);
    },
    [screenToContent],
  );

  // ---- Drawing ----
  const draw = useCallback(() => {
    const c = canvasRef.current;
    if (!c) return;
    const ctx = c.getContext("2d")!;
    ctx.clearRect(0, 0, c.width, c.height);

    // Draw at content (world) coordinates — CSS transform on wrapper handles visual zoom
    const sw = 2;
    const vr = 4;
    const fs = 12;

    // PDF background
    const pdfCache = pdfCacheRef.current;
    if (pdfCache) {
      ctx.drawImage(pdfCache, 0, 0, c.width, c.height);
    }

    // Areas
    for (const area of areas) {
      const color = area.type === "room" ? ROOM_COLOR : EXCL_COLOR;
      const fill = area.type === "room" ? ROOM_FILL : EXCL_FILL;
      drawPolygon(ctx, area.vertices, fill, color, sw);
      const cx =
        area.vertices.reduce((s, p) => s + p[0], 0) / area.vertices.length;
      const cy =
        area.vertices.reduce((s, p) => s + p[1], 0) / area.vertices.length;
      ctx.fillStyle = "#e2e8f0";
      ctx.font = `${fs}px Inter, sans-serif`;
      ctx.textAlign = "center";
      ctx.fillText(`${area.name}: ${area.areaM2.toFixed(1)} m²`, cx, cy);
    }

    // Calibration
    if (calibration.point1)
      drawCross(
        ctx,
        calibration.point1[0],
        calibration.point1[1],
        CAL_COLOR,
        sw,
      );
    if (calibration.point2)
      drawCross(
        ctx,
        calibration.point2[0],
        calibration.point2[1],
        CAL_COLOR,
        sw,
      );
    if (calibration.point1 && calibration.point2) {
      const [x1, y1] = calibration.point1;
      const [x2, y2] = calibration.point2;
      ctx.strokeStyle = CAL_COLOR;
      ctx.lineWidth = sw;
      ctx.setLineDash([5, 5]);
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.lineTo(x2, y2);
      ctx.stroke();
      ctx.setLineDash([]);
      const lenPx = dist(calibration.point1, calibration.point2);
      const lenM =
        calibration.pxPerMetre > 0 ? lenPx / calibration.pxPerMetre : 0;
      ctx.fillStyle = CAL_COLOR;
      ctx.font = `bold ${fs}px Inter, sans-serif`;
      ctx.textAlign = "center";
      ctx.fillText(
        `${lenPx.toFixed(0)} px${calibration.pxPerMetre > 0 ? ` = ${lenM.toFixed(2)} m` : ""}`,
        (x1 + x2) / 2,
        (y1 + y2) / 2 - 8,
      );
    }

    // Current drawing
    if (currentPts.length > 0) {
      const isExcl = modeRef.current === "exclusion";
      const isCalArea = modeRef.current === "calibrate-area";
      const color = isExcl ? EXCL_COLOR : isCalArea ? CAL_COLOR : ROOM_COLOR;
      const fill = isExcl
        ? EXCL_FILL
        : isCalArea
          ? "rgba(245, 158, 11, 0.12)"
          : ROOM_FILL;
      if (currentPts.length >= 3) drawPolygon(ctx, currentPts, fill, color, sw);
      for (const [x, y] of currentPts) {
        ctx.beginPath();
        ctx.arc(x, y, vr, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.fill();
      }
    }

    // Custom cursor indicator — visible on any background
    const cp = cursorPos.current;
    if (cp && modeRef.current !== "pan") {
      const m = modeRef.current;
      const cursorColor =
        m === "exclusion"
          ? EXCL_COLOR
          : m === "calibrate" || m === "calibrate-area"
            ? CAL_COLOR
            : ROOM_COLOR;
      const r = Math.max(6, 14 / scale); // fixed ~14px visual size
      ctx.strokeStyle = cursorColor;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(cp[0], cp[1], r, 0, Math.PI * 2);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(cp[0] - r - 4, cp[1]);
      ctx.lineTo(cp[0] + r + 4, cp[1]);
      ctx.moveTo(cp[0], cp[1] - r - 4);
      ctx.lineTo(cp[0], cp[1] + r + 4);
      ctx.stroke();
    }
  }, [
    areas,
    currentPts,
    calibration,
    pdfCacheRef,
    pdfReady,
    scale,
    cursorPos,
    renderTick,
  ]);

  useEffect(() => {
    draw();
  }, [draw, scale, positionX, positionY]);

  // ---- Mouse events ----
  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      const m = modeRef.current;
      if (e.button === 0 && m !== "pan") {
        const [wx, wy] = mouseContent(e);
        if (m === "calibrate") {
          if (!calibration.point1) onSetCalPoint1([wx, wy]);
          else if (!calibration.point2) onSetCalPoint2([wx, wy]);
          return;
        }
        onAddPoint([wx, wy]);
      } else if (e.button === 2) {
        if (m === "room" || m === "exclusion" || m === "calibrate-area")
          onFinish();
      }
    },
    [
      calibration,
      mouseContent,
      onAddPoint,
      onFinish,
      onSetCalPoint1,
      onSetCalPoint2,
    ],
  );

  const handleMouseMove = useCallback(
    (e: React.MouseEvent) => {
      // Track cursor position for custom cursor indicator
      cursorPos.current = mouseContent(e);
      draw();
      if (currentPts.length === 0) return;
      const c = canvasRef.current;
      if (!c) return;
      const ctx = c.getContext("2d")!;
      draw();
      const [wx, wy] = mouseContent(e);
      const last = currentPts[currentPts.length - 1];
      const isExcl = modeRef.current === "exclusion";
      const isCalArea = modeRef.current === "calibrate-area";
      const color = isExcl ? EXCL_COLOR : isCalArea ? CAL_COLOR : ROOM_COLOR;
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.5;
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(last[0], last[1]);
      ctx.lineTo(wx, wy);
      ctx.stroke();
      ctx.setLineDash([]);
      if (pxPerMetre > 0) {
        const lenPx = dist(last, [wx, wy]);
        const lenM = lenPx / pxPerMetre;
        ctx.fillStyle = color;
        ctx.font = "11px DM Mono, monospace";
        ctx.textAlign = "center";
        ctx.fillText(
          `${lenM.toFixed(2)} m`,
          (last[0] + wx) / 2,
          (last[1] + wy) / 2 - 6,
        );
      }
    },
    [currentPts, pxPerMetre, draw, mouseContent],
  );

  const handleMouseLeave = useCallback(() => {
    cursorPos.current = null;
    draw();
  }, [draw]);

  return (
    <canvas
      ref={canvasRef}
      width={natW}
      height={natH}
      style={{
        display: "block",
        maxWidth: "none",
        touchAction: "none",
        cursor: mode === "pan" ? "grab" : "none",
        caretColor: "transparent",
      }}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
      onContextMenu={(e) => e.preventDefault()}
    />
  );
}

// ---- Outer component with TransformWrapper ----
export default function PdfEditor(props: Props) {
  const { pdfCacheRef, pdfReady, mode, calibration, onSetKnownLength } = props;
  const [zoom, setZoom] = useState(1);

  // Wait for PDF to finish loading so canvas dimensions match PDF exactly
  const natW = pdfCacheRef.current?.width || 0;
  const natH = pdfCacheRef.current?.height || 0;
  const hasPdf = pdfReady && natW > 0 && natH > 0;

  return (
    <div className="h-full flex flex-col">
      <div className="flex-1 relative overflow-hidden">
        {/* Hidden canvas for PDF.js rendering */}
        <canvas ref={props.canvasRef as any} style={{ display: "none" }} />

        {!hasPdf && (
          <div className="h-full flex items-center justify-center text-slate-500 text-sm">
            Loading PDF...
          </div>
        )}

        {hasPdf && (
          <TransformWrapper
            initialScale={1}
            minScale={0.1}
            maxScale={50}
            wheel={{ step: 0.03 }}
            pinch={{ step: 0.02 }}
            doubleClick={{ disabled: true }}
            onTransform={(_ref: any, event: any) => setZoom(event.scale || 1)}
            limitToBounds={false}
            centerZoomedOut={false}
            centerOnInit={false}
          >
            {() => (
              <TransformComponent
                wrapperStyle={{ width: "100%", height: "100%" }}
                contentStyle={{ lineHeight: "0" }}
              >
                <CanvasContent {...props} />
              </TransformComponent>
            )}
          </TransformWrapper>
        )}

        {/* Zoom badge */}
        <div className="absolute bottom-3 left-3 bg-slate-900/80 text-xs text-slate-400 font-mono px-2 py-1 rounded border border-slate-700/50 pointer-events-none select-none z-10">
          {Math.round(zoom * 100)}%
        </div>
      </div>

      {/* Length calibration modal */}
      {calibration.point1 &&
        calibration.point2 &&
        calibration.pxPerMetre === 0 && (
          <CalibrationModal
            px={Math.hypot(
              calibration.point2[0] - calibration.point1[0],
              calibration.point2[1] - calibration.point1[1],
            )}
            onConfirm={onSetKnownLength}
          />
        )}

      {/* Area calibration modal */}
      {props.calAreaPts && (
        <CalibrationAreaModal
          px={polygonArea(props.calAreaPts)}
          onConfirm={props.onConfirmCalArea}
          onCancel={props.onCancelCalArea}
        />
      )}
    </div>
  );
}

function drawPolygon(
  ctx: CanvasRenderingContext2D,
  pts: number[][],
  fill: string,
  stroke: string,
  lw: number,
) {
  if (pts.length < 2) return;
  ctx.beginPath();
  ctx.moveTo(pts[0][0], pts[0][1]);
  for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
  ctx.closePath();
  ctx.fillStyle = fill;
  ctx.fill();
  ctx.strokeStyle = stroke;
  ctx.lineWidth = lw;
  ctx.stroke();
}

function drawCross(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  color: string,
  lw: number,
) {
  const s = 6 / lw;
  ctx.strokeStyle = color;
  ctx.lineWidth = lw;
  ctx.beginPath();
  ctx.moveTo(x - s, y);
  ctx.lineTo(x + s, y);
  ctx.moveTo(x, y - s);
  ctx.lineTo(x, y + s);
  ctx.stroke();
  ctx.beginPath();
  ctx.arc(x, y, 4 / lw, 0, Math.PI * 2);
  ctx.stroke();
}

function polygonArea(pts: number[][]): number {
  let a = 0;
  const n = pts.length;
  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n;
    a += pts[i][0] * pts[j][1] - pts[j][0] * pts[i][1];
  }
  return Math.abs(a) / 2;
}

// ---- Calibration modal (length) ----
function CalibrationModal({
  px,
  onConfirm,
}: {
  px: number;
  onConfirm: (m: number) => void;
}) {
  const [val, setVal] = useState(1);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);

  const handleConfirm = () => onConfirm(val);

  return (
    <div className="absolute inset-0 flex items-center justify-center bg-black/40 z-20">
      <div className="bg-slate-800 border border-slate-600 rounded-xl p-6 shadow-2xl w-80 animate-fade-in">
        <h3 className="text-sm font-semibold text-slate-100 mb-1">
          Calibrate Scale
        </h3>
        <p className="text-xs text-slate-400 mb-4">
          Line is{" "}
          <span className="text-slate-200 font-mono">{px.toFixed(0)} px</span>.
          Enter the real-world length:
        </p>
        <div className="flex items-center gap-3">
          <div className="relative flex-1">
            <input
              ref={inputRef}
              type="number"
              step="0.01"
              min="0.01"
              value={val}
              onChange={(e) => setVal(parseFloat(e.target.value) || 0.01)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleConfirm();
              }}
              className="bg-slate-700 text-sm text-slate-100 px-3 py-2 rounded-lg border border-slate-600 outline-none w-full font-mono"
            />
            <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-slate-500">
              m
            </span>
          </div>
          <button
            onClick={handleConfirm}
            className="bg-brand text-white text-xs font-medium px-4 py-2 rounded-lg hover:bg-brand-hover transition-colors shrink-0"
          >
            OK
          </button>
        </div>
        <p className="text-xs text-slate-500 mt-2">Press Enter or click OK</p>
      </div>
    </div>
  );
}

// ---- Calibration modal (area) ----
function CalibrationAreaModal({
  px,
  onConfirm,
  onCancel,
}: {
  px: number;
  onConfirm: (m2: number) => void;
  onCancel: () => void;
}) {
  const [val, setVal] = useState(1);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);

  const handleConfirm = () => onConfirm(val);

  return (
    <div className="absolute inset-0 flex items-center justify-center bg-black/40 z-20">
      <div className="bg-slate-800 border border-slate-600 rounded-xl p-6 shadow-2xl w-80 animate-fade-in">
        <h3 className="text-sm font-semibold text-slate-100 mb-1">
          Calibrate by Area
        </h3>
        <p className="text-xs text-slate-400 mb-4">
          Traced area is{" "}
          <span className="text-slate-200 font-mono">{px.toFixed(0)} px²</span>.
          Enter the real area:
        </p>
        <div className="flex items-center gap-3">
          <div className="relative flex-1">
            <input
              ref={inputRef}
              type="number"
              step="0.01"
              min="0.01"
              value={val}
              onChange={(e) => setVal(parseFloat(e.target.value) || 0.01)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleConfirm();
                if (e.key === "Escape") onCancel();
              }}
              className="bg-slate-700 text-sm text-slate-100 px-3 py-2 rounded-lg border border-slate-600 outline-none w-full font-mono"
            />
            <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-slate-500">
              m²
            </span>
          </div>
          <button
            onClick={handleConfirm}
            className="bg-brand text-white text-xs font-medium px-4 py-2 rounded-lg hover:bg-brand-hover transition-colors shrink-0"
          >
            OK
          </button>
          <button
            onClick={onCancel}
            className="text-xs text-slate-400 px-3 py-2 rounded-lg hover:bg-slate-700/50 transition-colors shrink-0"
          >
            Cancel
          </button>
        </div>
        <p className="text-xs text-slate-500 mt-2">
          Enter area in m² and press Enter
        </p>
      </div>
    </div>
  );
}
