import { useRef, useState, useCallback } from "react";
import * as pdfjs from "pdfjs-dist";

import pdfWorkerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
pdfjs.GlobalWorkerOptions.workerSrc = pdfWorkerUrl;

export function usePdf() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const pdfCacheRef = useRef<HTMLCanvasElement | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pageWidth, setPageWidth] = useState(0);
  const [pageHeight, setPageHeight] = useState(0);
  const renderTaskRef = useRef<any>(null);
  // New state goes LAST to avoid HMR hook-order shifts
  const [pdfReady, setPdfReady] = useState(false);

  const loadPdf = useCallback(async (file: File) => {
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
      await renderPage(doc, 1);
      setPdfReady(true);
    } catch (e: any) {
      setError(e.message || "Failed to load PDF");
    } finally {
      setLoading(false);
    }
  }, []);

  const renderPage = async (doc: any, pageNum: number) => {
    const page = await doc.getPage(pageNum);
    const viewport = page.getViewport({ scale: 1.5 });

    if (!pdfCacheRef.current) {
      pdfCacheRef.current = document.createElement("canvas");
    }
    const cache = pdfCacheRef.current;
    cache.width = viewport.width;
    cache.height = viewport.height;
    setPageWidth(viewport.width);
    setPageHeight(viewport.height);

    if (renderTaskRef.current) {
      await renderTaskRef.current.cancel();
    }
    const ctx = cache.getContext("2d")!;
    renderTaskRef.current = page.render({ canvasContext: ctx, viewport });
    await renderTaskRef.current.promise;
  };

  return {
    canvasRef,
    pdfCacheRef,
    loading,
    error,
    loadPdf,
    pageWidth,
    pageHeight,
    pdfReady,
  };
}
