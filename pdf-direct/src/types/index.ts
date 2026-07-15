export interface MarkedArea {
  id: string;
  name: string;
  type: "room" | "exclusion";
  vertices: number[][]; // pixel coords [x, y][]
  areaPx: number; // area in px²
  areaM2: number; // area in m²
  perimeterM: number;
  dimensions: string; // e.g. "8.0 × 6.0 m"
}

export interface Calibration {
  method: "length" | "area";
  // Length-based
  point1: number[] | null;
  point2: number[] | null;
  knownLengthM: number;
  // Area-based
  polygon: number[][]; // vertices of calibration polygon in px
  knownAreaM2: number;
  // Computed
  pxPerMetre: number;
}

export type ToolMode =
  "pan" | "calibrate" | "calibrate-area" | "room" | "rect" | "exclusion";

export interface WarmsetRoom {
  name: string;
  grossAreaM2: number;
  excludedAreaM2: number;
  netHeatableM2: number;
  matAreaM2: number;
  stripCount: number;
  totalLinearM: number;
  coveragePct: number;
  setbackM: number;
}

export interface WarmsetResult {
  rooms: WarmsetRoom[];
  totals: Record<string, number>;
}
