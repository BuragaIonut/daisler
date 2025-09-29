"use client";

import { useEffect, useRef, useState } from "react";
import NextImage from "next/image";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000/api";

export default function Home() {
  const [file, setFile] = useState<File | null>(null);
  const [imageSrc, setImageSrc] = useState<string | null>(null);
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [naturalSize, setNaturalSize] = useState<{ width: number; height: number } | null>(null);
  const [zoom, setZoom] = useState<number>(1);
  const [originX, setOriginX] = useState<number>(0);
  const [originY, setOriginY] = useState<number>(0);
  const [selecting, setSelecting] = useState(false);
  const [startPoint, setStartPoint] = useState<{ x: number; y: number } | null>(
    null
  );
  const [selection, setSelection] = useState<{
    x: number;
    y: number;
    width: number;
    height: number;
  } | null>(null);
  const [useCase, setUseCase] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [toSendPreviewUrl, setToSendPreviewUrl] = useState<string | null>(null);
  const [toSendType, setToSendType] = useState<string>("image/png");
  const [processedUrl, setProcessedUrl] = useState<string | null>(null);
  const [processedType, setProcessedType] = useState<string | null>(null);
  const [processedPdfUrl, setProcessedPdfUrl] = useState<string | null>(null);
  const [resizeWidth, setResizeWidth] = useState<string>("");
  const [resizeHeight, setResizeHeight] = useState<string>("");
  const [resizeDpi, setResizeDpi] = useState<string>("300");
  const [resizeUnit, setResizeUnit] = useState<string>("mm");
  const [healthStatus, setHealthStatus] = useState<string | null>(null);
  const [checkingHealth, setCheckingHealth] = useState(false);
  
  // Cropping mode state
  const [cropMode, setCropMode] = useState<"free" | "fixed">("free");
  const [fixedWidth, setFixedWidth] = useState<string>("100");
  const [fixedHeight, setFixedHeight] = useState<string>("100");
  const [dragging, setDragging] = useState(false);

  function readFileToDataURL(f: File): Promise<string> {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as string);
      reader.onerror = reject;
      reader.readAsDataURL(f);
    });
  }

  async function createImage(src: string): Promise<HTMLImageElement> {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.addEventListener("load", () => resolve(img));
      img.addEventListener("error", (e: Event) => reject(e));
      img.crossOrigin = "anonymous";
      img.src = src;
    });
  }

  async function convertPdfToImageViaBackend(pdfFile: File): Promise<string> {
    try {
      const formData = new FormData();
      formData.append('file', pdfFile);
      
      const response = await fetch(`${BACKEND_URL}/pdf_to_image`, {
        method: 'POST',
        body: formData,
      });
      
      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(errorText || `PDF conversion failed (${response.status})`);
      }
      
      const blob = await response.blob();
      return URL.createObjectURL(blob);
    } catch (error) {
      console.error('Error converting PDF to image via backend:', error);
      throw error;
    }
  }

  // End selection even if mouse is released outside the image container
  useEffect(() => {
    const onWinMouseUp = () => {
      setSelecting(false);
      setDragging(false);
    };
    window.addEventListener("mouseup", onWinMouseUp);
    return () => window.removeEventListener("mouseup", onWinMouseUp);
  }, []);

  // Prevent page scroll and zoom the image when the wheel is used over the image container.
  // Zoom towards mouse pointer by setting transform-origin to the pointer location.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const pointerX = e.clientX - rect.left;
      const pointerY = e.clientY - rect.top;
      setOriginX(pointerX);
      setOriginY(pointerY);
      const zoomFactor = e.deltaY < 0 ? 1.1 : 0.9; // smooth multiplicative zoom
      setZoom((prevZoom) => Math.min(5, Math.max(0.2, Number((prevZoom * zoomFactor).toFixed(3)))));
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel as EventListener);
  }, [imageSrc, naturalSize]);

  // Reset pan when a new image is loaded
  useEffect(() => {
    const el = containerRef.current;
    if (el) {
      const rect = el.getBoundingClientRect();
      setOriginX(rect.width / 2);
      setOriginY(rect.height / 2);
    } else {
      setOriginX(0);
      setOriginY(0);
    }
    setZoom(1);
  }, [imageSrc]);

  // Update fixed selection rectangle when dimensions change
  useEffect(() => {
    if (cropMode === "fixed" && selection) {
      const fixW = Math.max(5, Math.min(parseInt(fixedWidth) || 100, naturalSize?.width || 1000));
      const fixH = Math.max(5, Math.min(parseInt(fixedHeight) || 100, naturalSize?.height || 1000));
      const contEl = containerRef.current;
      if (contEl) {
        const rect = contEl.getBoundingClientRect();
        // Keep the selection centered on its current position but update size
        const centerX = selection.x + selection.width / 2;
        const centerY = selection.y + selection.height / 2;
        setSelection({
          x: Math.max(0, Math.min(centerX - fixW / 2, rect.width - fixW)),
          y: Math.max(0, Math.min(centerY - fixH / 2, rect.height - fixH)),
          width: fixW,
          height: fixH,
        });
      }
    }
  }, [fixedWidth, fixedHeight, cropMode, naturalSize]);

  function computeCropPixelsFromSelection(sel: { x: number; y: number; width: number; height: number } | null) {
    if (!isValidSelection(sel)) return null;
    const contEl = containerRef.current;
    if (!contEl || !naturalSize || !imageSrc) return null;
    const cw = contEl.clientWidth;
    const ch = contEl.clientHeight;
    const iw = naturalSize.width;
    const ih = naturalSize.height;
    const baseScale = Math.min(cw / iw, ch / ih) || 1;
    const bw = iw * baseScale; // base contained width
    const bh = ih * baseScale; // base contained height
    const ex = (cw - bw) / 2; // base offset inside container
    const ey = (ch - bh) / 2;
    const elementOffsetX = originX * (1 - zoom);
    const elementOffsetY = originY * (1 - zoom);
    const imgLeft = elementOffsetX + ex * zoom;
    const imgTop = elementOffsetY + ey * zoom;
    const dispW = bw * zoom;
    const dispH = bh * zoom;
    const sx = sel.x;
    const sy = sel.y;
    const sw = sel.width;
    const sh = sel.height;
    // Intersection with image bounds
    const ix = Math.max(0, Math.min(sx, imgLeft + dispW) - imgLeft);
    const iy = Math.max(0, Math.min(sy, imgTop + dispH) - imgTop);
    const ix2 = Math.max(0, Math.min(sx + sw, imgLeft + dispW) - imgLeft);
    const iy2 = Math.max(0, Math.min(sy + sh, imgTop + dispH) - imgTop);
    const selWOnImg = Math.max(0, ix2 - ix);
    const selHOnImg = Math.max(0, iy2 - iy);
    if (selWOnImg < 1 || selHOnImg < 1) return null;
    const normX = ix / dispW;
    const normY = iy / dispH;
    const normW = selWOnImg / dispW;
    const normH = selHOnImg / dispH;
    const px = Math.max(0, Math.floor(normX * iw));
    const py = Math.max(0, Math.floor(normY * ih));
    const pw = Math.max(1, Math.floor(normW * iw));
    const ph = Math.max(1, Math.floor(normH * ih));
    return { x: px, y: py, width: pw, height: ph };
  }

  function maybeClearTinySelection() {
    if (selection && (selection.width < 8 || selection.height < 8)) {
      setSelection(null);
    }
  }

  function isValidSelection(sel: { x: number; y: number; width: number; height: number } | null): sel is { x: number; y: number; width: number; height: number } {
    return !!sel && sel.width >= 8 && sel.height >= 8;
  }

  // Calculate effective DPI and quality warnings
  function calculateDpiQuality(
    imageWidth: number,
    imageHeight: number,
    printWidthMm: number,
    printHeightMm: number,
    targetDpi: number
  ) {
    // Convert mm to inches
    const printWidthInch = printWidthMm / 25.4;
    const printHeightInch = printHeightMm / 25.4;
    
    // Calculate effective DPI
    const effectiveDpiX = imageWidth / printWidthInch;
    const effectiveDpiY = imageHeight / printHeightInch;
    const effectiveDpi = Math.min(effectiveDpiX, effectiveDpiY);
    
    // Quality assessment
    const isLowQuality = effectiveDpi < targetDpi * 0.95; // Under 95%
    const isVeryLowQuality = effectiveDpi < targetDpi * 0.8; // Under 80%
    
    // Calculate recommended resolution
    const recommendedWidth = Math.ceil(printWidthInch * targetDpi);
    const recommendedHeight = Math.ceil(printHeightInch * targetDpi);
    
    return {
      effectiveDpi: Math.round(effectiveDpi),
      isLowQuality,
      isVeryLowQuality,
      recommendedWidth,
      recommendedHeight
    };
  }

  async function getCroppedBlob(
    imageSrc: string,
    cropPixels: { x: number; y: number; width: number; height: number }
  ): Promise<Blob> {
    const image = await createImage(imageSrc);
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("Canvas not supported");

    const pixelRatio = window.devicePixelRatio || 1;
    canvas.width = Math.max(1, Math.floor(cropPixels.width * pixelRatio));
    canvas.height = Math.max(1, Math.floor(cropPixels.height * pixelRatio));
    ctx.scale(pixelRatio, pixelRatio);
    ctx.imageSmoothingQuality = "high";

    ctx.drawImage(
      image,
      cropPixels.x,
      cropPixels.y,
      cropPixels.width,
      cropPixels.height,
      0,
      0,
      cropPixels.width,
      cropPixels.height
    );

    return new Promise((resolve) => {
      canvas.toBlob((blob) => resolve(blob as Blob), "image/png", 1);
    });
  }

  function revokeUrl(url: string | null) {
    try {
      if (url) URL.revokeObjectURL(url);
    } catch {}
  }

  // Cleanup any created PDF object URL and image object URLs
  useEffect(() => {
    return () => {
      revokeUrl(pdfUrl);
      // Also revoke imageSrc if it's an object URL (from PDF conversion)
      if (imageSrc && imageSrc.startsWith('blob:')) {
        revokeUrl(imageSrc);
      }
    };
  }, [pdfUrl, imageSrc]);

  async function refreshToSendPreview() {
    if (!imageSrc) {
      revokeUrl(toSendPreviewUrl);
      setToSendPreviewUrl(null);
      // Clear old processed output when selection/context resets
      revokeUrl(processedUrl);
      setProcessedUrl(null);
      setProcessedType(null);
      revokeUrl(processedPdfUrl);
      setProcessedPdfUrl(null);
      return;
    }
    try {
      if (isValidSelection(selection)) {
        const cropPixels = computeCropPixelsFromSelection(selection);
        if (!cropPixels) {
          revokeUrl(toSendPreviewUrl);
          setToSendPreviewUrl(null);
          revokeUrl(processedUrl);
          setProcessedUrl(null);
          setProcessedType(null);
          revokeUrl(processedPdfUrl);
          setProcessedPdfUrl(null);
          return;
        }
        // New valid crop → clear previous processed result
        revokeUrl(processedUrl);
        setProcessedUrl(null);
        setProcessedType(null);
        revokeUrl(processedPdfUrl);
        setProcessedPdfUrl(null);
        const blob = await getCroppedBlob(imageSrc, cropPixels);
        const url = URL.createObjectURL(blob);
        revokeUrl(toSendPreviewUrl);
        setToSendPreviewUrl(url);
        setToSendType(blob.type || "image/png");
      } else {
        // No valid crop → do not show preview
        revokeUrl(toSendPreviewUrl);
        setToSendPreviewUrl(null);
        // Also clear processed if selection was removed/changed
        revokeUrl(processedUrl);
        setProcessedUrl(null);
        setProcessedType(null);
        revokeUrl(processedPdfUrl);
        setProcessedPdfUrl(null);
      }
    } catch {}
  }

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setResult(null);
    if ((!file && !imageSrc) || !useCase) {
      setError("Please select an image and enter a use case.");
      return;
    }
    const form = new FormData();

    let fileToSend: File | null = file;
    try {
      if (imageSrc && selection) {
        const cropPixels = computeCropPixelsFromSelection(selection);
        if (cropPixels) {
          const blob = await getCroppedBlob(imageSrc, cropPixels);
          fileToSend = new File([blob], "crop.png", { type: "image/png" });
        }
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Crop failed";
      setError(message);
      return;
    }

    if (!fileToSend && imageSrc) {
      // Fallback: send original dataURL as blob
      const res = await fetch(imageSrc);
      const blob = await res.blob();
      fileToSend = new File([blob], "image.png", { type: blob.type || "image/png" });
    }

    if (!fileToSend) {
      setError("No file to send");
      return;
    }

    // Ensure preview matches exactly what is being sent (only for images)
    try {
      if (fileToSend.type && fileToSend.type.startsWith("image/")) {
        const url = URL.createObjectURL(fileToSend);
        revokeUrl(toSendPreviewUrl);
        setToSendPreviewUrl(url);
        setToSendType(fileToSend.type || "image/png");
      } else {
        // Non-image: clear preview
        revokeUrl(toSendPreviewUrl);
        setToSendPreviewUrl(null);
      }
    } catch {}

    form.append("file", fileToSend);
    form.append("use_case", useCase);
    setLoading(true);
    try {
      const isPdf = file && file.type === 'application/pdf';
      const endpoint = isPdf ? `${BACKEND_URL}/analyze_pdf` : `${BACKEND_URL}/analyze`;
      const res = await fetch(endpoint, {
        method: "POST",
        body: form,
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t || `Request failed (${res.status})`);
      }
      const data = await res.json();
      setResult(data.result ?? "No result");
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Unexpected error";
      setError(message);
    } finally {
      setLoading(false);
    }
  };

  const onProcess = async () => {
    setError(null);
    setProcessedUrl(null);
    setProcessedType(null);
    revokeUrl(processedPdfUrl);
    setProcessedPdfUrl(null);
    if (!imageSrc && !file) {
      setError("Please select an image first.");
      return;
    }

    // Build the exact same file that would be sent (respecting crop)
    let fileToSend: File | null = file;
    try {
      if (imageSrc && selection) {
        const cropPixels = computeCropPixelsFromSelection(selection);
        if (cropPixels) {
          const blob = await getCroppedBlob(imageSrc, cropPixels);
          fileToSend = new File([blob], "crop.png", { type: "image/png" });
        }
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Crop failed";
      setError(message);
      return;
    }

    if (!fileToSend && imageSrc) {
      const res = await fetch(imageSrc);
      const blob = await res.blob();
      fileToSend = new File([blob], "image.png", { type: blob.type || "image/png" });
    }
    if (!fileToSend) {
      setError("No file to process");
      return;
    }

    const form = new FormData();
    form.append("file", fileToSend);
    form.append("bleed_px", String(30));

    try {
      const res = await fetch(`${BACKEND_URL}/process`, { method: "POST", body: form });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t || `Process failed (${res.status})`);
      }
      const blob = await res.blob();
      if (processedUrl) URL.revokeObjectURL(processedUrl);
      setProcessedUrl(URL.createObjectURL(blob));
      setProcessedType(blob.type || null);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Processing error";
      setError(message);
    }
  };

  const checkHealth = async () => {
    setCheckingHealth(true);
    setHealthStatus(null);
    try {
      const res = await fetch(`${BACKEND_URL}/health`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setHealthStatus(`Status: ${data.status}`);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Unknown error";
      setHealthStatus(`Error: ${message}`);
    } finally {
      setCheckingHealth(false);
    }
  };

  return (
    <div className="mx-auto max-w-[1800px] px-8 py-8">
      <header className="mb-8">
        <h1 className="text-3xl font-bold heading">Daisler Print Processor</h1>
      </header>
      <section className="grid grid-cols-1 lg:grid-cols-2 gap-8 mb-8">
        <div className="card p-6">
        <h2 className="text-xl font-semibold mb-2">Analizează/Procesează fișierul</h2>
        <form onSubmit={onSubmit} className="space-y-5">
          <div>
            <label className="block text-sm font-medium mb-2">Fișier (imagine: jpeg/jpg/png sau PDF)</label>
            <div className="glass rounded-lg p-3">
              <input
                type="file"
                accept="image/jpeg,image/jpg,image/png,application/pdf"
                onChange={async (e) => {
                  const f = e.target.files?.[0] ?? null;
                  setFile(f);
                  // Any new file selection clears previous processed outputs
                  revokeUrl(processedUrl);
                  setProcessedUrl(null);
                  setProcessedType(null);
                  revokeUrl(processedPdfUrl);
                  setProcessedPdfUrl(null);
                  if (f) {
                    if (f.type === 'application/pdf') {
                      // PDF flow - convert to image via backend
                      revokeUrl(pdfUrl);
                      setPdfUrl(null);
                      // Clean up previous imageSrc if it's an object URL
                      if (imageSrc && imageSrc.startsWith('blob:')) {
                        revokeUrl(imageSrc);
                      }
                      try {
                        const imageObjectUrl = await convertPdfToImageViaBackend(f);
                        setImageSrc(imageObjectUrl);
                        const img = await createImage(imageObjectUrl);
                        setNaturalSize({ width: img.naturalWidth, height: img.naturalHeight });
                      } catch (error) {
                        console.error('Failed to convert PDF to image:', error);
                        setImageSrc(null);
                        setNaturalSize(null);
                      }
                      setSelection(null);
                      setStartPoint(null);
                      setZoom(1);
                      revokeUrl(toSendPreviewUrl);
                      setToSendPreviewUrl(null);
                    } else {
                      // Image flow
                      revokeUrl(pdfUrl);
                      setPdfUrl(null);
                      // Clean up previous imageSrc if it's an object URL
                      if (imageSrc && imageSrc.startsWith('blob:')) {
                        revokeUrl(imageSrc);
                      }
                      const dataUrl = await readFileToDataURL(f);
                      setImageSrc(dataUrl);
                      try {
                        const img = await createImage(dataUrl);
                        setNaturalSize({ width: img.naturalWidth, height: img.naturalHeight });
                      } catch {
                        setNaturalSize(null);
                      }
                      setSelection(null);
                      setStartPoint(null);
                      setZoom(1);
                      revokeUrl(toSendPreviewUrl);
                      setToSendPreviewUrl(null);
                    }
                  } else {
                    // Clean up previous imageSrc if it's an object URL
                    if (imageSrc && imageSrc.startsWith('blob:')) {
                      revokeUrl(imageSrc);
                    }
                    setImageSrc(null);
                    setSelection(null);
                    revokeUrl(pdfUrl);
                    setPdfUrl(null);
                    setNaturalSize(null);
                  }
                }}
                className="block w-full text-sm file:mr-4 file:rounded-md file:border-0 file:bg-[var(--accent)] file:text-white file:px-3 file:py-1.5"
              />
            </div>
          </div>
          {imageSrc && (
            <div
              className="relative rounded-lg overflow-hidden glass w-full"
              style={{ aspectRatio: naturalSize ? `${naturalSize.width} / ${naturalSize.height}` : "4 / 3" }}
              ref={containerRef}
               onMouseDown={(e: React.MouseEvent<HTMLDivElement>) => {
                const rect = (e.currentTarget as HTMLDivElement).getBoundingClientRect();
                const x = e.clientX - rect.left;
                const y = e.clientY - rect.top;
                
                if (cropMode === "free") {
                  setSelecting(true);
                  setStartPoint({ x, y });
                  setSelection({ x, y, width: 0, height: 0 });
                } else if (cropMode === "fixed") {
                  const fixW = Math.max(5, Math.min(parseInt(fixedWidth) || 100, naturalSize?.width || 1000));
                  const fixH = Math.max(5, Math.min(parseInt(fixedHeight) || 100, naturalSize?.height || 1000));
                  setDragging(true);
                  // Center the fixed-size rectangle on mouse position
                  setSelection({
                    x: Math.max(0, Math.min(x - fixW / 2, rect.width - fixW)),
                    y: Math.max(0, Math.min(y - fixH / 2, rect.height - fixH)),
                    width: fixW,
                    height: fixH,
                  });
                }
              }}
               onMouseMove={(e: React.MouseEvent<HTMLDivElement>) => {
                const rect = (e.currentTarget as HTMLDivElement).getBoundingClientRect();
                let x = e.clientX - rect.left;
                let y = e.clientY - rect.top;
                x = Math.max(0, Math.min(x, rect.width));
                y = Math.max(0, Math.min(y, rect.height));
                
                if (cropMode === "free" && selecting && startPoint) {
                  const sx = Math.min(startPoint.x, x);
                  const sy = Math.min(startPoint.y, y);
                  const w = Math.abs(x - startPoint.x);
                  const h = Math.abs(y - startPoint.y);
                  setSelection({ x: sx, y: sy, width: w, height: h });
                } else if (cropMode === "fixed" && dragging && selection) {
                  const fixW = Math.max(5, Math.min(parseInt(fixedWidth) || 100, naturalSize?.width || 1000));
                  const fixH = Math.max(5, Math.min(parseInt(fixedHeight) || 100, naturalSize?.height || 1000));
                  // Move the fixed-size rectangle to follow mouse
                  setSelection({
                    x: Math.max(0, Math.min(x - fixW / 2, rect.width - fixW)),
                    y: Math.max(0, Math.min(y - fixH / 2, rect.height - fixH)),
                    width: fixW,
                    height: fixH,
                  });
                }
              }}
              onMouseUp={() => {
                setSelecting(false);
                setDragging(false);
                if (cropMode === "free") {
                  maybeClearTinySelection();
                }
                refreshToSendPreview();
              }}
              onMouseLeave={() => {
                setSelecting(false);
                setDragging(false);
                if (cropMode === "free") {
                  maybeClearTinySelection();
                }
              }}
            >
              <NextImage
                src={imageSrc}
                alt="preview"
                fill
                unoptimized
                priority
                className="object-contain select-none"
                sizes="(max-width: 1024px) 100vw, 50vw"
                draggable={false}
                style={{ transform: `scale(${zoom})`, transformOrigin: `${originX}px ${originY}px` }}
              />
              
              {/* Zoom percentage display */}
              <div className="absolute top-2 right-2 bg-black/70 text-white text-xs px-2 py-1 rounded backdrop-blur-sm">
                {Math.round(zoom * 100)}%
              </div>
              {selection && (cropMode === "fixed" || (selection.width > 2 && selection.height > 2)) && (
                <div
                  className={`absolute border-2 ${
                    cropMode === "fixed" 
                      ? "border-orange-400 bg-[rgba(251,146,60,0.15)]" 
                      : "border-[var(--accent)] bg-[rgba(99,102,241,0.15)]"
                  }`}
                  style={{
                    left: selection.x,
                    top: selection.y,
                    width: selection.width,
                    height: selection.height,
                  }}
                >
                  {cropMode === "fixed" && (
                    <div className="absolute -top-6 left-0 bg-orange-400 text-white text-xs px-2 py-1 rounded text-center">
                      {selection.width}×{selection.height}px
                    </div>
                  )}
                  {cropMode === "free" && selection.width > 8 && selection.height > 8 && (
                    <div className="absolute -top-6 left-0 bg-[var(--accent)] text-white text-xs px-2 py-1 rounded text-center">
                      {(() => {
                        const cropPixels = computeCropPixelsFromSelection(selection);
                        return cropPixels ? `${cropPixels.width}×${cropPixels.height}px` : `${Math.round(selection.width)}×${Math.round(selection.height)}px`;
                      })()}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          
          {/* Reset buttons under image */}
          {imageSrc && (
            <div className="flex items-center gap-3 mt-3">
              <button
                type="button"
                className="btn-outline text-xs"
                onClick={() => { setZoom(1); const el = containerRef.current; if (el) { const r = el.getBoundingClientRect(); setOriginX(r.width/2); setOriginY(r.height/2);} }}
              >
                Reset zoom
              </button>
              {isValidSelection(selection) && (
                <button
                  type="button"
                  onClick={() => {
                    setSelection(null);
                    refreshToSendPreview();
                  }}
                  className="btn-outline text-xs"
                >
                  Șterge selecția
                </button>
              )}
            </div>
          )}
          
          {/* Cropping mode controls */}
          {imageSrc && (
            <div className="space-y-3 p-4 rounded-lg border border-white/10 bg-white/5">
              <h3 className="text-sm font-medium">Mod decupare</h3>
              <p className="text-xs text-gray-400">
                {cropMode === "free" 
                  ? "Desenați liber cu mouse-ul pentru a selecta zona de decupat" 
                  : "Glisați dreptunghiul de dimensiuni fixe peste imagine"
                }
              </p>
              <div className="flex gap-4">
                <label className="flex items-center gap-2">
                  <input
                    type="radio"
                    value="free"
                    checked={cropMode === "free"}
                    onChange={(e) => {
                      setCropMode("free");
                      setSelection(null); // Reset selection when switching to free mode
                      refreshToSendPreview();
                    }}
                    className="text-[var(--accent)]"
                  />
                  <span className="text-sm">Liber</span>
                </label>
                <label className="flex items-center gap-2">
                  <input
                    type="radio"
                    value="fixed"
                    checked={cropMode === "fixed"}
                    onChange={(e) => {
                      const newMode = e.target.value as "free" | "fixed";
                      setCropMode(newMode);
                      if (newMode === "fixed") {
                        // Create initial fixed-size selection in center of image
                        const fixW = Math.max(5, Math.min(parseInt(fixedWidth) || 100, naturalSize?.width || 1000));
                        const fixH = Math.max(5, Math.min(parseInt(fixedHeight) || 100, naturalSize?.height || 1000));
                        const contEl = containerRef.current;
                        if (contEl) {
                          const rect = contEl.getBoundingClientRect();
                          setSelection({
                            x: Math.max(0, (rect.width - fixW) / 2),
                            y: Math.max(0, (rect.height - fixH) / 2),
                            width: fixW,
                            height: fixH,
                          });
                        }
                      } else {
                        setSelection(null); // Reset selection for free mode
                      }
                      refreshToSendPreview();
                    }}
                    className="text-[var(--accent)]"
                  />
                  <span className="text-sm">Dimensiuni fixe</span>
                </label>
              </div>
              
              {cropMode === "fixed" && (
                <div className="space-y-4">
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-xs mb-1">Lățime (px)</label>
                      <input
                        type="number"
                        value={fixedWidth}
                        onChange={(e) => setFixedWidth(e.target.value)}
                        className="w-full rounded-lg p-2 bg-transparent border border-white/10 text-sm"
                        min="5"
                        max={naturalSize?.width || 1000}
                      />
                    </div>
                    <div>
                      <label className="block text-xs mb-1">Înălțime (px)</label>
                      <input
                        type="number"
                        value={fixedHeight}
                        onChange={(e) => setFixedHeight(e.target.value)}
                        className="w-full rounded-lg p-2 bg-transparent border border-white/10 text-sm"
                        min="5"
                        max={naturalSize?.height || 1000}
                      />
                    </div>
                  </div>
                  
                  {/* Sliders for width and height */}
                  <div className="space-y-4">
                    <div>
                      <label className="block text-xs mb-2 flex justify-between">
                        <span>Lățime</span>
                        <span className="text-gray-400">5 - {naturalSize?.width || 1000}px</span>
                      </label>
                      <div className="slider-container relative">
                        <div className="absolute top-1/2 left-0 w-full h-2 bg-white/20 rounded-lg transform -translate-y-1/2 border border-black/10" />
                        <div 
                          className="slider-fill" 
                          style={{ 
                            width: `${((parseInt(fixedWidth) || 100) - 5) / ((naturalSize?.width || 1000) - 5) * 100}%` 
                          }}
                        />
                        <input
                          type="range"
                          min="5"
                          max={naturalSize?.width || 1000}
                          value={parseInt(fixedWidth) || 100}
                          onChange={(e) => setFixedWidth(e.target.value)}
                          className="w-full appearance-none cursor-pointer slider relative z-10 bg-transparent"
                        />
                      </div>
                    </div>
                    <div>
                      <label className="block text-xs mb-2 flex justify-between">
                        <span>Înălțime</span>
                        <span className="text-gray-400">5 - {naturalSize?.height || 1000}px</span>
                      </label>
                      <div className="slider-container relative">
                        <div className="absolute top-1/2 left-0 w-full h-2 bg-white/20 rounded-lg transform -translate-y-1/2 border border-black/10" />
                        <div 
                          className="slider-fill" 
                          style={{ 
                            width: `${((parseInt(fixedHeight) || 100) - 5) / ((naturalSize?.height || 1000) - 5) * 100}%` 
                          }}
                        />
                        <input
                          type="range"
                          min="5"
                          max={naturalSize?.height || 1000}
                          value={parseInt(fixedHeight) || 100}
                          onChange={(e) => setFixedHeight(e.target.value)}
                          className="w-full appearance-none cursor-pointer slider relative z-10 bg-transparent"
                        />
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}
          
          <div>
            <label className="block text-sm font-medium mb-2">Descrieți scopul utilizării</label>
            <input
              type="text"
              placeholder="ex.: carte de vizită, poster, tricou, autocolant"
              value={useCase}
              onChange={(e) => setUseCase(e.target.value)}
              className="w-full rounded-lg p-3 bg-transparent border border-white/10 focus:outline-none focus:ring-2 focus:ring-[var(--accent)]"
            />
          </div>
          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={loading}
              className="btn-primary disabled:opacity-60 min-w-36"
            >
              {loading ? "Se analizează..." : "Analizează"}
            </button>
            <button
              type="button"
              onClick={onProcess}
              className="btn-secondary disabled:opacity-60 min-w-36"
              disabled={false}
            >
              Procesează
            </button>
            <button
              type="button"
              className="btn-secondary disabled:opacity-60 min-w-36"
              disabled={!imageSrc}
              onClick={async () => {
                if (!imageSrc) return;
                setError(null);
                try {
                  let toSend: File | null = null;
                  if (isValidSelection(selection)) {
                    const cropPixels = computeCropPixelsFromSelection(selection);
                    if (!cropPixels) throw new Error("Selecție invalidă pentru decupare");
                    const blob = await getCroppedBlob(imageSrc, cropPixels);
                    toSend = new File([blob], "crop.png", { type: "image/png" });
                  } else {
                    const res = await fetch(imageSrc);
                    const blob = await res.blob();
                    toSend = new File([blob], "image.png", { type: blob.type || "image/png" });
                  }
                  const form = new FormData();
                  form.append("file", toSend);
                  const res = await fetch(`${BACKEND_URL}/remove_background`, { method: "POST", body: form });
                  if (!res.ok) {
                    const t = await res.text();
                    throw new Error(t || `Remove background failed (${res.status})`);
                  }
                  const data = await res.json();
                  setResult((prev) => `${prev ? prev + "\n\n" : ""}Elimină fundalul: ${data.message}`);
                } catch (err: unknown) {
                  const message = err instanceof Error ? err.message : "Background remover error";
                  setError(message);
                }
              }}
            >
              Elimină fundalul
            </button>



            {/* Resize controls */}
          </div>

          <div className="mt-4 space-y-4">
            <div className="grid grid-cols-2 md:grid-cols-5 gap-3 items-end">
              <div>
                <label className="block text-xs mb-1">X</label>
                <input value={resizeWidth} onChange={(e) => setResizeWidth(e.target.value)} placeholder="lățime"
                       className="w-full rounded-lg p-2 bg-transparent border border-white/10" />
              </div>
              <div>
                <label className="block text-xs mb-1">Y</label>
                <input value={resizeHeight} onChange={(e) => setResizeHeight(e.target.value)} placeholder="înălțime"
                       className="w-full rounded-lg p-2 bg-transparent border border-white/10" />
              </div>
              <div>
                <label className="block text-xs mb-1">DPI</label>
                <input value={resizeDpi} onChange={(e) => setResizeDpi(e.target.value)} placeholder="dpi" 
                       className="w-full rounded-lg p-2 bg-transparent border border-white/10" />
              </div>
              <div>
                <label className="block text-xs mb-1">Unitate</label>
                <select value={resizeUnit} onChange={(e) => setResizeUnit(e.target.value)}
                        className="w-full rounded-lg p-2 bg-transparent border border-white/10">
                  <option value="mm">mm</option>
                  <option value="inch">inch</option>
                </select>
              </div>
              <div className="col-span-2 md:col-span-1">
                <button type="button" className="btn-secondary w-full whitespace-nowrap text-sm" disabled={!imageSrc}
                onClick={async () => {
                  if (!imageSrc) return;
                  setError(null);
                  setProcessedUrl(null);
                  try {
                    // input parsing
                    const w = parseFloat(resizeWidth);
                    const h = parseFloat(resizeHeight);
                    const d = parseInt(resizeDpi, 10);
                    if (!(w > 0 && h > 0 && d > 0)) {
                      throw new Error("Valori invalid dimensionare");
                    }
                    let toSend: File | null = null;
                    if (isValidSelection(selection)) {
                      const cropPixels = computeCropPixelsFromSelection(selection);
                      if (!cropPixels) throw new Error("Selecție invalidă pentru redimensionare");
                      const blob = await getCroppedBlob(imageSrc, cropPixels);
                      toSend = new File([blob], "crop.png", { type: "image/png" });
                    } else {
                      const res = await fetch(imageSrc);
                      const blob = await res.blob();
                      toSend = new File([blob], "image.png", { type: blob.type || "image/png" });
                    }
                    const form = new FormData();
                    form.append("file", toSend);
                    form.append("width", String(w));
                    form.append("height", String(h));
                    form.append("dpi", String(d));
                    form.append("unit", resizeUnit);
                    const resz = await fetch(`${BACKEND_URL}/resize`, { method: "POST", body: form });
                    if (!resz.ok) {
                      const t = await resz.text();
                      throw new Error(t || `Resize failed (${resz.status})`);
                    }
                    const outBlob = await resz.blob();
                    // Clear any prior generated PDF for old results
                    revokeUrl(processedPdfUrl);
                    setProcessedPdfUrl(null);
                    setProcessedUrl(URL.createObjectURL(outBlob));
                    setProcessedType(outBlob.type || null);
                  } catch (err: unknown) {
                    const message = err instanceof Error ? err.message : "Resize error";
                    setError(message);
                  }
                }}
                >
                  Redimensionează
                </button>
              </div>
            </div>
            
            {/* DPI Quality Warning with Large Emoji */}
            {imageSrc && naturalSize && resizeWidth && resizeHeight && resizeDpi && (
              (() => {
                const w = parseFloat(resizeWidth);
                const h = parseFloat(resizeHeight);
                const d = parseInt(resizeDpi, 10);
                const unit = (resizeUnit || "mm").trim().toLowerCase();
                
                if (!(w > 0 && h > 0 && d > 0)) return null;
                
                // Get current image dimensions (considering crop if active)
                let currentWidth = naturalSize.width;
                let currentHeight = naturalSize.height;
                
                if (isValidSelection(selection)) {
                  const cropPixels = computeCropPixelsFromSelection(selection);
                  if (cropPixels) {
                    currentWidth = cropPixels.width;
                    currentHeight = cropPixels.height;
                  }
                }
                
                // Convert to mm for calculation
                const printWidthMm = unit === "mm" ? w : w * 25.4;
                const printHeightMm = unit === "mm" ? h : h * 25.4;
                
                const quality = calculateDpiQuality(currentWidth, currentHeight, printWidthMm, printHeightMm, d);
                
                if (quality.isVeryLowQuality) {
                  // Red: Under 80% of target DPI
                  return (
                    <div className="flex items-center justify-between p-4 rounded-lg border bg-red-50 border-red-200 text-red-800">
                      <div className="flex-1">
                        <div className="font-bold text-lg mb-1">🚫 Calitate foarte scăzută</div>
                        <div className="text-sm space-y-1">
                          <div>DPI efectiv: {quality.effectiveDpi} (țintă: {d}) - {Math.round((quality.effectiveDpi / d) * 100)}%</div>
                          <div>Rezoluție actuală: {currentWidth}×{currentHeight}px</div>
                          <div>Rezoluție recomandată: {quality.recommendedWidth}×{quality.recommendedHeight}px</div>
                          <div className="mt-2 font-medium">
                            Recomandare: Folosiți o imagine cu rezoluție mai mare pentru o calitate optimă de printare.
                          </div>
                        </div>
                      </div>
                      <div className="text-6xl ml-4">🚫</div>
                    </div>
                  );
                } else if (quality.isLowQuality) {
                  // Yellow: 80-95% of target DPI
                  return (
                    <div className="flex items-center justify-between p-4 rounded-lg border bg-yellow-50 border-yellow-200 text-yellow-800">
                      <div className="flex-1">
                        <div className="font-bold text-lg mb-1">⚠️ Calitate acceptabilă</div>
                        <div className="text-sm space-y-1">
                          <div>DPI efectiv: {quality.effectiveDpi} (țintă: {d}) - {Math.round((quality.effectiveDpi / d) * 100)}%</div>
                          <div>Rezoluție actuală: {currentWidth}×{currentHeight}px</div>
                          <div>Rezoluție recomandată: {quality.recommendedWidth}×{quality.recommendedHeight}px</div>
                          <div className="mt-2 font-medium">
                            Pentru calitate optimă, considerați o rezoluție mai mare.
                          </div>
                        </div>
                      </div>
                      <div className="text-6xl ml-4">⚠️</div>
                    </div>
                  );
                } else {
                  // Green: Over 95% of target DPI
                  return (
                    <div className="flex items-center justify-between p-4 rounded-lg border bg-green-50 border-green-200 text-green-800">
                      <div className="flex-1">
                        <div className="font-bold text-lg mb-1">✅ Calitate excelentă</div>
                        <div className="text-sm">
                          <div>DPI efectiv: {quality.effectiveDpi} (țintă: {d}) - {Math.round((quality.effectiveDpi / d) * 100)}%</div>
                          <div>Rezoluție actuală: {currentWidth}×{currentHeight}px</div>
                          <div className="mt-2 font-medium">Perfectă pentru printare profesională!</div>
                        </div>
                      </div>
                      <div className="text-6xl ml-4">✅</div>
                    </div>
                  );
                }
              })()
            )}

          </div>
        </form>
        {error && (
          <p className="mt-4 text-red-400 text-sm whitespace-pre-wrap">{error}</p>
        )}
        </div>

        <div className="card p-6">
          <h2 className="text-xl font-semibold mb-2">Rezultatul analizei/procesării</h2>
          
          {/* Preview of the exact image sent to the API (image uploads) */}
          {toSendPreviewUrl && (
            <div className="mb-6">
              <h3 className="text-lg font-medium mb-3 text-[var(--accent)]">Imaginea care urmează să fie procesată</h3>
              <div className="relative w-full rounded border border-white/10" style={{ aspectRatio: "4 / 3" }}>
                <NextImage
                  src={toSendPreviewUrl}
                  alt="to-send"
                  fill
                  unoptimized
                  className="object-contain rounded"
                  sizes="(max-width: 1024px) 100vw, 50vw"
                />
              </div>
            </div>
          )}

          {/* Processed result should appear here on the right side */}
          {processedUrl && (
            <div className="mb-6">
              <h3 className="text-lg font-medium mb-3 text-[var(--accent)]">Rezultatul în format PDF</h3>
              <div className="relative w-full rounded border border-white/10" style={{ aspectRatio: "4 / 3" }}>
                {processedType === 'application/pdf' ? (
                  <iframe title="processed-pdf" src={processedUrl} className="w-full h-[60vh] rounded" />
                ) : (
                  <NextImage
                    src={processedUrl}
                    alt="processed"
                    fill
                    unoptimized
                    className="object-contain rounded"
                    sizes="(max-width: 1024px) 100vw, 50vw"
                  />
                )}
              </div>
            </div>
          )}
          {processedUrl && (
            <div className="mt-3 flex gap-3">
              <button
                type="button"
                className="btn-primary"
                onClick={async () => {
                  try {
                    if (!processedUrl) return;
                    // If already a PDF, download directly
                    if (processedType === 'application/pdf') {
                      const a = document.createElement('a');
                      a.href = processedUrl;
                      a.download = 'processed.pdf';
                      document.body.appendChild(a);
                      a.click();
                      document.body.removeChild(a);
                      return;
                    }
                    // Else convert image -> PDF via backend then download
                    const blob = await (await fetch(processedUrl)).blob();
                    const toSend = new File([blob], 'processed.png', { type: processedType || 'image/png' });
                    const form = new FormData();
                    form.append('file', toSend);
                    const res = await fetch(`${BACKEND_URL}/image_to_pdf`, { method: 'POST', body: form });
                    if (!res.ok) {
                      const t = await res.text();
                      throw new Error(t || `Conversion failed (${res.status})`);
                    }
                    const pdfBlob = await res.blob();
                    revokeUrl(processedPdfUrl);
                    const pdfUrlLocal = URL.createObjectURL(pdfBlob);
                    setProcessedPdfUrl(pdfUrlLocal);
                    const a = document.createElement('a');
                    a.href = pdfUrlLocal;
                    a.download = 'processed.pdf';
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                  } catch (err) {
                    const message = err instanceof Error ? err.message : 'Download error';
                    setError(message);
                  }
                }}
              >
                Descarcă
              </button>
            </div>
          )}
          {/* Textual analysis result from OpenAI for both images and PDFs */}
          {result && (
            <div className="mt-6">
              <pre className="mt-1 whitespace-pre-wrap text-sm leading-6">{result}</pre>
            </div>
          )}
        </div>
      </section>

      {/* Removed separate results section; processed image now appears in the right panel above */}
      </div>
  );
}