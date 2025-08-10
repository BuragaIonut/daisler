"use client";

import { useEffect, useRef, useState } from "react";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

export default function Home() {
  const [file, setFile] = useState<File | null>(null);
  const [imageSrc, setImageSrc] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const imgRef = useRef<HTMLImageElement | null>(null);
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
      img.addEventListener("error", (e) => reject(e));
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

  function maybeClearTinySelection() {
    if (selection && (selection.width < 8 || selection.height < 8)) {
      setSelection(null);
    }
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

  async function refreshToSendPreview() {
    if (!imageSrc) {
      revokeUrl(toSendPreviewUrl);
      setToSendPreviewUrl(null);
      return;
    }
    try {
      if (selection) {
        const imgEl = imgRef.current;
        const contEl = containerRef.current;
        if (!imgEl || !contEl) return;
        const naturalW = imgEl.naturalWidth;
        const naturalH = imgEl.naturalHeight;
        const rect = contEl.getBoundingClientRect();
        const displayedW = rect.width;
        const displayedH = imgEl.getBoundingClientRect().height;
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
        // Preview original
        const res = await fetch(imageSrc);
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        revokeUrl(toSendPreviewUrl);
        setToSendPreviewUrl(url);
        setToSendType(blob.type || "image/png");
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
        const imgEl = imgRef.current;
        const contEl = containerRef.current;
        if (imgEl && contEl) {
          const naturalW = imgEl.naturalWidth;
          const naturalH = imgEl.naturalHeight;
          const rect = contEl.getBoundingClientRect();
          const displayedW = rect.width;
          const displayedH = imgEl.getBoundingClientRect().height;

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
    } catch (err: any) {
      setError(err.message || "Crop failed");
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

    // Ensure preview matches exactly what is being sent
    try {
      const url = URL.createObjectURL(fileToSend);
      revokeUrl(toSendPreviewUrl);
      setToSendPreviewUrl(url);
      setToSendType(fileToSend.type || "image/png");
    } catch {}

    form.append("file", fileToSend);
    form.append("use_case", useCase);
    setLoading(true);
    try {
      const res = await fetch(`${BACKEND_URL}/analyze`, {
        method: "POST",
        body: form,
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t || `Request failed (${res.status})`);
      }
      const data = await res.json();
      setResult(data.result ?? "No result");
    } catch (err: any) {
      setError(err.message || "Unexpected error");
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
        const imgEl = imgRef.current;
        const contEl = containerRef.current;
        if (imgEl && contEl) {
          const naturalW = imgEl.naturalWidth;
          const naturalH = imgEl.naturalHeight;
          const rect = contEl.getBoundingClientRect();
          const displayedW = rect.width;
          const displayedH = imgEl.getBoundingClientRect().height;
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
    } catch (err: any) {
      setError(err.message || "Crop failed");
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
    } catch (err: any) {
      setError(err.message || "Processing error");
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
    } catch (err: any) {
      setHealthStatus(`Error: ${err.message || "Unknown error"}`);
    } finally {
      setCheckingHealth(false);
    }
  };

  return (
    <div className="mx-auto max-w-[1400px] px-6">
      <section className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        <div className="card p-6">
        <h2 className="text-xl font-semibold mb-2">Analyze your artwork</h2>
        <p className="text-sm text-[var(--muted)] mb-6">
          Upload an image and tell us the intended use. We’ll check format, text, composition, centering, and bleed.
        </p>
        <form onSubmit={onSubmit} className="space-y-5">
          <div>
            <label className="block text-sm font-medium mb-2">Image (jpeg/jpg/png)</label>
            <div className="glass rounded-lg p-3">
              <input
                type="file"
                accept="image/jpeg,image/jpg,image/png"
                onChange={async (e) => {
                  const f = e.target.files?.[0] ?? null;
                  setFile(f);
                  if (f) {
                    const dataUrl = await readFileToDataURL(f);
                    setImageSrc(dataUrl);
                    setSelection(null);
                    setStartPoint(null);
                    revokeUrl(toSendPreviewUrl);
                    setToSendPreviewUrl(null);
                  } else {
                    setImageSrc(null);
                    setSelection(null);
                  }
                }}
                className="block w-full text-sm file:mr-4 file:rounded-md file:border-0 file:bg-[var(--accent)] file:text-white file:px-3 file:py-1.5"
              />
            </div>
          </div>
          {imageSrc && (
            <div
              className="relative rounded-lg overflow-hidden glass"
              ref={containerRef}
              onMouseDown={(e) => {
                const rect = (e.currentTarget as HTMLDivElement).getBoundingClientRect();
                setSelecting(true);
                const x = e.clientX - rect.left;
                const y = e.clientY - rect.top;
                setStartPoint({ x, y });
                setSelection({ x, y, width: 0, height: 0 });
              }}
              onMouseMove={(e) => {
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
              <img
                ref={imgRef}
                src={imageSrc}
                alt="preview"
                className="w-full h-auto max-h-[75vh] object-contain block select-none"
                draggable={false}
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
          <div>
            <label className="block text-sm font-medium mb-2">Use case</label>
            <input
              type="text"
              placeholder="e.g., business card, poster, tshirt, sticker"
              value={useCase}
              onChange={(e) => setUseCase(e.target.value)}
              className="w-full rounded-lg p-3 bg-transparent border border-white/10 focus:outline-none focus:ring-2 focus:ring-[var(--accent)]"
            />
          </div>
          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={loading}
              className="btn-primary disabled:opacity-60"
            >
              {loading ? "Analyzing..." : "Analyze artwork"}
            </button>
            <button
              type="button"
              onClick={onProcess}
              className="btn-primary disabled:opacity-60"
            >
              Process (bleed + cut)
            </button>
            {imageSrc && selection && (
              <button
                type="button"
                onClick={() => {
                  setSelection(null);
                  refreshToSendPreview();
                }}
                className="text-xs px-3 py-2 rounded border border-white/10 hover:bg-white/5"
              >
                Clear selection
              </button>
            )}
            <button
              type="button"
              onClick={checkHealth}
              disabled={checkingHealth}
              className="text-xs px-3 py-2 rounded border border-white/10 hover:bg-white/5 disabled:opacity-60"
            >
              {checkingHealth ? "Checking..." : "Check API Health"}
            </button>
            {healthStatus && (
              <span className="text-xs text-[var(--muted)]">{healthStatus}</span>
            )}
            <span className="text-xs text-[var(--muted)]">Backend: {BACKEND_URL}</span>
          </div>
        </form>
        {error && (
          <p className="mt-4 text-red-400 text-sm whitespace-pre-wrap">{error}</p>
        )}
        </div>

        <div className="card p-6">
          <h2 className="text-xl font-semibold mb-2">Will be sent to API</h2>
          {!toSendPreviewUrl && (
            <p className="text-sm text-[var(--muted)]">Select or crop an image to see the outgoing preview.</p>
          )}
          {toSendPreviewUrl && (
            <img
              src={toSendPreviewUrl}
              alt="to-send"
              className="w-full h-auto max-h-[75vh] object-contain rounded border border-white/10"
            />
          )}
          <p className="text-xs text-[var(--muted)] mt-2">Type: {toSendType}</p>
        </div>
      </section>

      <section className="card p-6">
        <h2 className="text-xl font-semibold mb-2">Results</h2>
        {!result && (
          <p className="text-sm text-[var(--muted)]">Results will appear here after analysis.</p>
        )}
        {result && (
          <pre className="mt-3 whitespace-pre-wrap text-sm leading-6">{result}</pre>
        )}
        {processedUrl && (
          <div className="mt-6">
            <h3 className="text-sm font-medium mb-2">Processed image (with bleed and cut lines)</h3>
            <img src={processedUrl} alt="processed" className="w-full h-auto max-h-[75vh] object-contain rounded border border-white/10" />
          </div>
        )}
      </section>
      </div>
  );
}