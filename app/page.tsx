"use client";

import { useEffect, useRef, useState } from "react";
import NextImage from "next/image";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

export default function Home() {
  const [file, setFile] = useState<File | null>(null);
  const [imageSrc, setImageSrc] = useState<string | null>(null);
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [naturalSize, setNaturalSize] = useState<{ width: number; height: number } | null>(null);
  const [zoom, setZoom] = useState<number>(1);
  const [transformOrigin, setTransformOrigin] = useState<string>("center center");
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
  const [healthStatus, setHealthStatus] = useState<string | null>(null);
  const [checkingHealth, setCheckingHealth] = useState(false);

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

  // End selection even if mouse is released outside the image container
  useEffect(() => {
    const onWinMouseUp = () => setSelecting(false);
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
      setTransformOrigin(`${pointerX}px ${pointerY}px`);
      const zoomFactor = e.deltaY < 0 ? 1.1 : 0.9; // smooth multiplicative zoom
      setZoom((prevZoom) => Math.min(5, Math.max(0.2, Number((prevZoom * zoomFactor).toFixed(3)))));
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel as EventListener);
  }, [imageSrc, naturalSize]);

  // Reset pan when a new image is loaded
  useEffect(() => {
    setTransformOrigin("center center");
    setZoom(1);
  }, [imageSrc]);

  function maybeClearTinySelection() {
    if (selection && (selection.width < 8 || selection.height < 8)) {
      setSelection(null);
    }
  }

  function isValidSelection(sel: { x: number; y: number; width: number; height: number } | null): sel is { x: number; y: number; width: number; height: number } {
    return !!sel && sel.width >= 8 && sel.height >= 8;
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

  // Cleanup any created PDF object URL
  useEffect(() => {
    return () => revokeUrl(pdfUrl);
  }, [pdfUrl]);

  async function refreshToSendPreview() {
    if (!imageSrc) {
      revokeUrl(toSendPreviewUrl);
      setToSendPreviewUrl(null);
      return;
    }
    try {
      if (isValidSelection(selection)) {
        const contEl = containerRef.current;
        if (!contEl || !naturalSize) return;
        const naturalW = naturalSize.width;
        const naturalH = naturalSize.height;
        const rect = contEl.getBoundingClientRect();
        const displayedW = rect.width;
        const displayedH = rect.height;
        const scaleX = naturalW / displayedW;
        const scaleY = naturalH / displayedH;
        const cropPixels = {
          x: Math.max(0, Math.floor(selection.x * scaleX)),
          y: Math.max(0, Math.floor(selection.y * scaleY)),
          width: Math.max(1, Math.floor(selection.width * scaleX)),
          height: Math.max(1, Math.floor(selection.height * scaleY)),
        };
        const blob = await getCroppedBlob(imageSrc, cropPixels);
        const url = URL.createObjectURL(blob);
        revokeUrl(toSendPreviewUrl);
        setToSendPreviewUrl(url);
        setToSendType(blob.type || "image/png");
      } else {
        // No valid crop → do not show preview
        revokeUrl(toSendPreviewUrl);
        setToSendPreviewUrl(null);
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
        const contEl = containerRef.current;
        if (contEl && naturalSize) {
          const naturalW = naturalSize.width;
          const naturalH = naturalSize.height;
          const rect = contEl.getBoundingClientRect();
          const displayedW = rect.width;
          const displayedH = rect.height;

          const scaleX = naturalW / displayedW;
          const scaleY = naturalH / displayedH;

          const cropPixels = {
            x: Math.max(0, Math.floor(selection.x * scaleX)),
            y: Math.max(0, Math.floor(selection.y * scaleY)),
            width: Math.max(1, Math.floor(selection.width * scaleX)),
            height: Math.max(1, Math.floor(selection.height * scaleY)),
          };

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
    if (!imageSrc && !file) {
      setError("Please select an image first.");
      return;
    }

    // Build the exact same file that would be sent (respecting crop)
    let fileToSend: File | null = file;
    try {
      if (imageSrc && selection) {
        const contEl = containerRef.current;
        if (contEl && naturalSize) {
          const naturalW = naturalSize.width;
          const naturalH = naturalSize.height;
          const rect = contEl.getBoundingClientRect();
          const displayedW = rect.width;
          const displayedH = rect.height;
          const scaleX = naturalW / displayedW;
          const scaleY = naturalH / displayedH;
          const cropPixels = {
            x: Math.max(0, Math.floor(selection.x * scaleX)),
            y: Math.max(0, Math.floor(selection.y * scaleY)),
            width: Math.max(1, Math.floor(selection.width * scaleX)),
            height: Math.max(1, Math.floor(selection.height * scaleY)),
          };
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
                  if (f) {
                    if (f.type === 'application/pdf') {
                      // PDF flow
                      revokeUrl(pdfUrl);
                      const url = URL.createObjectURL(f);
                      setPdfUrl(url);
                      // reset image-related state
                      setImageSrc(null);
                      setNaturalSize(null);
                      setSelection(null);
                      setStartPoint(null);
                      setZoom(1);
                      revokeUrl(toSendPreviewUrl);
                      setToSendPreviewUrl(null);
                    } else {
                      // Image flow
                      revokeUrl(pdfUrl);
                      setPdfUrl(null);
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
                setSelecting(true);
                const x = e.clientX - rect.left;
                const y = e.clientY - rect.top;
                setStartPoint({ x, y });
                setSelection({ x, y, width: 0, height: 0 });
              }}
               onMouseMove={(e: React.MouseEvent<HTMLDivElement>) => {
                if (!selecting || !startPoint) return;
                const rect = (e.currentTarget as HTMLDivElement).getBoundingClientRect();
                let x = e.clientX - rect.left;
                let y = e.clientY - rect.top;
                x = Math.max(0, Math.min(x, rect.width));
                y = Math.max(0, Math.min(y, rect.height));
                const sx = Math.min(startPoint.x, x);
                const sy = Math.min(startPoint.y, y);
                const w = Math.abs(x - startPoint.x);
                const h = Math.abs(y - startPoint.y);
                setSelection({ x: sx, y: sy, width: w, height: h });
              }}
              onMouseUp={() => {
                setSelecting(false);
                maybeClearTinySelection();
                refreshToSendPreview();
              }}
              onMouseLeave={() => {
                setSelecting(false);
                maybeClearTinySelection();
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
                style={{ transform: `scale(${zoom})`, transformOrigin }}
              />
              {selection && selection.width > 2 && selection.height > 2 && (
                <div
                  className="absolute border-2 border-[var(--accent)] bg-[rgba(99,102,241,0.15)]"
                  style={{
                    left: selection.x,
                    top: selection.y,
                    width: selection.width,
                    height: selection.height,
                  }}
                />
              )}
            </div>
          )}
          {!imageSrc && pdfUrl && (
            <div className="relative rounded-lg overflow-hidden glass w-full">
              <iframe title="pdf-preview" src={pdfUrl} className="w-full h-[75vh] rounded" />
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
              disabled={!!pdfUrl}
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
                  if (isValidSelection(selection) && containerRef.current && naturalSize) {
                    const rect = containerRef.current.getBoundingClientRect();
                    const scaleX = naturalSize.width / rect.width;
                    const scaleY = naturalSize.height / rect.height;
                    const cropPixels = {
                      x: Math.max(0, Math.floor(selection.x * scaleX)),
                      y: Math.max(0, Math.floor(selection.y * scaleY)),
                      width: Math.max(1, Math.floor(selection.width * scaleX)),
                      height: Math.max(1, Math.floor(selection.height * scaleY)),
                    };
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
            {imageSrc && isValidSelection(selection) && (
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
            {imageSrc && (
              <button
                type="button"
                className="btn-outline text-xs"
                onClick={() => { setZoom(1); setTransformOrigin("center center"); }}
              >
                Reset zoom
              </button>
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
          )}
          {/* For PDFs, show the PDF itself on the right as well */}
          {!toSendPreviewUrl && pdfUrl && (
            <div className="relative w-full rounded border border-white/10" style={{ aspectRatio: "4 / 3" }}>
              <iframe title="pdf-to-send" src={pdfUrl} className="w-full h-[60vh] rounded" />
            </div>
          )}
          {/* Processed image should appear here on the right side */}
          {processedUrl && !toSendPreviewUrl && (
            <div className="relative w-full rounded border border-white/10 mt-4" style={{ aspectRatio: "4 / 3" }}>
              <NextImage
                src={processedUrl}
                alt="processed"
                fill
                unoptimized
                className="object-contain rounded"
                sizes="(max-width: 1024px) 100vw, 50vw"
              />
            </div>
          )}
          {processedUrl && toSendPreviewUrl && (
            <div className="relative w-full rounded border border-white/10 mt-4" style={{ aspectRatio: "4 / 3" }}>
              <NextImage
                src={processedUrl}
                alt="processed"
                fill
                unoptimized
                className="object-contain rounded"
                sizes="(max-width: 1024px) 100vw, 50vw"
              />
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