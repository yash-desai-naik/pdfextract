import { useState, useCallback, useRef } from "react";
import type { MarkedArea, ToolMode } from "../types";
import { polygonArea, polygonPerimeter, polygonDimensions } from "../geometry";

let idCounter = 0;
function nextId() {
  return `area_${++idCounter}`;
}

export function useDrawing(pxPerMetre: number) {
  const [mode, setMode] = useState<ToolMode>("pan");
  const [areas, setAreas] = useState<MarkedArea[]>([]);
  const [currentPts, setCurrentPts] = useState<number[][]>([]);
  const finishingRef = useRef(false);

  const addPoint = useCallback((pt: [number, number]) => {
    setCurrentPts((prev) => [...prev, pt]);
  }, []);

  const undoPoint = useCallback(() => {
    setCurrentPts((prev) => prev.slice(0, -1));
  }, []);

  const clearPoints = useCallback(() => {
    setCurrentPts([]);
  }, []);

  const finishArea = useCallback(
    (type: "room" | "exclusion", customName?: string) => {
      if (finishingRef.current) return;
      finishingRef.current = true;
      setTimeout(() => {
        finishingRef.current = false;
      }, 200);

      const pts = currentPts;
      if (pts.length < 3) return;

      const areaPx = polygonArea(pts);
      const perimPx = polygonPerimeter(pts);
      const areaM2 = areaPx / (pxPerMetre * pxPerMetre);
      const perimeterM = perimPx / pxPerMetre;
      const dims = polygonDimensions(pts, pxPerMetre);

      let name = customName;
      if (!name) {
        const count = areas.filter((a) => a.type === type).length + 1;
        name = type === "room" ? `Room ${count}` : `Exclusion ${count}`;
      }

      const newArea: MarkedArea = {
        id: nextId(),
        name,
        type,
        vertices: pts,
        areaPx,
        areaM2,
        perimeterM,
        dimensions: dims,
      };

      if (type === "exclusion") {
        const cx = pts.reduce((s, p) => s + p[0], 0) / pts.length;
        const cy = pts.reduce((s, p) => s + p[1], 0) / pts.length;
        for (const area of areas) {
          if (
            area.type === "room" &&
            pointInPolygonSimple(cx, cy, area.vertices)
          ) {
            newArea.name = `${area.name} - ${name}`;
            break;
          }
        }
      }

      setAreas((prev) => [...prev, newArea]);
      setCurrentPts([]);
    },
    [currentPts, pxPerMetre, areas],
  );

  const removeArea = useCallback((id: string) => {
    setAreas((prev) => prev.filter((a) => a.id !== id));
  }, []);

  const renameArea = useCallback((id: string, name: string) => {
    setAreas((prev) => prev.map((a) => (a.id === id ? { ...a, name } : a)));
  }, []);

  const reset = useCallback(() => {
    setAreas([]);
    setCurrentPts([]);
  }, []);

  return {
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
    reset,
  };
}

function pointInPolygonSimple(
  px: number,
  py: number,
  polygon: number[][],
): boolean {
  let inside = false;
  const n = polygon.length;
  for (let i = 0, j = n - 1; i < n; j = i++) {
    const xi = polygon[i][0],
      yi = polygon[i][1];
    const xj = polygon[j][0],
      yj = polygon[j][1];
    if (yi > py !== yj > py && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi) {
      inside = !inside;
    }
  }
  return inside;
}
