/** Pixel-space geometry utilities — all area/length in px, caller converts via scale */

export function polygonArea(pts: number[][]): number {
  // Shoelace formula
  let area = 0;
  const n = pts.length;
  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n;
    area += pts[i][0] * pts[j][1];
    area -= pts[j][0] * pts[i][1];
  }
  return Math.abs(area) / 2;
}

export function polygonPerimeter(pts: number[][]): number {
  let perim = 0;
  const n = pts.length;
  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n;
    perim += dist(pts[i], pts[j]);
  }
  return perim;
}

export function dist(a: number[], b: number[]): number {
  return Math.hypot(a[0] - b[0], a[1] - b[1]);
}

/** Bounding box of polygon */
export function bbox(pts: number[][]): [number, number, number, number] {
  let minX = Infinity,
    minY = Infinity,
    maxX = -Infinity,
    maxY = -Infinity;
  for (const p of pts) {
    if (p[0] < minX) minX = p[0];
    if (p[0] > maxX) maxX = p[0];
    if (p[1] < minY) minY = p[1];
    if (p[1] > maxY) maxY = p[1];
  }
  return [minX, minY, maxX, maxY];
}

/** Return approx. width/height description from bounding box */
export function polygonDimensions(pts: number[][], pxPerMetre: number): string {
  const [minX, minY, maxX, maxY] = bbox(pts);
  const w = (maxX - minX) / pxPerMetre;
  const h = (maxY - minY) / pxPerMetre;
  return `${w.toFixed(1)} × ${h.toFixed(1)} m`;
}

