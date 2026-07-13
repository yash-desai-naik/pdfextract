import { ArrowLeft, Upload, Download, Ruler, Zap, Thermometer } from "lucide-react";
import type { TakeoffResult, RoomData } from "../types";

interface Props {
  results: TakeoffResult;
  rooms: RoomData[];
  onBack: () => void;
  onNewUpload: () => void;
  scale: Record<string, any> | null;
}

export default function ResultsPanel({
  results,
  rooms,
  onBack,
  onNewUpload,
  scale,
}: Props) {
  const exportCSV = () => {
    const headers = [
      "Room",
      "Gross Area (m²)",
      "Excluded (m²)",
      "Net Heatable (m²)",
      "Mat Area (m²)",
      "Strips",
      "Linear (m)",
      "Coverage (%)",
      "Setback (m)",
    ];
    const rows = results.rooms.map((r) => [
      r.name,
      r.gross_area_m2,
      r.excluded_area_m2,
      r.net_heatable_area_m2,
      r.mat_area_m2,
      r.strip_count,
      r.total_linear_m,
      r.coverage_pct,
      r.setback_distance_m,
    ]);
    const csv = [
      headers.join(","),
      ...rows.map((r) => r.join(",")),
      "",
      "TOTALS",
      ...Object.entries(results.totals).map(
        ([k, v]) => `${k},${v}`
      ),
    ].join("\n");

    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "warmset_takeoff.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  const totalArea = results.rooms.reduce((s, r) => s + r.gross_area_m2, 0);
  const totalNet = results.rooms.reduce((s, r) => s + r.net_heatable_area_m2, 0);
  const totalMat = results.rooms.reduce((s, r) => s + r.mat_area_m2, 0);
  const totalLinear = results.rooms.reduce((s, r) => s + r.total_linear_m, 0);

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="max-w-4xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h2 className="text-2xl font-bold text-slate-100">
              Takeoff Results
            </h2>
            <p className="text-sm text-slate-400 mt-1">
              {results.rooms.length} rooms · {totalArea.toFixed(1)} m² total
              {scale && (
                <span className="ml-3 font-mono text-xs text-slate-500">
                  Scale: 1:{scale.scale_ratio}
                </span>
              )}
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
            <button
              onClick={onNewUpload}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs bg-slate-800 text-slate-300 hover:bg-slate-700 transition-all"
            >
              <Upload className="w-3.5 h-3.5" strokeWidth={1.5} />
              <span>New Drawing</span>
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
              {totalArea.toFixed(1)}
              <span className="text-sm font-normal text-slate-500 ml-1">m²</span>
            </p>
          </div>
          <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-4">
            <div className="flex items-center gap-2 text-xs text-slate-500 mb-2">
              <Thermometer className="w-3.5 h-3.5" strokeWidth={1.5} />
              <span>Net Heatable</span>
            </div>
            <p className="text-2xl font-bold text-brand">
              {totalNet.toFixed(1)}
              <span className="text-sm font-normal text-slate-500 ml-1">m²</span>
            </p>
          </div>
          <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-4">
            <div className="flex items-center gap-2 text-xs text-slate-500 mb-2">
              <Zap className="w-3.5 h-3.5" strokeWidth={1.5} />
              <span>Mat Area</span>
            </div>
            <p className="text-2xl font-bold text-slate-100">
              {totalMat.toFixed(1)}
              <span className="text-sm font-normal text-slate-500 ml-1">m²</span>
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
                {results.rooms.map((r, i) => (
                  <tr
                    key={i}
                    className="border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors"
                  >
                    <td className="px-4 py-3 text-sm font-medium text-slate-200">
                      {r.name}
                    </td>
                    <td className="px-4 py-3 text-right text-sm text-slate-300 font-mono">
                      {r.gross_area_m2.toFixed(2)}
                    </td>
                    <td className="px-4 py-3 text-right text-sm text-danger/70 font-mono">
                      {r.excluded_area_m2.toFixed(2)}
                    </td>
                    <td className="px-4 py-3 text-right text-sm text-slate-300 font-mono">
                      {r.net_heatable_area_m2.toFixed(2)}
                    </td>
                    <td className="px-4 py-3 text-right text-sm text-brand font-mono font-medium">
                      {r.mat_area_m2.toFixed(2)}
                    </td>
                    <td className="px-4 py-3 text-right text-sm text-slate-300 font-mono">
                      {r.strip_count}
                    </td>
                    <td className="px-4 py-3 text-right text-sm text-slate-300 font-mono">
                      {r.total_linear_m.toFixed(1)}
                    </td>
                    <td className="px-4 py-3 text-right text-sm text-slate-300 font-mono">
                      {r.coverage_pct}%
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
                    {totalArea.toFixed(2)}
                  </td>
                  <td className="px-4 py-3 text-right text-sm font-semibold text-danger/70 font-mono">
                    {results.rooms.reduce((s, r) => s + r.excluded_area_m2, 0).toFixed(2)}
                  </td>
                  <td className="px-4 py-3 text-right text-sm font-semibold text-slate-200 font-mono">
                    {totalNet.toFixed(2)}
                  </td>
                  <td className="px-4 py-3 text-right text-sm font-semibold text-brand font-mono">
                    {totalMat.toFixed(2)}
                  </td>
                  <td className="px-4 py-3 text-right text-sm font-semibold text-slate-200 font-mono">
                    {results.rooms.reduce((s, r) => s + r.strip_count, 0)}
                  </td>
                  <td className="px-4 py-3 text-right text-sm font-semibold text-slate-200 font-mono">
                    {totalLinear.toFixed(1)}
                  </td>
                  <td className="px-4 py-3 text-right text-sm font-semibold text-slate-200 font-mono">
                    {results.totals.coverage_pct || "-"}
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
        </div>

        {/* Additional detail */}
        <div className="grid grid-cols-2 gap-4 mt-4">
          {Object.entries(results.totals).map(([key, val]) => (
            <div
              key={key}
              className="bg-slate-800/30 border border-slate-700/50 rounded-lg px-4 py-3"
            >
              <span className="text-xs text-slate-500">{key}</span>
              <p className="text-lg font-semibold text-slate-100 mt-0.5 font-mono">
                {typeof val === "number" ? val.toFixed(2) : String(val)}
              </p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
