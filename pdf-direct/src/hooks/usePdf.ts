import { useRef, useState, useCallback } from "react";
import * as pdfjs from "pdfjs-dist";

import pdfWorkerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
pdfjs.GlobalWorkerOptions.workerSrc = pdfWorkerUrl;

export function usePdf() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const pdfCacheRef = useRef<HTMLCanvasElement | null>(null);
  const docRef = useRef<any>(null);
  const renderTaskRef = useRef<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pdfReady, setPdfReady] = useState(false);
  const [renderTick, setRenderTick] = useState(0);
  // Fixed base dimensions — set once on first render, never change
  const [baseW, setBaseW] = useState(0);
  const [baseH, setBaseH] = useState(0);

  const renderPage = useCallback(async (scale: number) => {
    const page = docRef.current;
    if (!page) return;
    const viewport = page.getViewport({ scale });

    if (!pdfCacheRef.current) {
      pdfCacheRef.current = document.createElement("canvas");
    }
    const cache = pdfCacheRef.current;
    cache.width = viewport.width;
    cache.height = viewport.height;

    // Store base dimensions on first render only
    setBaseW((prev) => (prev === 0 ? viewport.width : prev));
    setBaseH((prev) => (prev === 0 ? viewport.height : prev));

    if (renderTaskRef.current) {
      try {
        await renderTaskRef.current.cancel();
      } catch {}
    }
    const ctx = cache.getContext("2d")!;
    renderTaskRef.current = page.render({ canvasContext: ctx, viewport });
    await renderTaskRef.current.promise;
    setRenderTick((n) => n + 1);
  }, []);

  const loadPdf = useCallback(
    async (file: File) => {
      if (!file.name.toLowerCase().endsWith(".pdf")) {
        setError("Only PDF files accepted");
        return;
      }
      setLoading(true);
      setError(null);
      setPdfReady(false);
      setBaseW(0);
      setBaseH(0);
      try {
        const buffer = await file.arrayBuffer();
        const doc = await pdfjs.getDocument({ data: buffer }).promise;
        docRef.current = await doc.getPage(1);
        await renderPage(2);
        setPdfReady(true);
      } catch (e: any) {
        setError(e.message || "Failed to load PDF");
      } finally {
        setLoading(false);
      }
    },
    [renderPage],
  );

  const reRender = useCallback(
    (targetScale: number) => {
      const s = Math.min(Math.max(targetScale, 0.3), 20);
      renderPage(s);
    },
    [renderPage],
  );

  return {
    canvasRef,
    pdfCacheRef,
    loading,
    error,
    loadPdf,
    pageWidth: baseW,
    pageHeight: baseH,
    pdfReady,
    renderTick,
    reRender,
  };
}
