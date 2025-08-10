from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel
from PIL import Image, ImageDraw
from io import BytesIO
import base64
import logging
import os
from openai import OpenAI
from dotenv import load_dotenv, find_dotenv
from pathlib import Path
import fitz  # PyMuPDF

class AnalysisResponse(BaseModel):
    result: str


app = FastAPI(title="Print Analyzer API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root():
    return {"message": "Hello from FastAPI!"}

@app.get("/health")
def health_check():
    return {"status": "healthy"}



# Configure logging early
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("print-analyzer")

# Discover and load .env, then log the resolved path
_resolved_env = find_dotenv(".env.local")
if not _resolved_env:
    fallback = Path(__file__).resolve().parent / ".env"
    if fallback.exists():
        _resolved_env = str(fallback)

if _resolved_env:
    # Use utf-8-sig to tolerate BOM in files saved with a BOM on Windows
    load_dotenv(_resolved_env, override=True, encoding="utf-8-sig")
logger.info(f"dotenv loaded from: {_resolved_env or 'not found'}")
# Log OPENAI_API_KEY presence (masked) to help diagnose env issues
_k = os.getenv("OPENAI_API_KEY")
if _k:
    logger.info(
        "OPENAI_API_KEY detected: length=%s, prefix=%s***",
        len(_k),
        _k[:4],
    )




def encode_image_from_pil(pil_image: Image.Image) -> str:
    """Encode a PIL image to base64 PNG data string."""
    buffered = BytesIO()
    pil_image.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode("utf-8")


def analyze_image_with_openai(pil_image: Image.Image, use_case: str) -> str:
    """Advanced print analysis using OpenAI Vision (Responses API)."""

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set in environment.")

    width, height = pil_image.size
    aspect_ratio = (width / height) if height else 0
    orientation = (
        "landscape" if width > height else "portrait" if height > width else "square"
    )

    client = OpenAI(api_key=api_key)
    b64_image = encode_image_from_pil(pil_image)

    analysis_prompt = f"""
You are a professional print expert analyzing an image for print production.
Please analyze this image for the following use case: {use_case}

Image specifications:
- Dimensions: {width}×{height}px
- Aspect ratio: {aspect_ratio:.2f}
- Orientation: {orientation}

Please analyze and provide specific feedback on these key areas:

1. FORMAT SUITABILITY: Resolution for intended print size, aspect ratio fit, overall quality
2. TEXT ANALYSIS: Presence/readability of text, font size/clarity concerns
3. OBJECT COMPOSITION: Multiple objects? Should elements be separated? Complexity
4. POSITIONING & CENTERING: Subject centering and composition balance for print
5. BLEED REQUIREMENTS: Need for bleed, recommended amount (mm), cutting type (rectangular or complex)

Provide clear, actionable recommendations for optimal print results.
"""

    response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user", 
                    "content": [
                        {"type": "text", "text": analysis_prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{b64_image}",
                                "detail": "high"
                            }
                        }
                    ]
                }
            ],
            max_tokens=1500,
            temperature=0.1
        )

    return response.choices[0].message.content


@app.post("/analyze", response_model=AnalysisResponse)
async def analyze_endpoint(
    file: UploadFile = File(...),
    use_case: str = Form(...),
):
    if file.content_type not in ("image/jpeg", "image/png", "image/jpg"):
        raise HTTPException(status_code=400, detail="Unsupported file type")

    raw = await file.read()
    try:
        image = Image.open(BytesIO(raw)).convert("RGB")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid image data")

    try:
        result_text = analyze_image_with_openai(image, use_case)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return AnalysisResponse(result=result_text)


@app.post("/analyze_pdf", response_model=AnalysisResponse)
async def analyze_pdf_endpoint(
    file: UploadFile = File(...),
    use_case: str = Form(""),
):
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Unsupported file type; expected application/pdf")

    raw = await file.read()
    try:
        # Render first page of PDF to an image using PyMuPDF
        pdf = fitz.open(stream=raw, filetype="pdf")
        if pdf.page_count == 0:
            raise HTTPException(status_code=400, detail="Empty PDF")
        page = pdf.load_page(0)
        # Use a matrix to render at higher DPI for better analysis
        zoom = 2.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        mode = "RGB" if pix.n < 4 else "RGBA"
        pil_image = Image.frombytes(mode, (pix.width, pix.height), pix.samples)
        if pil_image.mode != "RGB":
            pil_image = pil_image.convert("RGB")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid PDF: {exc}")

    try:
        result_text = analyze_image_with_openai(pil_image, use_case or "PDF page analysis")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return AnalysisResponse(result=result_text)


@app.post("/remove_background")
async def remove_background_endpoint(file: UploadFile = File(None)):
    # Placeholder endpoint – to be implemented
    return {"message": "Will be implemented soon"}


@app.post("/process")
async def process_image_endpoint(
    file: UploadFile = File(...),
    bleed_px: int = Form(30),
):
    """
    Add a content-aware bleed (mirror padding) and draw square cutting lines.

    - bleed_px: padding size in pixels to add on each side.
    Returns a PNG image.
    """
    if file.content_type not in ("image/jpeg", "image/png", "image/jpg"):
        raise HTTPException(status_code=400, detail="Unsupported file type")

    raw = await file.read()
    try:
        pil_image = Image.open(BytesIO(raw)).convert("RGB")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid image data")

    try:
        # Mirror bleed using pure Pillow (no OpenCV)
        pad = max(0, int(bleed_px))
        w, h = pil_image.size

        # Create expanded canvas
        expanded = Image.new("RGB", (w + 2 * pad, h + 2 * pad))
        expanded.paste(pil_image, (pad, pad))

        if pad > 0:
            # Left and right bands (mirror horizontally)
            left_band = pil_image.crop((0, 0, pad, h)).transpose(Image.FLIP_LEFT_RIGHT)
            right_band = pil_image.crop((w - pad, 0, w, h)).transpose(Image.FLIP_LEFT_RIGHT)
            expanded.paste(left_band, (0, pad))
            expanded.paste(right_band, (pad + w, pad))

            # Top and bottom bands (mirror vertically)
            top_band = pil_image.crop((0, 0, w, pad)).transpose(Image.FLIP_TOP_BOTTOM)
            bottom_band = pil_image.crop((0, h - pad, w, h)).transpose(Image.FLIP_TOP_BOTTOM)
            expanded.paste(top_band, (pad, 0))
            expanded.paste(bottom_band, (pad, pad + h))

            # Corners (double reflection ~ rotate 180)
            tl = pil_image.crop((0, 0, pad, pad)).transpose(Image.ROTATE_180)
            tr = pil_image.crop((w - pad, 0, w, pad)).transpose(Image.ROTATE_180)
            bl = pil_image.crop((0, h - pad, pad, h)).transpose(Image.ROTATE_180)
            br = pil_image.crop((w - pad, h - pad, w, h)).transpose(Image.ROTATE_180)
            expanded.paste(tl, (0, 0))
            expanded.paste(tr, (pad + w, 0))
            expanded.paste(bl, (0, pad + h))
            expanded.paste(br, (pad + w, pad + h))

        # Draw cutting rectangle (green)
        draw = ImageDraw.Draw(expanded)
        rect = (pad, pad, pad + w - 1, pad + h - 1)
        draw.rectangle(rect, outline=(60, 235, 120), width=2)

        buf = BytesIO()
        expanded.save(buf, format="PNG")
        png_bytes = buf.getvalue()
        return Response(content=png_bytes, media_type="image/png")
    except Exception as exc:
        logger.exception("processing failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


