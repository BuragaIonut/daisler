"use client";

import { useEffect, useRef, useState } from "react";
import NextImage from "next/image";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000/api";

export default function Home() {
  const [file, setFile] = useState<File | null>(null);
  const [imageSrc, setImageSrc] = useState<string | null>(null);
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const aiExtensionRef = useRef<HTMLDivElement | null>(null);
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
  const [bleedSize, setBleedSize] = useState<string>("3");
  const [addCutline, setAddCutline] = useState<boolean>(false);
  const [processingForPrint, setProcessingForPrint] = useState(false);
  
  // AI Extension selection state
  const [extensionOptions, setExtensionOptions] = useState<Array<{
    overlap_percentage: number;
    extended_image: string;
    mask_preview: string;
    temp_path: string;
  }>>([]);
  const [selectedOptionIndex, setSelectedOptionIndex] = useState<number>(0);
  const [showingOptions, setShowingOptions] = useState(false);
  const [loadingExtensions, setLoadingExtensions] = useState(false);
  const [currentGeneratingIndex, setCurrentGeneratingIndex] = useState<number>(-1);
  const [availableOverlaps, setAvailableOverlaps] = useState<number[]>([]);
  const [aiExtensionParams, setAiExtensionParams] = useState<any>(null);
  const [expandedCardIndex, setExpandedCardIndex] = useState<number | null>(null);
  const [fullscreenCardIndex, setFullscreenCardIndex] = useState<number | null>(null);
  
  // Debug info state
  const [debugInfo, setDebugInfo] = useState<{
    currentImageDims?: { width: number; height: number };
    croppedImageDims?: { width: number; height: number };
    desiredDims?: { width: number; height: number; unit: string };
    desiredDimsMm?: { width: number; height: number };
    desiredPixels?: { width: number; height: number };
    currentRatio?: number;
    desiredRatio?: number;
    scalingFactor?: number;
    strategy?: string;
    selectedOverlap?: number;
    effectiveDpi?: number;
    targetDpi?: number;
    bleedPx?: number;
    intermediaryImages?: Array<{
      name: string;
      url: string;
      dimensions?: { width: number; height: number };
    }>;
  }>({});
  const [showDebug, setShowDebug] = useState(false);
  
  // Global units and format selection
  const [globalUnit, setGlobalUnit] = useState<string>("mm");
  const [selectedFormat, setSelectedFormat] = useState<string>("A4");
  const [customWidth, setCustomWidth] = useState<string>("210");
  const [customHeight, setCustomHeight] = useState<string>("297");
  
  // Cropping mode state
  const [cropMode, setCropMode] = useState<"free" | "fixed">("free");
  const [fixedWidth, setFixedWidth] = useState<string>("100");
  const [fixedHeight, setFixedHeight] = useState<string>("100");
  const [dragging, setDragging] = useState(false);

  // Common formats with dimensions in mm
  const commonFormats = {
    "A4": { width: 210, height: 297 },
    "A3": { width: 297, height: 420 },
    "A5": { width: 148, height: 210 },
    "Letter": { width: 215.9, height: 279.4 },
    "Legal": { width: 215.9, height: 355.6 },
    "Tabloid": { width: 279.4, height: 431.8 },
    "Business Card": { width: 85, height: 55 },
    "Postcard": { width: 148, height: 105 },
    "Poster A2": { width: 420, height: 594 },
    "Poster A1": { width: 594, height: 841 },
    "Custom": { width: 0, height: 0 }
  };

  // Convert dimensions based on global unit
  const convertDimensions = (mmValue: number) => {
    return globalUnit === "mm" ? mmValue : Number((mmValue / 25.4).toFixed(2));
  };

  // Get current format dimensions
  const getCurrentFormatDimensions = () => {
    if (selectedFormat === "Custom") {
      return {
        width: parseFloat(customWidth) || 0,
        height: parseFloat(customHeight) || 0
      };
    }
    const format = commonFormats[selectedFormat as keyof typeof commonFormats];
    return {
      width: convertDimensions(format.width),
      height: convertDimensions(format.height)
    };
  };

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

  // Refresh preview when selection or zoom changes
  useEffect(() => {
    refreshToSendPreview();
  }, [selection, zoom, imageSrc]);

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
    if ((!file && !imageSrc)) {
      setError("Please select an image.");
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
    
    // Use the selected format as use case
    const formatDims = getCurrentFormatDimensions();
    const formatUseCase = selectedFormat === "Custom" 
      ? `Custom format: ${formatDims.width}×${formatDims.height} ${globalUnit}`
      : `${selectedFormat} format (${formatDims.width}×${formatDims.height} ${globalUnit})`;
    
    form.append("use_case", formatUseCase);
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

  const generateNextExtension = async (index: number, strategyData: any, inputFile: File) => {
    if (!strategyData || !inputFile) return;
    
    setCurrentGeneratingIndex(index);
    setLoadingExtensions(true);
    
    try {
      if (strategyData.status === "needs_two_step_extension") {
        // Two-step strategy
        const step1Params = strategyData.step1_params;
        const step2Params = strategyData.step2_params;
        const overlapPct = step2Params.overlap_percentages[index];
        
        console.log(`Two-step generation for ${overlapPct}%: Step 1 - Converting to square...`);
        
        // Step 1: Convert to square
        const step1Form = new FormData();
        step1Form.append("file", inputFile);
        step1Form.append("target_width", String(step1Params.target_width));
        step1Form.append("target_height", String(step1Params.target_height));
        step1Form.append("overlap_percentage", String(overlapPct));
        step1Form.append("overlap_horizontally", String(step1Params.overlap_horizontally));
        step1Form.append("overlap_vertically", String(step1Params.overlap_vertically));
        
        const step1Res = await fetch(`${BACKEND_URL}/ai_extend_with_mask`, {
          method: "POST",
          body: step1Form
        });
        
        if (!step1Res.ok) {
          const errorText = await step1Res.text();
          throw new Error(`Step1 AI extension failed for ${overlapPct}%: ${errorText}`);
        }
        
        const step1Data = await step1Res.json();
        console.log(`✓ Step1 complete: square with ${overlapPct}% overlap`);
        
        // Step 2: Convert square to final ratio
        console.log(`Step 2 - Converting to final dimensions...`);
        const step1ImageBlob = await fetch(step1Data.extended_image).then(r => r.blob());
        const step1File = new File([step1ImageBlob], `square_${overlapPct}.png`, { type: "image/png" });
        
        const step2Form = new FormData();
        step2Form.append("file", step1File);
        step2Form.append("target_width", String(step2Params.target_width));
        step2Form.append("target_height", String(step2Params.target_height));
        step2Form.append("overlap_percentage", String(overlapPct));
        step2Form.append("overlap_horizontally", String(step2Params.overlap_horizontally));
        step2Form.append("overlap_vertically", String(step2Params.overlap_vertically));
        
        const step2Res = await fetch(`${BACKEND_URL}/ai_extend_with_mask`, {
          method: "POST",
          body: step2Form
        });
        
        if (!step2Res.ok) {
          const errorText = await step2Res.text();
          throw new Error(`Step2 AI extension failed for ${overlapPct}%: ${errorText}`);
        }
        
        const step2Data = await step2Res.json();
        console.log(`✓ Step2 complete: final with ${overlapPct}% overlap`);
        
        // Add the final result
        setExtensionOptions(prev => [...prev, step2Data]);
        
      } else {
        // Single-step strategy
        const aiParams = strategyData.ai_extension_params;
        const overlapPct = aiParams.overlap_percentages[index];
        
        console.log(`Generating AI extension for ${overlapPct}% overlap...`);
        
        const aiForm = new FormData();
        aiForm.append("file", inputFile);
        aiForm.append("target_width", String(aiParams.target_width));
        aiForm.append("target_height", String(aiParams.target_height));
        aiForm.append("overlap_percentage", String(overlapPct));
        aiForm.append("overlap_horizontally", String(aiParams.overlap_horizontally));
        aiForm.append("overlap_vertically", String(aiParams.overlap_vertically));
        
        const aiRes = await fetch(`${BACKEND_URL}/ai_extend_with_mask`, {
          method: "POST",
          body: aiForm
        });
        
        if (!aiRes.ok) {
          const errorText = await aiRes.text();
          throw new Error(`AI extension failed for ${overlapPct}%: ${errorText}`);
        }
        
        const aiData = await aiRes.json();
        console.log(`✓ AI extension complete for ${overlapPct}% overlap`);
        
        // Add result
        setExtensionOptions(prev => [...prev, aiData]);
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Extension generation error";
      setError(message);
    } finally {
      setLoadingExtensions(false);
      setCurrentGeneratingIndex(-1);
    }
  };

  const onProcess = async () => {
    setError(null);
    setProcessedUrl(null);
    setProcessedType(null);
    revokeUrl(processedPdfUrl);
    setProcessedPdfUrl(null);
    setDebugInfo({}); // Clear previous debug info
    
    if (!imageSrc && !file) {
      setError("Please select an image first.");
      return;
    }

    // Get target dimensions from format selection
    const formatDims = getCurrentFormatDimensions();
    if (formatDims.width <= 0 || formatDims.height <= 0) {
      setError("Please select valid dimensions.");
      return;
    }

    // Get DPI
    const targetDpi = parseInt(resizeDpi, 10);
    if (!targetDpi || targetDpi <= 0) {
      setError("Please enter a valid DPI.");
      return;
    }

    // Calculate debug info
    const debug: typeof debugInfo = {
      desiredDims: { 
        width: formatDims.width, 
        height: formatDims.height, 
        unit: globalUnit 
      },
      targetDpi: targetDpi,
      intermediaryImages: []
    };

    // Convert to mm for calculations
    const targetWidthMm = globalUnit === "mm" 
      ? formatDims.width 
      : formatDims.width * 25.4;
    const targetHeightMm = globalUnit === "mm" 
      ? formatDims.height 
      : formatDims.height * 25.4;
    debug.desiredDimsMm = { width: targetWidthMm, height: targetHeightMm };

    // Calculate desired pixels
    const desiredWidthPx = Math.round((targetWidthMm / 25.4) * targetDpi);
    const desiredHeightPx = Math.round((targetHeightMm / 25.4) * targetDpi);
    debug.desiredPixels = { width: desiredWidthPx, height: desiredHeightPx };
    debug.desiredRatio = desiredWidthPx / desiredHeightPx;

    // Get current image dimensions
    if (naturalSize) {
      debug.currentImageDims = { 
        width: naturalSize.width, 
        height: naturalSize.height 
      };
      debug.currentRatio = naturalSize.width / naturalSize.height;
    }

    // Calculate bleed in pixels
    const bleedValue = parseFloat(bleedSize) || 0;
    if (bleedValue > 0) {
      debug.bleedPx = Math.round((bleedValue / 25.4) * targetDpi);
    }

    // Build the exact same file that would be sent (respecting crop)
    let fileToSend: File | null = file;
    
    // CRITICAL: If the original file is a PDF, we must convert it to image first
    if (fileToSend && fileToSend.type === 'application/pdf') {
      try {
        const pdfForm = new FormData();
        pdfForm.append('file', fileToSend);
        const pdfRes = await fetch(`${BACKEND_URL}/pdf_to_image`, {
          method: 'POST',
          body: pdfForm
        });
        if (!pdfRes.ok) {
          throw new Error(`PDF conversion failed (${pdfRes.status})`);
        }
        const imageBlob = await pdfRes.blob();
        fileToSend = new File([imageBlob], "converted.png", { 
          type: "image/png" 
        });
        
        // Update imageSrc for cropping if needed
        if (!imageSrc) {
          const convertedUrl = URL.createObjectURL(imageBlob);
          setImageSrc(convertedUrl);
        }
      } catch (err: unknown) {
        const message = err instanceof Error 
          ? err.message 
          : "PDF conversion failed";
        setError(message);
        return;
      }
    }
    
    try {
      if (imageSrc && selection) {
        const cropPixels = computeCropPixelsFromSelection(selection);
        if (cropPixels) {
          const blob = await getCroppedBlob(imageSrc, cropPixels);
          fileToSend = new File([blob], "crop.png", { type: "image/png" });
          debug.croppedImageDims = { 
            width: cropPixels.width, 
            height: cropPixels.height 
          };
          debug.currentRatio = cropPixels.width / cropPixels.height;
          
          // Add cropped image to intermediary images
          const croppedUrl = URL.createObjectURL(blob);
          debug.intermediaryImages?.push({
            name: "Cropped Image",
            url: croppedUrl,
            dimensions: { width: cropPixels.width, height: cropPixels.height }
          });
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
      fileToSend = new File([blob], "image.png", { 
        type: blob.type || "image/png" 
      });
    }
    if (!fileToSend) {
      setError("No file to process");
      return;
    }

    // Calculate scaling factor
    const currentWidth = debug.croppedImageDims?.width || 
      debug.currentImageDims?.width || 0;
    const currentHeight = debug.croppedImageDims?.height || 
      debug.currentImageDims?.height || 0;
    if (currentWidth > 0 && currentHeight > 0) {
      const scaleX = desiredWidthPx / currentWidth;
      const scaleY = desiredHeightPx / currentHeight;
      debug.scalingFactor = Math.max(scaleX, scaleY);
      
      // Calculate effective DPI
      const printWidthInch = targetWidthMm / 25.4;
      const printHeightInch = targetHeightMm / 25.4;
      const effectiveDpiX = currentWidth / printWidthInch;
      const effectiveDpiY = currentHeight / printHeightInch;
      debug.effectiveDpi = Math.round(Math.min(effectiveDpiX, effectiveDpiY));
    }

    // Determine strategy (basic logic - backend will do the actual calculation)
    if (debug.currentRatio && debug.desiredRatio) {
      const cr = debug.currentRatio;
      const dr = debug.desiredRatio;
      
      if (Math.abs(cr - dr) < 0.01) {
        debug.strategy = "no_extension_needed";
      } else if (dr > 1) {
        // Landscape desired
        if (cr > 1) {
          debug.strategy = cr < dr 
            ? "landscape_extend_width" 
            : "landscape_extend_height";
        } else if (cr < 1) {
          debug.strategy = "portrait_to_square_to_landscape";
        } else {
          debug.strategy = "square_to_landscape";
        }
      } else if (dr < 1) {
        // Portrait desired
        if (cr < 1) {
          debug.strategy = cr > dr 
            ? "portrait_extend_height" 
            : "portrait_extend_width";
        } else if (cr > 1) {
          debug.strategy = "landscape_to_square_to_portrait";
        } else {
          debug.strategy = "square_to_portrait";
        }
      } else {
        // Square desired
        if (cr > 1) {
          debug.strategy = "landscape_to_square";
        } else if (cr < 1) {
          debug.strategy = "portrait_to_square";
        } else {
          debug.strategy = "no_extension_needed";
        }
      }
    }

    setDebugInfo(debug);

    setProcessingForPrint(true);
    const form = new FormData();
    form.append("file", fileToSend);
    form.append("target_width_mm", String(formatDims.width));
    form.append("target_height_mm", String(formatDims.height));
    form.append("unit", globalUnit);
    form.append("dpi", String(targetDpi));
    form.append("to_add_cutline", String(addCutline));

    const bleedValueToSend = parseFloat(bleedSize) || 0;
    form.append("add_bleed", String(bleedValueToSend > 0));
    form.append("bleed_mm", bleedSize);

    try {
      // Step 1: Get AI extension parameters (doesn't do extension yet)
      const res = await fetch(`${BACKEND_URL}/process_for_print_step1`, { 
        method: "POST", 
        body: form 
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t || `Process failed (${res.status})`);
      }
      
      const data = await res.json();
      console.log("Received strategy data from step1:", data);
      
      // If no extension needed, proceed directly to step 2
      if (data.status === "no_extension_needed") {
        // Call step 2 directly without showing options
        await finalizePrint(fileToSend, formatDims, targetDpi);
        return;
      }
      
      // Reset and prepare for sequential loading
      setExtensionOptions([]);
      setShowingOptions(true);
      setLoadingExtensions(false);
      setCurrentGeneratingIndex(-1);
      
      // Scroll to AI Extension section after a short delay to let it render
      setTimeout(() => {
        aiExtensionRef.current?.scrollIntoView({ 
          behavior: 'smooth', 
          block: 'start' 
        });
      }, 100);
      
      // Store AI extension params for sequential generation
      if (data.status === "needs_two_step_extension") {
        // For two-step, we'll handle it differently
        setAiExtensionParams({
          isTwoStep: true,
          step1Params: data.step1_params,
          step2Params: data.step2_params,
          fileToSend: fileToSend,
          strategy: data.strategy
        });
        setAvailableOverlaps(data.step2_params.overlap_percentages);
      } else if (data.status === "needs_extension" && data.ai_extension_params) {
        // Single-step strategy with ai_extension_params
        setAiExtensionParams({
          isTwoStep: false,
          ...data.ai_extension_params,
          fileToSend: fileToSend
        });
        setAvailableOverlaps(data.ai_extension_params.overlap_percentages);
      } else if (data.status === "needs_extension" && data.overlap_percentages) {
        // Strategy needs extension but backend returned simplified response
        // (portrait_to_square, landscape_to_square)
        setAiExtensionParams({
          isTwoStep: false,
          target_width: data.target_width || 1024,
          target_height: data.target_height || 1024,
          overlap_horizontally: data.overlap_horizontally || false,
          overlap_vertically: data.overlap_vertically || false,
          fileToSend: fileToSend,
          strategy: data.strategy
        });
        setAvailableOverlaps(data.overlap_percentages);
      } else {
        // Fallback for unknown status
        throw new Error(`Unexpected response status: ${data.status}`);
      }
      
      // Automatically generate the first option (3%)
      await generateNextExtension(0, data, fileToSend);
      
      setSelectedOptionIndex(0);
      setError(null);
      
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Processing error";
      setError(message);
      setLoadingExtensions(false);
    } finally {
      setProcessingForPrint(false);
    }
  };

  const finalizePrint = async (
    imageFile: File | string,
    formatDims: { width: number; height: number },
    targetDpi: number
  ) => {
    setProcessingForPrint(true);
    setError(null);
    
    try {
      const form = new FormData();
      
      // If imageFile is a string (temp_path from step1), use it directly
      if (typeof imageFile === 'string') {
        form.append("selected_image_path", imageFile);
      } else {
        // This shouldn't happen in step1->step2 flow, but handle it
        form.append("file", imageFile);
      }
      
      form.append("target_width", String(formatDims.width));
      form.append("target_height", String(formatDims.height));
      form.append("unit", globalUnit);
      form.append("dpi", String(targetDpi));
      const bleedValueToSend = parseFloat(bleedSize) || 0;
      form.append("add_bleed", String(bleedValueToSend > 0));
      form.append("bleed_mm", bleedSize);
      form.append("to_add_cutline", String(addCutline));

      const res = await fetch(`${BACKEND_URL}/process_for_print_step2`, {
        method: "POST",
        body: form
      });
      
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t || `Final processing failed (${res.status})`);
      }
      
      const blob = await res.blob();
      if (processedUrl) URL.revokeObjectURL(processedUrl);
      setProcessedUrl(URL.createObjectURL(blob));
      setProcessedType("application/pdf");
      
      // Clear extension options after successful processing
      setShowingOptions(false);
      setExtensionOptions([]);
      setLoadingExtensions(false);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Processing error";
      setError(message);
    } finally {
      setProcessingForPrint(false);
    }
  };

  const onSelectAndFinalize = async () => {
    if (extensionOptions.length === 0 || selectedOptionIndex < 0) {
      setError("Please select an option first");
      return;
    }
    
    const selectedOption = extensionOptions[selectedOptionIndex];
    const formatDims = getCurrentFormatDimensions();
    const targetDpi = parseInt(resizeDpi, 10);
    
    // Update debug info with selected overlap
    setDebugInfo(prev => ({
      ...prev,
      selectedOverlap: selectedOption.overlap_percentage
    }));
    
    await finalizePrint(
      selectedOption.temp_path,
      formatDims,
      targetDpi
    );
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
      <header className="mb-8 flex justify-between items-start">
        <h1 className="text-3xl font-bold heading">Daisler Print Processor</h1>
        {/* Global Units, DPI, and Bleed Picker */}
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <label className="text-sm font-medium">Unități:</label>
            <select 
              value={globalUnit} 
              onChange={(e) => setGlobalUnit(e.target.value)}
              className="rounded-lg p-2 bg-white border border-gray-300 text-gray-800 text-sm min-w-16 hover:border-gray-400 focus:border-[var(--accent)] focus:outline-none focus:ring-1 focus:ring-[var(--accent)]"
            >
              <option value="mm">mm</option>
              <option value="inch">inch</option>
            </select>
          </div>
          <div className="flex items-center gap-2">
            <label className="text-sm font-medium">DPI:</label>
            <input 
              value={resizeDpi} 
              onChange={(e) => setResizeDpi(e.target.value)} 
              placeholder="300"
              className="rounded-lg p-2 bg-white border border-gray-300 text-gray-800 text-sm w-20 hover:border-gray-400 focus:border-[var(--accent)] focus:outline-none focus:ring-1 focus:ring-[var(--accent)]"
            />
          </div>
          <div className="flex items-center gap-2">
            <label className="text-sm font-medium">Bleed:</label>
            <select 
              value={bleedSize} 
              onChange={(e) => setBleedSize(e.target.value)}
              className="rounded-lg p-2 bg-white border border-gray-300 text-gray-800 text-sm min-w-24 hover:border-gray-400 focus:border-[var(--accent)] focus:outline-none focus:ring-1 focus:ring-[var(--accent)]"
            >
              <option value="0">No bleed</option>
              <option value="3">3mm</option>
              <option value="5">5mm</option>
              <option value="10">10mm</option>
            </select>
          </div>
          <div className="flex items-center gap-2">
            <label className="text-sm font-medium flex items-center gap-2 cursor-pointer">
              <input 
                type="checkbox" 
                checked={addCutline}
                onChange={(e) => setAddCutline(e.target.checked)}
                className="w-4 h-4 text-[var(--accent)] bg-gray-100 border-gray-300 rounded focus:ring-[var(--accent)] focus:ring-2"
              />
              <span>Cutline</span>
            </label>
          </div>
        </div>
      </header>
      
      {/* Main Form Section - Full Width */}
      <section className="mb-8">
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
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              {/* Left side - Original image with zoom and crop */}
              <div className="space-y-2">
                <h3 className="text-sm font-medium text-gray-300">Imaginea originală</h3>
                <div
                  className="relative rounded-lg overflow-hidden glass w-full"
                  style={{ 
                    aspectRatio: naturalSize ? `${naturalSize.width} / ${naturalSize.height}` : "4 / 3",
                    maxHeight: '600px'
                  }}
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
              </div>
              
              {/* Right side - Preview of what will be processed */}
              <div className="space-y-2">
                <h3 className="text-sm font-medium text-gray-300">
                  Imaginea care urmează să fie procesată
                </h3>
                {toSendPreviewUrl ? (
                  <div 
                    className="relative rounded-lg overflow-hidden glass w-full"
                    style={{ 
                      aspectRatio: naturalSize ? `${naturalSize.width} / ${naturalSize.height}` : "4 / 3",
                      maxHeight: '600px'
                    }}
                  >
                    <NextImage
                      src={toSendPreviewUrl}
                      alt="preview-to-process"
                      fill
                      unoptimized
                      className="object-contain select-none"
                      sizes="(max-width: 1024px) 100vw, 50vw"
                    />
                  </div>
                ) : (
                  <div 
                    className="relative rounded-lg overflow-hidden glass w-full flex items-center justify-center"
                    style={{ 
                      aspectRatio: naturalSize ? `${naturalSize.width} / ${naturalSize.height}` : "4 / 3",
                      maxHeight: '600px'
                    }}
                  >
                    <p className="text-gray-400 text-sm">
                      Faceți o selecție pentru a vedea previzualizarea
                    </p>
                  </div>
                )}
              </div>
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
          
          {/* Format Selection */}
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium mb-2">Format de printare</label>
              <select
                value={selectedFormat}
                onChange={(e) => setSelectedFormat(e.target.value)}
                className="w-full rounded-lg p-3 bg-white border border-gray-300 text-gray-800 hover:border-gray-400 focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-[var(--accent)]"
              >
                {Object.keys(commonFormats).map((format) => (
                  <option key={format} value={format}>
                    {format}
                    {format !== "Custom" && (
                      ` (${convertDimensions(commonFormats[format as keyof typeof commonFormats].width)} × ${convertDimensions(commonFormats[format as keyof typeof commonFormats].height)} ${globalUnit})`
                    )}
                  </option>
                ))}
              </select>
            </div>

            {/* Custom dimensions inputs */}
            {selectedFormat === "Custom" && (
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium mb-1">Lățime ({globalUnit})</label>
                  <input
                    type="number"
                    value={customWidth}
                    onChange={(e) => setCustomWidth(e.target.value)}
                    placeholder={`Lățime în ${globalUnit}`}
                    className="w-full rounded-lg p-2 bg-white border border-gray-300 text-gray-800 placeholder-gray-500 hover:border-gray-400 focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-[var(--accent)]"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium mb-1">Înălțime ({globalUnit})</label>
                  <input
                    type="number"
                    value={customHeight}
                    onChange={(e) => setCustomHeight(e.target.value)}
                    placeholder={`Înălțime în ${globalUnit}`}
                    className="w-full rounded-lg p-2 bg-white border border-gray-300 text-gray-800 placeholder-gray-500 hover:border-gray-400 focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-[var(--accent)]"
                  />
                </div>
              </div>
            )}

            {/* Format Preview Rectangle */}
            <div className="flex items-center justify-center p-4 bg-white/5 rounded-lg">
              <div className="flex flex-col items-center gap-2">
                <span className="text-xs text-gray-400">Previzualizare format</span>
                {(() => {
                  const dims = getCurrentFormatDimensions();
                  if (dims.width <= 0 || dims.height <= 0) return null;
                  
                  // Convert to mm for consistent scaling
                  const widthMm = globalUnit === "mm" ? dims.width : dims.width * 25.4;
                  const heightMm = globalUnit === "mm" ? dims.height : dims.height * 25.4;
                  
                  // Scale the preview rectangle to fit nicely
                  const maxSize = 120;
                  const aspectRatio = widthMm / heightMm;
                  let previewWidth, previewHeight;
                  
                  if (aspectRatio > 1) {
                    previewWidth = maxSize;
                    previewHeight = maxSize / aspectRatio;
                  } else {
                    previewHeight = maxSize;
                    previewWidth = maxSize * aspectRatio;
                  }
                  
                  return (
                    <div className="flex flex-col items-center gap-1">
                      <div 
                        className="border-2 border-[var(--accent)] bg-[var(--accent)]/10 rounded"
                        style={{
                          width: `${previewWidth}px`,
                          height: `${previewHeight}px`,
                          minWidth: '20px',
                          minHeight: '20px'
                        }}
                      />
                      <span className="text-xs text-gray-300">
                        {dims.width.toFixed(1)} × {dims.height.toFixed(1)} {globalUnit}
                      </span>
                    </div>
                  );
                })()}
              </div>
            </div>
          </div>
          
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={onProcess}
              className="btn-primary disabled:opacity-60 min-w-36 flex items-center justify-center gap-2"
              disabled={processingForPrint}
            >
              {processingForPrint ? (
                <>
                  <svg className="animate-spin h-5 w-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                  </svg>
                  Se procesează...
                </>
              ) : (
                'Procesează pentru print'
              )}
            </button>
          </div>

          <div className="mt-4 space-y-4">
            
            {/* DPI Quality Warning with Large Emoji */}
            {imageSrc && naturalSize && resizeDpi && (
              (() => {
                // Get dimensions from format selection
                const formatDims = getCurrentFormatDimensions();
                const w = formatDims.width;
                const h = formatDims.height;
                const d = parseInt(resizeDpi, 10);
                const unit = (globalUnit || "mm").trim().toLowerCase();
                
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
                  // Under 80% of target DPI - significant upscaling needed
                  return (
                    <div className="flex items-center justify-between p-4 rounded-lg border bg-blue-50 border-blue-200 text-blue-800">
                      <div className="flex-1">
                        <div className="font-bold text-lg mb-1">⚠️ Upscaling necesar</div>
                        <div className="text-sm space-y-1">
                          <div>DPI actual: {quality.effectiveDpi} → {d} DPI (după upscaling)</div>
                          <div>Rezoluție actuală: {currentWidth}×{currentHeight}px</div>
                          <div>Rezoluție finală: {quality.recommendedWidth}×{quality.recommendedHeight}px</div>
                          <div className="mt-2 font-medium">
                            ℹ️ Imaginea va fi mărită cu {Math.round((quality.recommendedWidth / currentWidth) * 100)}% pentru a respecta DPI-ul țintă.
                          </div>
                        </div>
                      </div>
                      <div className="text-6xl ml-4">⚠️</div>
                    </div>
                  );
                } else if (quality.isLowQuality) {
                  // 80-95% of target DPI - minor upscaling
                  return (
                    <div className="flex items-center justify-between p-4 rounded-lg border bg-blue-50 border-blue-200 text-blue-800">
                      <div className="flex-1">
                        <div className="font-bold text-lg mb-1">📐 Upscaling minor</div>
                        <div className="text-sm space-y-1">
                          <div>DPI actual: {quality.effectiveDpi} → {d} DPI (după upscaling)</div>
                          <div>Rezoluție actuală: {currentWidth}×{currentHeight}px</div>
                          <div>Rezoluție finală: {quality.recommendedWidth}×{quality.recommendedHeight}px</div>
                          <div className="mt-2 font-medium">
                            ✓ Imaginea va fi ajustată la rezoluția cerută ({Math.round((quality.effectiveDpi / d) * 100)}% din DPI țintă).
                          </div>
                        </div>
                      </div>
                      <div className="text-6xl ml-4">📐</div>
                    </div>
                  );
                } else {
                  // Over 95% of target DPI - little or no upscaling
                  return (
                    <div className="flex items-center justify-between p-4 rounded-lg border bg-green-50 border-green-200 text-green-800">
                      <div className="flex-1">
                        <div className="font-bold text-lg mb-1">✅ Rezoluție optimă</div>
                        <div className="text-sm">
                          <div>DPI actual: {quality.effectiveDpi} (țintă: {d}) - {Math.round((quality.effectiveDpi / d) * 100)}%</div>
                          <div>Rezoluție: {currentWidth}×{currentHeight}px</div>
                          <div className="mt-2 font-medium">✓ Imaginea are rezoluția perfectă pentru printare la {d} DPI!</div>
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
      </section>

      {/* AI Extension Options - Full Width Section */}
      {showingOptions && (
        <section className="mb-8" ref={aiExtensionRef}>
          <div className="card p-6">
            <h3 className="text-2xl font-semibold mb-3 text-[var(--accent)]">
              🎨 Selectează varianta dorită (AI Extension)
            </h3>
            <p className="text-base text-gray-300 mb-6">
              Algoritmul AI a generat variante cu diferite grade de suprapunere (overlap). 
              Click pe o variantă pentru a vedea masca de extindere (zona roșie). 
              Selectează varianta care arată cel mai natural.
            </p>
            
            {/* Progressive Loading Info */}
            {loadingExtensions && currentGeneratingIndex >= 0 && (
              <div className="mb-6 p-4 bg-blue-500/10 border border-blue-500/30 rounded-lg flex items-center gap-3">
                <svg className="animate-spin h-6 w-6 text-blue-400" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                <div>
                  <div className="font-medium text-blue-300">
                    Se generează varianta {availableOverlaps[currentGeneratingIndex]}%...
                  </div>
                  <div className="text-sm text-blue-400 mt-1">
                    Vă rugăm așteptați
                  </div>
                </div>
              </div>
            )}
            
            {/* Dynamic Cards Layout - Always Row */}
            {(() => {
              const overlapPercentages = [3, 5, 10, 15]; // Expected 4 cards
              const isAnyFullscreen = fullscreenCardIndex !== null;
              
              return (
                <div 
                  className="flex flex-row gap-4 mb-6"
                  style={{ 
                    transition: 'all 0.3s ease-in-out',
                    minHeight: isAnyFullscreen ? '700px' : '400px'
                  }}
                >
                  {overlapPercentages.map((overlapPct, index) => {
                    // Check if this card has loaded data
                    const option = extensionOptions.find(
                      opt => Math.abs(opt.overlap_percentage - overlapPct) < 0.01
                    );
                    const isLoaded = !!option;
                    const isExpanded = expandedCardIndex === index;
                    const isSelected = selectedOptionIndex === index;
                    const isFullscreen = fullscreenCardIndex === index;
                    const isHidden = isAnyFullscreen && !isFullscreen;
                    
                    return (
                      <div
                        key={`card-${overlapPct}-${index}`}
                        className={`relative rounded-xl transition-all duration-300 ease-in-out overflow-hidden ${
                          isLoaded 
                            ? 'cursor-pointer bg-white/5 backdrop-blur-sm'
                            : 'cursor-wait bg-white/5 backdrop-blur-sm'
                        } ${
                          isSelected && isLoaded
                            ? "border-[3px] border-[var(--accent)] shadow-lg shadow-[var(--accent)]/30"
                            : isLoaded 
                              ? "border-2 border-white/20 hover:border-white/30 shadow-md hover:shadow-lg"
                              : "border-2 border-dashed border-white/30"
                        } ${
                          isFullscreen
                            ? 'flex-[100]'
                            : isHidden
                              ? 'flex-[0] opacity-0 pointer-events-none'
                              : 'flex-1'
                        }`}
                        style={{
                          transition: 'all 0.4s cubic-bezier(0.4, 0, 0.2, 1)',
                          minHeight: isFullscreen ? '700px' : '400px',
                          boxShadow: isSelected && isLoaded
                            ? '0 10px 25px rgba(0, 0, 0, 0.3), 0 6px 10px rgba(0, 0, 0, 0.2)'
                            : isLoaded
                              ? '0 4px 12px rgba(0, 0, 0, 0.2), 0 2px 6px rgba(0, 0, 0, 0.1)'
                              : 'none'
                        }}
                        onClick={() => isLoaded && setSelectedOptionIndex(index)}
                      >
                        {isLoaded ? (
                          <>
                            {/* Selection Radio - Top Left */}
                            <div className="absolute top-3 left-3 z-20">
                              <div className={`w-7 h-7 rounded-full border-2 flex items-center justify-center transition-all shadow-lg ${
                                isSelected 
                                  ? 'bg-[var(--accent)] border-[var(--accent)]' 
                                  : 'bg-white/90 border-gray-400'
                              }`}>
                                {isSelected && (
                                  <svg className="w-5 h-5 text-white" fill="currentColor" viewBox="0 0 20 20">
                                    <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                                  </svg>
                                )}
                              </div>
                            </div>
                            
                            {/* Overlap Badge - Top Center */}
                            <div className="absolute top-3 left-1/2 transform -translate-x-1/2 z-10 bg-black/50 backdrop-blur-sm px-3 py-1 rounded-md">
                              <span className="text-white/90 font-medium text-xs">
                                Suprapunere {option.overlap_percentage}%
                              </span>
                            </div>
                            
                            {/* Expand/Collapse Button - Top Right */}
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                setFullscreenCardIndex(isFullscreen ? null : index);
                              }}
                              className="absolute top-3 right-3 z-20 bg-[var(--accent)] text-white p-2 rounded-lg hover:opacity-80 transition-opacity shadow-lg"
                              title={isFullscreen ? "Închide" : "Extinde"}
                            >
                              {isFullscreen ? (
                                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                                </svg>
                              ) : (
                                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4" />
                                </svg>
                              )}
                            </button>
                            
                            {/* Content Area - Always use flex-row for side-by-side layout */}
                            <div 
                              className="relative w-full h-full p-4 pt-12 flex flex-row gap-2 transition-all duration-400"
                            >
                              {/* Extended Image - Always visible */}
                              <div 
                                className="relative transition-all duration-400"
                                style={{
                                  width: isFullscreen ? '50%' : '100%',
                                  height: '100%',
                                  minHeight: '350px'
                                }}
                              >
                                <NextImage
                                  src={option.extended_image}
                                  alt={`Extended ${option.overlap_percentage}%`}
                                  fill
                                  unoptimized
                                  className="object-contain"
                                  sizes="(max-width: 768px) 100vw, 50vw"
                                />
                              </div>
                              
                              {/* Mask Preview - Shows on right when fullscreen */}
                              <div 
                                className="relative overflow-hidden transition-all duration-400"
                                style={{
                                  width: isFullscreen ? '50%' : '0%',
                                  height: '100%',
                                  minHeight: '350px',
                                  opacity: isFullscreen ? 1 : 0
                                }}
                              >
                                {isFullscreen && (
                                  <NextImage
                                    src={option.mask_preview}
                                    alt={`Mask ${option.overlap_percentage}%`}
                                    fill
                                    unoptimized
                                    className="object-contain"
                                    sizes="(max-width: 768px) 100vw, 50vw"
                                  />
                                )}
                              </div>
                            </div>
                          </>
                        ) : (
                          /* Placeholder - Not Generated Yet */
                          <div className="w-full h-full flex flex-col items-center justify-center p-6">
                            <div className="flex flex-col items-center gap-4">
                              {/* Show spinner if currently generating */}
                              {currentGeneratingIndex === index ? (
                                <>
                                  <svg className="animate-spin h-16 w-16 text-[var(--accent)]" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                                  </svg>
                                  <div className="text-center space-y-2">
                                    <div className="text-base font-medium text-[var(--accent)]">
                                      Se generează...
                                    </div>
                                    <div className="text-sm text-[var(--accent)]/80">
                                      Overlap {overlapPct}%
                                    </div>
                                  </div>
                                </>
                              ) : (
                                <>
                                  {/* Generate Next Button */}
                                  <div className="text-center space-y-4">
                                    <div className="text-lg font-medium text-white/70">
                                      Overlap {overlapPct}%
                                    </div>
                                    <div className="text-sm text-white/50 mb-4">
                                      Nu a fost încă generat
                                    </div>
                                    {/* Only show button if previous options are generated or if it's the first */}
                                    {(index === 0 || extensionOptions.length >= index) && !loadingExtensions && aiExtensionParams && (
                                      <button
                                        onClick={(e) => {
                                          e.stopPropagation();
                                          generateNextExtension(
                                            index,
                                            aiExtensionParams.isTwoStep 
                                              ? {
                                                  status: "needs_two_step_extension",
                                                  step1_params: aiExtensionParams.step1Params,
                                                  step2_params: aiExtensionParams.step2Params,
                                                  strategy: aiExtensionParams.strategy
                                                }
                                              : {
                                                  ai_extension_params: {
                                                    ...aiExtensionParams,
                                                    overlap_percentages: availableOverlaps
                                                  }
                                                },
                                            aiExtensionParams.fileToSend
                                          );
                                        }}
                                        className="px-6 py-3 rounded-lg font-medium bg-[var(--accent)] text-white hover:opacity-90 transition-opacity"
                                      >
                                        Generează varianta {overlapPct}%
                                      </button>
                                    )}
                                    {index > 0 && extensionOptions.length < index && (
                                      <div className="text-xs text-white/40">
                                        Generează mai întâi variantele anterioare
                                      </div>
                                    )}
                                  </div>
                                  {/* Skeleton placeholder */}
                                  <div className="w-32 h-32 bg-white/5 rounded-lg"></div>
                                </>
                              )}
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              );
            })()}
            
            {/* Continue Button - Available when at least one option is loaded */}
            {extensionOptions.length > 0 && (
              <button
                onClick={onSelectAndFinalize}
                disabled={processingForPrint || !extensionOptions[selectedOptionIndex]}
                className="w-full px-6 py-4 rounded-lg font-medium text-lg bg-[var(--accent)] text-white hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed transition-opacity flex items-center justify-center gap-2"
              >
                {processingForPrint ? (
                  <>
                    <svg className="animate-spin h-5 w-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                    Se finalizează procesarea...
                  </>
                ) : extensionOptions[selectedOptionIndex] ? (
                  `Continuă cu varianta ${extensionOptions[selectedOptionIndex].overlap_percentage}%`
                ) : (
                  'Selectează o variantă pentru a continua'
                )}
              </button>
            )}
          </div>
        </section>
      )}

      {/* Results Section - Full Width */}
      <section className="mb-8">
        <div className="card p-6">
          <h2 className="text-xl font-semibold mb-4">
            Rezultatul analizei/procesării
          </h2>

          {/* Processed result should appear here */}
          {processedUrl && (
            <div className="mb-6">
              <h3 className="text-lg font-medium mb-3 text-[var(--accent)]">Rezultatul în format PDF</h3>
              {processedType === 'application/pdf' ? (
                <div className="w-full rounded border border-white/10 overflow-hidden">
                  <iframe 
                    title="processed-pdf" 
                    src={processedUrl} 
                    className="w-full rounded" 
                    style={{ height: '80vh', minHeight: '600px' }}
                  />
                </div>
              ) : (
                <div className="relative w-full rounded border border-white/10" style={{ aspectRatio: "4 / 3" }}>
                  <NextImage
                    src={processedUrl}
                    alt="processed"
                    fill
                    unoptimized
                    className="object-contain rounded"
                    sizes="100vw"
                  />
                </div>
              )}
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
                    
                    // Generate meaningful filename
                    const originalName = file?.name || 'image';
                    const nameWithoutExt = originalName.replace(/\.[^/.]+$/, '');
                    const strategy = debugInfo.strategy || 'processed';
                    const overlap = debugInfo.selectedOverlap || '';
                    const filename = overlap 
                      ? `${nameWithoutExt}_${strategy}_${overlap}percent.pdf`
                      : `${nameWithoutExt}_${strategy}.pdf`;
                    
                    // If already a PDF, download directly
                    if (processedType === 'application/pdf') {
                      const a = document.createElement('a');
                      a.href = processedUrl;
                      a.download = filename;
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
                    a.download = filename;
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
          
          {/* Debug Information Dropdown */}
          {Object.keys(debugInfo).length > 0 && (
            <div className="mt-6 border border-white/10 rounded-lg">
              <button
                type="button"
                onClick={() => setShowDebug(!showDebug)}
                className="w-full flex items-center justify-between p-4 text-left hover:bg-white/5 transition-colors rounded-lg"
              >
                <span className="font-semibold text-lg">
                  🐛 Debug Information
                </span>
                <svg
                  className={`w-5 h-5 transition-transform ${
                    showDebug ? "rotate-180" : ""
                  }`}
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M19 9l-7 7-7-7"
                  />
                </svg>
              </button>
              
              {showDebug && (
                <div className="p-4 space-y-6 border-t border-white/10">
                  {/* Dimensions Section */}
                  <div className="space-y-3">
                    <h4 className="font-bold text-[var(--accent)] text-sm uppercase tracking-wide">
                      📐 Dimensions
                    </h4>
                    
                    {debugInfo.currentImageDims && (
                      <div className="pl-4 space-y-1 text-sm">
                        <p className="text-gray-300">
                          <span className="font-medium">Original Image:</span>{" "}
                          {debugInfo.currentImageDims.width} × {
                            debugInfo.currentImageDims.height
                          } px
                        </p>
                      </div>
                    )}
                    
                    {debugInfo.croppedImageDims && (
                      <div className="pl-4 space-y-1 text-sm">
                        <p className="text-gray-300">
                          <span className="font-medium">Cropped Image:</span>{" "}
                          {debugInfo.croppedImageDims.width} × {
                            debugInfo.croppedImageDims.height
                          } px
                        </p>
                      </div>
                    )}
                    
                    {debugInfo.desiredDims && (
                      <div className="pl-4 space-y-1 text-sm">
                        <p className="text-gray-300">
                          <span className="font-medium">Target Dimensions:</span>{" "}
                          {debugInfo.desiredDims.width.toFixed(2)} × {
                            debugInfo.desiredDims.height.toFixed(2)
                          } {debugInfo.desiredDims.unit}
                        </p>
                      </div>
                    )}
                    
                    {debugInfo.desiredPixels && (
                      <div className="pl-4 space-y-1 text-sm">
                        <p className="text-gray-300">
                          <span className="font-medium">Target Pixels:</span>{" "}
                          {debugInfo.desiredPixels.width} × {
                            debugInfo.desiredPixels.height
                          } px
                        </p>
                      </div>
                    )}
                  </div>
                  
                  {/* Ratios Section */}
                  <div className="space-y-3">
                    <h4 className="font-bold text-[var(--accent)] text-sm uppercase tracking-wide">
                      📊 Aspect Ratios
                    </h4>
                    
                    {debugInfo.currentRatio && (
                      <div className="pl-4 space-y-1 text-sm">
                        <p className="text-gray-300">
                          <span className="font-medium">Current Ratio:</span>{" "}
                          {debugInfo.currentRatio.toFixed(4)} {
                            debugInfo.currentRatio > 1 
                              ? "(Landscape)" 
                              : debugInfo.currentRatio < 1 
                                ? "(Portrait)" 
                                : "(Square)"
                          }
                        </p>
                      </div>
                    )}
                    
                    {debugInfo.desiredRatio && (
                      <div className="pl-4 space-y-1 text-sm">
                        <p className="text-gray-300">
                          <span className="font-medium">Desired Ratio:</span>{" "}
                          {debugInfo.desiredRatio.toFixed(4)} {
                            debugInfo.desiredRatio > 1 
                              ? "(Landscape)" 
                              : debugInfo.desiredRatio < 1 
                                ? "(Portrait)" 
                                : "(Square)"
                          }
                        </p>
                      </div>
                    )}
                  </div>
                  
                  {/* Processing Strategy */}
                  {debugInfo.strategy && (
                    <div className="space-y-3">
                      <h4 className="font-bold text-[var(--accent)] text-sm \
uppercase tracking-wide">
                        🎯 Extension Strategy
                      </h4>
                      <div className="pl-4 space-y-1 text-sm">
                        <p className="text-gray-300 font-mono bg-white/5 p-2 \
rounded border border-white/10">
                          {debugInfo.strategy}
                        </p>
                        {debugInfo.selectedOverlap && (
                          <p className="text-gray-300 mt-2">
                            <span className="font-medium">
                              Selected Overlap:
                            </span>{" "}
                            {debugInfo.selectedOverlap}%
                          </p>
                        )}
                      </div>
                    </div>
                  )}
                  
                  {/* Scaling & DPI */}
                  <div className="space-y-3">
                    <h4 className="font-bold text-[var(--accent)] text-sm \
uppercase tracking-wide">
                      🔬 Scaling & Quality
                    </h4>
                    
                    {debugInfo.scalingFactor && (
                      <div className="pl-4 space-y-1 text-sm">
                        <p className="text-gray-300">
                          <span className="font-medium">Scaling Factor:</span>{" "}
                          {debugInfo.scalingFactor.toFixed(4)}x
                        </p>
                      </div>
                    )}
                    
                    {debugInfo.effectiveDpi && debugInfo.targetDpi && (
                      <div className="pl-4 space-y-1 text-sm">
                        <p className="text-gray-300">
                          <span className="font-medium">Effective DPI:</span>{" "}
                          {debugInfo.effectiveDpi} / {debugInfo.targetDpi} {
                            " "}
                          ({Math.round(
                            (debugInfo.effectiveDpi / debugInfo.targetDpi) * 100
                          )}%)
                        </p>
                      </div>
                    )}
                    
                    {debugInfo.bleedPx && (
                      <div className="pl-4 space-y-1 text-sm">
                        <p className="text-gray-300">
                          <span className="font-medium">Bleed:</span>{" "}
                          {debugInfo.bleedPx} px ({bleedSize} mm)
                        </p>
                      </div>
                    )}
                  </div>
                  
                  {/* Intermediary Images */}
                  {debugInfo.intermediaryImages && 
                   debugInfo.intermediaryImages.length > 0 && (
                    <div className="space-y-3">
                      <h4 className="font-bold text-[var(--accent)] text-sm uppercase tracking-wide">
                        🖼️ Intermediary Images
                      </h4>
                      <div className="space-y-4">
                        {debugInfo.intermediaryImages.map((img, idx) => (
                          <div key={idx} className="pl-4 space-y-2">
                            <p className="text-sm font-medium text-gray-200">
                              {img.name}
                              {img.dimensions && (
                                <span className="text-gray-400 ml-2">
                                  ({img.dimensions.width} × {
                                    img.dimensions.height
                                  } px)
                                </span>
                              )}
                            </p>
                            <div 
                              className="relative w-full rounded border border-white/10" 
                              style={{ aspectRatio: "4 / 3" }}
                            >
                              <NextImage
                                src={img.url}
                                alt={img.name}
                                fill
                                unoptimized
                                className="object-contain rounded"
                                sizes="(max-width: 1024px) 100vw, 50vw"
                              />
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}