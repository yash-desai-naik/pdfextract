import { useState } from "react";

export function useCalibration() {
  const [calibration, setCalibration] = useState({
    method: "length" as "length" | "area",
    point1: null as [number, number] | null,
    point2: null as [number, number] | null,
    knownLengthM: 1,
    polygon: [] as number[][],
    knownAreaM2: 1,
    pxPerMetre: 0,
  });

  const setPoint1 = (pt: [number, number] | null) => {
    setCalibration((c) => ({ ...c, point1: pt, method: "length" }));
  };

  const setPoint2 = (pt: [number, number] | null) => {
    setCalibration((c) => ({ ...c, point2: pt }));
  };

  const setKnownLength = (m: number) => {
    setCalibration((c) => ({ ...c, knownLengthM: m }));
  };

  const addPolygonPt = (pt: [number, number]) => {
    setCalibration((c) => ({
      ...c,
      polygon: [...c.polygon, pt],
      method: "area",
    }));
  };

  const undoPolygonPt = () => {
    setCalibration((c) => ({ ...c, polygon: c.polygon.slice(0, -1) }));
  };

  const setKnownArea = (m2: number) => {
    setCalibration((c) => ({ ...c, knownAreaM2: m2 }));
  };

  const computeScale = (lenM?: number, polygon?: number[][]) => {
    // If polygon is provided, use area-based calibration regardless of method
    if (polygon && polygon.length >= 3) {
      const finalArea = lenM ?? calibration.knownAreaM2;
      if (finalArea <= 0) return;
      const areaPx = polygonArea(polygon);
      if (areaPx <= 0) return;
      setCalibration((prev) => ({
        ...prev,
        method: "area",
        polygon,
        pxPerMetre: Math.sqrt(areaPx / finalArea),
        knownAreaM2: finalArea,
      }));
      return;
    }
    // Length-based calibration
    const c = calibration;
    const finalLen = lenM ?? c.knownLengthM;
    if (!c.point1 || !c.point2 || finalLen <= 0) return;
    const px = Math.hypot(c.point2[0] - c.point1[0], c.point2[1] - c.point1[1]);
    setCalibration((prev) => ({
      ...prev,
      method: "length",
      pxPerMetre: px / finalLen,
      knownLengthM: finalLen,
    }));
  };

  const reset = () => {
    setCalibration({
      method: "length",
      point1: null,
      point2: null,
      knownLengthM: 1,
      polygon: [],
      knownAreaM2: 1,
      pxPerMetre: 0,
    });
  };

  return {
    calibration,
    setPoint1,
    setPoint2,
    setKnownLength,
    addPolygonPt,
    undoPolygonPt,
    setKnownArea,
    computeScale,
    reset,
  };
}

function polygonArea(pts: number[][]): number {
  let area = 0;
  const n = pts.length;
  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n;
    area += pts[i][0] * pts[j][1];
    area -= pts[j][0] * pts[i][1];
  }
  return Math.abs(area) / 2;
}
