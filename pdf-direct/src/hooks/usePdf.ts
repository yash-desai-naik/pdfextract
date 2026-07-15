import { useRef, useState, useCallback } from "react";
import * as pdfjs from "pdfjs-dist";

import pdfWorkerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
pdfjs.GlobalWorkerOptions.workerSrc = pdfWorkerUrl;

export function usePdf() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const pdfCacheRef = useRef<HTMLCanvasElement | null>(null);
  const docRef = useRef<any>(null);
  const renderTaskRef = useRef<any>(null);
  const renderScaleRef = useRef(1.5); // track last rendered scale

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pageWidth, setPageWidth] = useState(0);
  const [pageHeight, setPageHeight] = useState(0);
  const [pdfReady, setPdfReady] = useState(false);
  const [renderTick, setRenderTick] = useState(0); // bump to trigger redraw

  const renderPage = useCallback(async (scale: number) => {
    const page = docRef.current;
    if (!page) return;
    renderScaleRef.current = scale;
    const viewport = page.getViewport({ scale });

    if (!pdfCacheRef.current) {
      pdfCacheRef.current = document.createElement("canvas");
    }
    const cache = pdfCacheRef.current;
    cache.width = viewport.width;
    cache.height = viewport.height;
    setPageWidth(viewport.width);
    setPageHeight(viewport.height);

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
      try {
        const buffer = await file.arrayBuffer();
        const doc = await pdfjs.getDocument({ data: buffer }).promise;
        docRef.current = await doc.getPage(1);
        await renderPage(1.5);
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
      // Clamp to reasonable bounds
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
    pageWidth,
    pageHeight,
    pdfReady,
    renderTick,
    reRender,
  };
}
