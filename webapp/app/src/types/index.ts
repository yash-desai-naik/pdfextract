export interface DXFEntity {
  type: "Feature";
  geometry: {
    type: "LineString" | "Point";
    coordinates: number[][] | number[];
  };
  properties: {
    type: string;
    layer: string;
    closed?: boolean;
    radius?: number;
    text?: string;
    height?: number;
  };
}

export interface DXFData {
  type: "FeatureCollection";
  features: DXFEntity[];
  bounds: number[];
  unit: string;
  unit_to_m: number;
  entity_count: number;
}

export interface RoomData {
  id: string;
  name: string;
  vertices: number[][]; // in metres (for calculation)
  pixelVertices?: number[][]; // in canvas pixels (for rendering, exact)
  exclusions: number[][][];
  pixelExclusions?: number[][][];
  area?: number;
}

export interface RoomExclusion {
  vertices: number[][];
}

export interface TakeoffRoom {
  name: string;
  gross_area_m2: number;
  excluded_area_m2: number;
  net_heatable_area_m2: number;
  mat_area_m2: number;
  strip_count: number;
  total_linear_m: number;
  coverage_pct: number;
  setback_distance_m: number;
}

export interface TakeoffResult {
  status: string;
  rooms: TakeoffRoom[];
  totals: Record<string, number>;
}

export type AppMode = "upload" | "editor" | "results";
export type EditorMode = "select" | "room" | "exclusion" | "pan" | "freeform";
