import { Download, Ruler, Thermometer, Zap, ArrowLeft } from "lucide-react";
import type { MarkedArea } from "../types";
import { computeTotalTakeoff } from "../geometry";

interface Props {
  areas: MarkedArea[];
  pxPerMetre: number;
  onBack: () => void;
}

export default function ResultsPanel({ areas, pxPerMetre, onBack }: Props) {
  const rooms = areas.filter((a) => a.type === "room");
  const exclusionsByRoom: Record<string, number[][][]> = {};

  // Group exclusions by room
  for (const room of rooms) {
    exclusionsByRoom[room.id] = [];
    for (const exc of areas) {
      if (exc.type === "exclusion") {
        // Check if exclusion centroid is inside this room
        const cx =
          exc.vertices.reduce((s, p) => s + p[0], 0) / exc.vertices.length;
        const cy =
          exc.vertices.reduce((s, p) => s + p[1], 0) / exc.vertices.length;
        if (pointInRoom(cx, cy, room.vertices)) {
          exclusionsByRoom[room.id].push(exc.vertices);
        }
      }
    }
  }

  const takeoff = computeTotalTakeoff(
    rooms.map((r) => ({
      name: r.name,
      vertices: r.vertices,
      exclusions: exclusionsByRoom[r.id] || [],
    })),
    pxPerMetre,
  );

  const exportCSV = () => {
    const headers = [
      "Room",
      "Gross (m²)",
      "Excluded (m²)",
      "Net Heatable (m²)",
      "Mat Area (m²)",
      "Strips",
      "Linear (m)",
      "Coverage (%)",
    ];
    const rows = takeoff.rooms.map((r: any) => [
      r.name,
      r.grossAreaM2,
      r.excludedAreaM2,
      r.netHeatableM2,
      r.matAreaM2,
      r.stripCount,
      r.totalLinearM,
      r.coveragePct,
    ]);
    const csv = [
      headers.join(","),
      ...rows.map((r: any) => r.join(",")),
      "",
      "TOTALS",
      ...Object.entries(takeoff.totals).map(([k, v]) => `${k},${v}`),
    ].join("\n");

    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "warmset_takeoff.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  const totalGross = takeoff.rooms.reduce(
    (s: number, r: any) => s + r.grossAreaM2,
    0,
  );
  const totalNet = takeoff.rooms.reduce(
    (s: number, r: any) => s + r.netHeatableM2,
    0,
  );
  const totalMat = takeoff.rooms.reduce(
    (s: number, r: any) => s + r.matAreaM2,
    0,
  );
  const totalLinear = takeoff.rooms.reduce(
    (s: number, r: any) => s + r.totalLinearM,
    0,
  );

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="max-w-4xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h2 className="text-2xl font-bold text-slate-100">
              Warmset Takeoff
            </h2>
            <p className="text-sm text-slate-400 mt-1">
              {takeoff.rooms.length} rooms · {totalGross.toFixed(1)} m² total
              <span className="ml-3 font-mono text-xs text-slate-500">
                {pxPerMetre.toFixed(1)} px/m
              </span>
            </p>
          </div>
          <div className="flex gap-2">
            <button
              onClick={onBack}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-all"
            >
              <ArrowLeft className="w-3.5 h-3.5" strokeWidth={1.5} />
              <span>Back to Editor</span>
            </button>
            <button
              onClick={exportCSV}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs bg-brand/20 text-brand hover:bg-brand/30 transition-all"
            >
              <Download className="w-3.5 h-3.5" strokeWidth={1.5} />
              <span>Export CSV</span>
            </button>
          </div>
        </div>

        {/* Summary cards */}
        <div className="grid grid-cols-3 gap-4 mb-6">
          <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-4">
            <div className="flex items-center gap-2 text-xs text-slate-500 mb-2">
              <Ruler className="w-3.5 h-3.5" strokeWidth={1.5} />
              <span>Gross Area</span>
            </div>
            <p className="text-2xl font-bold text-slate-100">
              {totalGross.toFixed(1)}
              <span className="text-sm font-normal text-slate-500 ml-1">
                m²
              </span>
            </p>
          </div>
          <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-4">
            <div className="flex items-center gap-2 text-xs text-slate-500 mb-2">
              <Thermometer className="w-3.5 h-3.5" strokeWidth={1.5} />
              <span>Net Heatable</span>
            </div>
            <p className="text-2xl font-bold text-brand">
              {totalNet.toFixed(1)}
              <span className="text-sm font-normal text-slate-500 ml-1">
                m²
              </span>
            </p>
          </div>
          <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-4">
            <div className="flex items-center gap-2 text-xs text-slate-500 mb-2">
              <Zap className="w-3.5 h-3.5" strokeWidth={1.5} />
              <span>Mat Area</span>
            </div>
            <p className="text-2xl font-bold text-slate-100">
              {totalMat.toFixed(1)}
              <span className="text-sm font-normal text-slate-500 ml-1">
                m²
              </span>
            </p>
          </div>
        </div>

        {/* Room table */}
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-700/50">
                  <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">
                    Room
                  </th>
                  <th className="text-right px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">
                    Gross (m²)
                  </th>
                  <th className="text-right px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">
                    Excluded (m²)
                  </th>
                  <th className="text-right px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">
                    Net (m²)
                  </th>
                  <th className="text-right px-4 py-3 text-xs font-semibold text-brand uppercase tracking-wider">
                    Mat (m²)
                  </th>
                  <th className="text-right px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">
                    Strips
                  </th>
                  <th className="text-right px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">
                    Linear (m)
                  </th>
                  <th className="text-right px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">
                    Coverage
                  </th>
                </tr>
              </thead>
              <tbody>
                {takeoff.rooms.map((r: any, i: number) => (
                  <tr
                    key={i}
                    className="border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors"
                  >
                    <td className="px-4 py-3 text-sm font-medium text-slate-200">
                      {r.name}
                    </td>
                    <td className="px-4 py-3 text-right text-sm text-slate-300 font-mono">
                      {r.grossAreaM2.toFixed(2)}
                    </td>
                    <td className="px-4 py-3 text-right text-sm text-danger/70 font-mono">
                      {r.excludedAreaM2.toFixed(2)}
                    </td>
                    <td className="px-4 py-3 text-right text-sm text-slate-300 font-mono">
                      {r.netHeatableM2.toFixed(2)}
                    </td>
                    <td className="px-4 py-3 text-right text-sm text-brand font-mono font-medium">
                      {r.matAreaM2.toFixed(2)}
                    </td>
                    <td className="px-4 py-3 text-right text-sm text-slate-300 font-mono">
                      {r.stripCount}
                    </td>
                    <td className="px-4 py-3 text-right text-sm text-slate-300 font-mono">
                      {r.totalLinearM.toFixed(1)}
                    </td>
                    <td className="px-4 py-3 text-right text-sm text-slate-300 font-mono">
                      {r.coveragePct}%
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="bg-slate-800/50">
                  <td className="px-4 py-3 text-sm font-semibold text-slate-200">
                    Total
                  </td>
                  <td className="px-4 py-3 text-right text-sm font-semibold text-slate-200 font-mono">
                    {totalGross.toFixed(2)}
                  </td>
                  <td className="px-4 py-3 text-right text-sm font-semibold text-danger/70 font-mono">
                    {takeoff.rooms
                      .reduce((s: number, r: any) => s + r.excludedAreaM2, 0)
                      .toFixed(2)}
                  </td>
                  <td className="px-4 py-3 text-right text-sm font-semibold text-slate-200 font-mono">
                    {totalNet.toFixed(2)}
                  </td>
                  <td className="px-4 py-3 text-right text-sm font-semibold text-brand font-mono">
                    {totalMat.toFixed(2)}
                  </td>
                  <td className="px-4 py-3 text-right text-sm font-semibold text-slate-200 font-mono">
                    {takeoff.rooms.reduce(
                      (s: number, r: any) => s + r.stripCount,
                      0,
                    )}
                  </td>
                  <td className="px-4 py-3 text-right text-sm font-semibold text-slate-200 font-mono">
                    {totalLinear.toFixed(1)}
                  </td>
                  <td className="px-4 py-3 text-right text-sm font-semibold text-slate-200 font-mono">
                    {(takeoff.totals as any).coverage_pct || "-"}
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
        </div>

        {/* Room breakdowns */}
        <div className="mt-4 space-y-3">
          {takeoff.rooms.map((r: any, i: number) => (
            <div
              key={i}
              className="bg-slate-800/30 border border-slate-700/50 rounded-lg px-4 py-3"
            >
              <h4 className="text-sm font-semibold text-slate-200 mb-1">
                {r.name}
              </h4>
              <pre className="text-xs text-slate-400 font-mono leading-relaxed">
                {`Gross polygon:          ${r.grossAreaM2.toFixed(2)} m²
  Less exclusions:       ${r.excludedAreaM2.toFixed(2)} m²
  Wall setback (100mm):  ${(r.grossAreaM2 - r.netHeatableM2 - r.excludedAreaM2).toFixed(2)} m²
  ─────────────────────────────────
  Net heatable area:     ${r.netHeatableM2.toFixed(2)} m²
  ${r.stripCount} strips × 500mm wide
  Total linear:          ${r.totalLinearM.toFixed(1)} m
  Mat area:              ${r.matAreaM2.toFixed(2)} m²
  Coverage:              ${r.coveragePct}%`}
              </pre>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function pointInRoom(px: number, py: number, polygon: number[][]): boolean {
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