/** Point-in-polygon test (ray casting) */
export function pointInPolygon(
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

/**
 * Compute net heatable polygon by subtracting exclusions from room polygon.
 * Uses a simple grid-based boolean subtraction (pixel accurate enough for takeoff).
 * Returns: [netAreaPx, excludedAreaPx]
 */
export function subtractExclusions(
  roomPts: number[][],
  exclusions: number[][][],
  resolution = 2, // sample every N px for perf
): [number, number] {
  const [minX, minY, maxX, maxY] = bbox(roomPts);
  let inRoom = 0,
    inExcluded = 0;
  for (let y = minY; y <= maxY; y += resolution) {
    for (let x = minX; x <= maxX; x += resolution) {
      if (pointInPolygon(x, y, roomPts)) {
        inRoom++;
        let excluded = false;
        for (const exc of exclusions) {
          if (pointInPolygon(x, y, exc)) {
            excluded = true;
            break;
          }
        }
        if (excluded) inExcluded++;
      }
    }
  }
  const pxArea = polygonArea(roomPts);
  const exclPxArea = (inExcluded / inRoom) * pxArea;
  return [pxArea - exclPxArea, exclPxArea];
}

/**
 * Approximate inward offset (setback) using centroid scaling.
 * For prototype — reduces polygon by scaling toward centroid.
 */
export function shrinkPolygon(pts: number[][], offsetPx: number): number[][] {
  const cx = pts.reduce((s, p) => s + p[0], 0) / pts.length;
  const cy = pts.reduce((s, p) => s + p[1], 0) / pts.length;
  // Compute avg distance from centroid to vertices
  const avgDist = pts.reduce((s, p) => s + dist(p, [cx, cy]), 0) / pts.length;
  const scale = Math.max(0, (avgDist - offsetPx) / avgDist);
  return pts.map(([x, y]) => [cx + (x - cx) * scale, cy + (y - cy) * scale]);
}

/**
 * Generate Warmset strips (500mm wide) along the dominant axis.
 * Returns strip count and total linear metres.
 */
export function generateStrips(
  polyPts: number[][],
  pxPerMetre: number,
  stripWidthM = 0.5,
): { stripCount: number; totalLinearM: number; stripLengthsM: number[] } {
  const [minX, minY, maxX, maxY] = bbox(polyPts);
  const stripWidthPx = stripWidthM * pxPerMetre;
  const w = maxX - minX;
  const h = maxY - minY;

  // Determine dominant axis (longer dimension = strip direction)
  const horizontal = w >= h;
  const strips: number[] = [];

  if (horizontal) {
    // Strips run horizontally (left-right), spaced vertically
    for (let y = minY + stripWidthPx / 2; y < maxY; y += stripWidthPx) {
      let inStrip = false;
      let stripStart = 0;
      for (let x = minX; x <= maxX; x += 1) {
        const inside = pointInPolygon(x, y, polyPts);
        if (inside && !inStrip) {
          stripStart = x;
          inStrip = true;
        } else if (!inside && inStrip) {
          const len = (x - stripStart) / pxPerMetre;
          if (len > 0.3) strips.push(len); // filter < 300mm
          inStrip = false;
        }
      }
      if (inStrip) {
        const len = (maxX - stripStart) / pxPerMetre;
        if (len > 0.3) strips.push(len);
      }
    }
  } else {
    // Strips run vertically (top-bottom), spaced horizontally
    for (let x = minX + stripWidthPx / 2; x < maxX; x += stripWidthPx) {
      let inStrip = false;
      let stripStart = 0;
      for (let y = minY; y <= maxY; y += 1) {
        const inside = pointInPolygon(x, y, polyPts);
        if (inside && !inStrip) {
          stripStart = y;
          inStrip = true;
        } else if (!inside && inStrip) {
          const len = (y - stripStart) / pxPerMetre;
          if (len > 0.3) strips.push(len);
          inStrip = false;
        }
      }
      if (inStrip) {
        const len = (maxY - stripStart) / pxPerMetre;
        if (len > 0.3) strips.push(len);
      }
    }
  }

  const totalLinearM = strips.reduce((s, l) => s + l, 0);
  return { stripCount: strips.length, totalLinearM, stripLengthsM: strips };
}

/**
 * Full Warmset takeoff for one room.
 */
export function computeRoomTakeoff(
  roomPts: number[][],
  exclusionPts: number[][][],
  pxPerMetre: number,
  setbackM = 0.1,
): {
  grossAreaM2: number;
  excludedAreaM2: number;
  netAreaPx: number;
  netHeatableM2: number;
  matAreaM2: number;
  stripCount: number;
  totalLinearM: number;
  coveragePct: number;
} {
  const grossPx = polygonArea(roomPts);
  const grossM2 = grossPx / (pxPerMetre * pxPerMetre);

  // Subtract exclusions
  const [netPx, exclPx] = subtractExclusions(roomPts, exclusionPts);
  const exclM2 = exclPx / (pxPerMetre * pxPerMetre);

  // Apply setback
  const setbackPx = setbackM * pxPerMetre;
  const shrunkPts = shrinkPolygon(
    // Use vertices of net polygon - estimate from room minus exclusion proportion
    roomPts,
    setbackPx,
  );
  const setbackPxLoss = netPx - polygonArea(shrunkPts);
  const netM2 = (netPx - setbackPxLoss) / (pxPerMetre * pxPerMetre);

  // Generate strips on shrunk polygon
  const { stripCount, totalLinearM } = generateStrips(shrunkPts, pxPerMetre);
  const matAreaM2 = stripCount * 0.5 * (totalLinearM / stripCount || 0); // 500mm wide × avg length

  const coveragePct = grossM2 > 0 ? (netM2 / grossM2) * 100 : 0;

  return {
    grossAreaM2: Math.round(grossM2 * 100) / 100,
    excludedAreaM2: Math.round(exclM2 * 100) / 100,
    netAreaPx: netPx - setbackPxLoss,
    netHeatableM2: Math.round(netM2 * 100) / 100,
    matAreaM2: Math.round(matAreaM2 * 100) / 100,
    stripCount,
    totalLinearM: Math.round(totalLinearM * 100) / 100,
    coveragePct: Math.round(coveragePct * 10) / 10,
  };
}

export function computeTotalTakeoff(
  rooms: { name: string; vertices: number[][]; exclusions: number[][][] }[],
  pxPerMetre: number,
) {
  let totalGross = 0,
    totalExcluded = 0,
    totalNet = 0,
    totalMat = 0,
    totalLinear = 0,
    totalStrips = 0;
  const results: any[] = [];

  for (const room of rooms) {
    const r = computeRoomTakeoff(room.vertices, room.exclusions, pxPerMetre);
    results.push({ name: room.name, ...r });
    totalGross += r.grossAreaM2;
    totalExcluded += r.excludedAreaM2;
    totalNet += r.netHeatableM2;
    totalMat += r.matAreaM2;
    totalLinear += r.totalLinearM;
    totalStrips += r.stripCount;
  }

  return {
    rooms: results,
    totals: {
      gross_area_m2: Math.round(totalGross * 100) / 100,
      excluded_area_m2: Math.round(totalExcluded * 100) / 100,
      net_heatable_m2: Math.round(totalNet * 100) / 100,
      mat_area_m2: Math.round(totalMat * 100) / 100,
      total_linear_m: Math.round(totalLinear * 100) / 100,
      total_strips: totalStrips,
      coverage_pct:
        totalGross > 0 ? Math.round((totalNet / totalGross) * 1000) / 10 : 0,
    },
  };
}
