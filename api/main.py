from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, JSONResponse
from io import BytesIO
import base64
import logging
import os
from dotenv import load_dotenv, find_dotenv
from pathlib import Path
import fitz
from PIL import Image, ImageDraw
from pydantic import BaseModel
from gradio_client import Client, handle_file
import tempfile
from openai import OpenAI
from concurrent.futures import ThreadPoolExecutor, as_completed
import uuid

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

prefix = "/api"


@app.get(f"{prefix}/health")
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


# ============================================================================
# UTILITY FUNCTIONS FROM utils.py
# ============================================================================

def calculate_desired_bleed_in_pixels(
    bleed_inch: float, 
    desired_ppi: float
) -> int:
    """Calculate bleed in pixels from inches and PPI."""
    bleed_px = int(bleed_inch * desired_ppi)
    return bleed_px


def calculate_desired_pixels(
    desired_x_inch: float, 
    desired_y_inch: float, 
    desired_ppi: float
) -> tuple[int, int, float]:
    """Calculate desired dimensions in pixels and aspect ratio."""
    desired_x_px = int(desired_x_inch * desired_ppi)
    desired_y_px = int(desired_y_inch * desired_ppi)
    desired_ratio = desired_x_px / desired_y_px
    return desired_x_px, desired_y_px, desired_ratio


def image_to_CMYK(image: Image.Image) -> Image.Image:
    """Convert an image to CMYK color space."""
    return image.convert("CMYK")


def read_image_dimensions_and_ratio(
    image: Image.Image
) -> tuple[int, int, float]:
    """Read image dimensions and aspect ratio."""
    width, height = image.size
    aspect_ratio = width / height
    return width, height, aspect_ratio


def calculate_constrained_dimensions(
    desired_ratio: float, 
    min_dimension: int = 720, 
    max_dimension: int = 1536,
    tolerance: float = 0.01
) -> tuple[int, int]:
    """
    Calculate dimensions matching desired ratio within tool constraints.
    Favors dimensions near middle of range for balanced resolution.
    """
    best_match = None
    best_error = float('inf')
    target_dimension = (min_dimension + max_dimension) / 2
    best_distance_from_target = float('inf')
    
    for width in range(min_dimension, max_dimension + 1):
        ideal_height = width / desired_ratio
        
        for height in [int(ideal_height), int(ideal_height) + 1]:
            if min_dimension <= height <= max_dimension:
                actual_ratio = width / height
                error = abs(actual_ratio - desired_ratio)
                
                if error <= tolerance:
                    avg_dimension = (width + height) / 2
                    distance_from_target = abs(avg_dimension - \
                                                target_dimension)
                    
                    if distance_from_target < best_distance_from_target or \
                       (distance_from_target == best_distance_from_target \
                        and error < best_error):
                        best_error = error
                        best_match = (width, height)
                        best_distance_from_target = distance_from_target
                elif error < best_error:
                    best_error = error
                    if best_match is None:
                        best_match = (width, height)
    
    if best_match is None:
        raise ValueError(
            f"Cannot achieve ratio {desired_ratio:.3f} within "
            f"constraints [{min_dimension}, {max_dimension}]"
        )
    
    if best_error > tolerance:
        achieved_ratio = best_match[0] / best_match[1]
        raise ValueError(
            f"Cannot achieve ratio {desired_ratio:.3f} within tolerance "
            f"{tolerance}. Best match: {best_match[0]}x{best_match[1]} "
            f"(ratio: {achieved_ratio:.3f}, error: {best_error:.3f})"
        )
    
    return best_match


def determine_scaling_factor(
    desired_x_px: int, 
    desired_y_px: int, 
    actual_x_px: int, 
    actual_y_px: int
) -> float:
    """Determine scaling factor based on desired and actual dimensions."""
    scale_x = desired_x_px / actual_x_px
    scale_y = desired_y_px / actual_y_px
    return max(scale_x, scale_y)


def determine_extension_strategy(
    current_ratio: float, 
    desired_ratio: float
) -> str:
    """Determine strategy for extending image to desired ratio."""
    if desired_ratio > 2.133:
        raise ValueError("Desired ratio exceeds maximum limit of 2.133")
    elif desired_ratio < 0.4687:
        raise ValueError("Desired ratio is below minimum limit of 0.4687")
        
    if 2.133 > desired_ratio > 1:
        if 2.133 > current_ratio > 1:
            if current_ratio < desired_ratio:
                strategy = "landscape_extend_width"
            elif current_ratio > desired_ratio:
                strategy = "landscape_extend_height"
            else:
                strategy = "no_extension_needed"
        elif current_ratio < 1:
            strategy = "portrait_to_square_to_landscape"
        else:
            strategy = "square_to_landscape"
    elif 0.4687 < desired_ratio < 1:
        if current_ratio < 1:
            if current_ratio > desired_ratio:
                strategy = "portrait_extend_height"
            elif current_ratio < desired_ratio:
                strategy = "portrait_extend_width"
            else:
                strategy = "no_extension_needed"
        elif current_ratio > 1:
            strategy = "landscape_to_square_to_portrait"
        else:
            strategy = "square_to_portrait"
    else:
        if current_ratio > 1:
            strategy = "landscape_to_square"
        elif current_ratio < 1:
            strategy = "portrait_to_square"
        else:
            strategy = "no_extension_needed"
    return strategy


def ai_image_extension(
    image_path: str, 
    target_width: int, 
    target_height: int, 
    overlap_horizontally: bool, 
    overlap_vertically: bool, 
    overlap_percentage: int
) -> tuple[str, str]:
    """Extend image using AI to target dimensions."""
    num_inference_steps = 12
    prompt = "seamless continuation"
    alignment = "Middle"
    overlap_left = overlap_right = overlap_top = overlap_bottom = False
    
    if overlap_vertically:
        overlap_top = overlap_bottom = True
    if overlap_horizontally:
        overlap_left = overlap_right = True
    
    logger.info(
        f"AI Extension: target={target_width}x{target_height}, "
        f"overlap_h={overlap_horizontally}, overlap_v={overlap_vertically}"
    )
    
    client = Client("https://8end7ai6stn3cs-7860.proxy.runpod.net/")
    
    result = client.predict(
        image=handle_file(image_path),
        width=target_width,
        height=target_height,
        overlap_percentage=overlap_percentage,
        num_inference_steps=num_inference_steps,
        resize_option="Full",
        custom_resize_percentage=100,
        prompt_input=prompt,
        alignment=alignment,
        overlap_left=overlap_left,
        overlap_right=overlap_right,
        overlap_top=overlap_top,
        overlap_bottom=overlap_bottom,
        api_name="/infer"
    )
    
    # Note: Gradio client downloads both image and mask (2 HTTP requests)
    logger.info("AI Extension complete - downloaded image and mask")
    return (result[1], result[0])  # (image_path, mask_path)


def extend_image_with_ai(
    image_path: str,
    strategy: str,
    actual_x_px: int, 
    actual_y_px: int, 
    desired_ratio: float
) -> tuple[str, str]:
    """Execute AI extension based on determined strategy."""
    if not (0.4687 < desired_ratio < 2.1333):
        raise ValueError(
            "Desired ratio out of acceptable range (0.4687 to 2.1333)"
        )
    
    if strategy == "no_extension_needed":
        logger.info(f"No extension needed: {actual_x_px}x{actual_y_px}")
        return (image_path, None)
    
    # Landscape adjustments (same orientation)
    if strategy == "landscape_extend_width":
        # Extending width = add to left/right = horizontal overlap
        recommended_x, recommended_y = calculate_constrained_dimensions(
            desired_ratio
        )
        overlap_h, overlap_v = True, False
    elif strategy == "landscape_extend_height":
        # Extending height = add to top/bottom = vertical overlap
        recommended_x, recommended_y = calculate_constrained_dimensions(
            desired_ratio
        )
        overlap_h, overlap_v = False, True
    
    # Portrait adjustments (same orientation)
    elif strategy == "portrait_extend_width":
        # Extending width = add to left/right = horizontal overlap
        recommended_x, recommended_y = calculate_constrained_dimensions(
            desired_ratio
        )
        overlap_h, overlap_v = True, False
    elif strategy == "portrait_extend_height":
        # Extending height = add to top/bottom = vertical overlap
        recommended_x, recommended_y = calculate_constrained_dimensions(
            desired_ratio
        )
        overlap_h, overlap_v = False, True
    
    # Square conversions (single step)
    elif strategy == "landscape_to_square":
        # Landscape to square: extend vertically (top/bottom)
        recommended_x, recommended_y = 1024, 1024
        overlap_h, overlap_v = False, True
    elif strategy == "portrait_to_square":
        # Portrait to square: extend horizontally (left/right)
        recommended_x, recommended_y = 1024, 1024
        overlap_h, overlap_v = True, False
    elif strategy == "square_to_landscape":
        # Square to landscape: extend horizontally (left/right)
        recommended_x, recommended_y = calculate_constrained_dimensions(
            desired_ratio
        )
        overlap_h, overlap_v = True, False
    elif strategy == "square_to_portrait":
        # Square to portrait: extend vertically (top/bottom)
        recommended_x, recommended_y = calculate_constrained_dimensions(
            desired_ratio
        )
        overlap_h, overlap_v = False, True
    
    # Two-step conversions
    elif strategy == "portrait_to_square_to_landscape":
        logger.info(
            f"Two-step conversion: {actual_x_px}x{actual_y_px} "
            f"-> 1024x1024 -> target landscape"
        )
        # Step 1: Portrait to square (extend horizontally)
        logger.info("Step 1/2: Extending portrait to square (1024x1024)")
        square_img, _ = ai_image_extension(
            image_path, 1024, 1024, True, False, 10
        )
        # Step 2: Square to landscape (extend horizontally)
        recommended_x, recommended_y = calculate_constrained_dimensions(
            desired_ratio
        )
        overlap_h, overlap_v = True, False
        logger.info(
            f"Step 2/2: Extending square to landscape "
            f"({recommended_x}x{recommended_y})"
        )
        return ai_image_extension(
            square_img, recommended_x, recommended_y, overlap_h, overlap_v, 10
        )
    elif strategy == "landscape_to_square_to_portrait":
        logger.info(
            f"Two-step conversion: {actual_x_px}x{actual_y_px} "
            f"-> 1024x1024 -> target portrait"
        )
        # Step 1: Landscape to square (extend vertically)
        logger.info("Step 1/2: Extending landscape to square (1024x1024)")
        square_img, _ = ai_image_extension(
            image_path, 1024, 1024, False, True, 10
        )
        # Step 2: Square to portrait (extend vertically)
        recommended_x, recommended_y = calculate_constrained_dimensions(
            desired_ratio
        )
        overlap_h, overlap_v = False, True
        logger.info(
            f"Step 2/2: Extending square to portrait "
            f"({recommended_x}x{recommended_y})"
        )
        return ai_image_extension(
            square_img, recommended_x, recommended_y, overlap_h, overlap_v, 10
        )
    else:
        # Fallback: should never reach here if strategy is correct
        raise ValueError(f"Unknown extension strategy: {strategy}")
    
    logger.info(
        f"Extending: {actual_x_px}x{actual_y_px} -> "
        f"{recommended_x}x{recommended_y}"
    )
    return ai_image_extension(
        image_path, recommended_x, recommended_y, overlap_h, overlap_v, 10
    )


def add_desired_mirror_bleed(
    image: Image.Image, 
    bleed_px: int
) -> tuple[Image.Image, int, int, int, int]:
    """Add bleed using mirror technique for seamless blending."""
    if bleed_px <= 0:
        w, h = image.size
        return image, 0, 0, w, h
        
    pad = bleed_px
    w, h = image.size
    
    expanded = Image.new(image.mode, (w + 2 * pad, h + 2 * pad))
    expanded.paste(image, (pad, pad))
    
    # Mirror edges
    left_band = image.crop((0, 0, min(pad, w), h)) \
                     .transpose(Image.FLIP_LEFT_RIGHT)
    right_band = image.crop((max(0, w - pad), 0, w, h)) \
                      .transpose(Image.FLIP_LEFT_RIGHT)
    expanded.paste(left_band, (0, pad))
    expanded.paste(right_band, (pad + w, pad))
    
    top_band = image.crop((0, 0, w, min(pad, h))) \
                    .transpose(Image.FLIP_TOP_BOTTOM)
    bottom_band = image.crop((0, max(0, h - pad), w, h)) \
                       .transpose(Image.FLIP_TOP_BOTTOM)
    expanded.paste(top_band, (pad, 0))
    expanded.paste(bottom_band, (pad, pad + h))
    
    # Mirror corners
    corner_size = min(pad, w, h)
    tl = image.crop((0, 0, corner_size, corner_size)) \
              .transpose(Image.ROTATE_180)
    tr = image.crop((max(0, w - corner_size), 0, w, corner_size)) \
              .transpose(Image.ROTATE_180)
    bl = image.crop((0, max(0, h - corner_size), corner_size, h)) \
              .transpose(Image.ROTATE_180)
    br = image.crop((max(0, w - corner_size), max(0, h - corner_size), \
                     w, h)).transpose(Image.ROTATE_180)
    expanded.paste(tl, (0, 0))
    expanded.paste(tr, (pad + w, 0))
    expanded.paste(bl, (0, pad + h))
    expanded.paste(br, (pad + w, pad + h))
    
    x1, y1 = pad, pad
    x2, y2 = pad + w, pad + h
    
    return expanded, x1, y1, x2, y2


def upscale_with_LANCZOS(
    image: Image.Image, 
    scaling_factor: float
) -> Image.Image:
    """Upscale image using LANCZOS filter."""
    new_width = int(image.width * scaling_factor)
    new_height = int(image.height * scaling_factor)
    return image.resize((new_width, new_height), Image.LANCZOS)


def add_cutline(
    doc: fitz.Document, 
    rect: tuple, 
    spot_name: str = "CutContour",
    alt_cmyk: tuple = (0.3, 0.5, 1, 0),
    page_num: int = 0, 
    hairline: bool = True, 
    stroke_width: float = 0.5
) -> fitz.Document:
    """Add rectangle cutline (spot color stroke) to PDF page."""
    page = doc[page_num]
    page_xref = page.xref

    # Create Separation object for spot color
    sep_obj = (
        f"[ /Separation /{spot_name} /DeviceCMYK "
        f"<< /FunctionType 2 /Domain [0 1] /C0 [0 0 0 0] "
        f"/C1 [{' '.join(map(str, alt_cmyk))}] /N 1 >> ]"
    )
    sep_xref = doc.get_new_xref()
    doc.update_object(sep_xref, sep_obj)

    # Ensure /Resources exists
    res_key = doc.xref_get_key(page_xref, "Resources")[1]
    if not res_key:
        res_xref = doc.get_new_xref()
        doc.update_object(res_xref, "<<>>")
        doc.xref_set_key(page_xref, "Resources", f"{res_xref} 0 R")
    else:
        if res_key.endswith(" R"):
            res_xref = int(res_key.split()[0])
        else:
            res_xref = doc.get_new_xref()
            doc.update_object(res_xref, res_key)
            doc.xref_set_key(page_xref, "Resources", f"{res_xref} 0 R")

    # Ensure /ColorSpace includes /CS1
    cs_key = doc.xref_get_key(res_xref, "ColorSpace")[1]
    if not cs_key:
        cs_xref = doc.get_new_xref()
        doc.update_object(cs_xref, f"<< /CS1 {sep_xref} 0 R >>")
        doc.xref_set_key(res_xref, "ColorSpace", f"{cs_xref} 0 R")
    else:
        if cs_key.endswith(" R"):
            cs_xref = int(cs_key.split()[0])
            current = doc.xref_object(cs_xref)
            if "obj" in current:
                current = current[current.find("<<"):current.rfind(">>")+2]
            if "/CS1" not in current:
                updated = current[:-2] + f" /CS1 {sep_xref} 0 R >>"
                doc.update_object(cs_xref, updated)
        else:
            cs_xref = doc.get_new_xref()
            base = cs_key.strip()
            if base.endswith(">>"):
                updated = base[:-2] + f" /CS1 {sep_xref} 0 R >>"
            else:
                updated = f"<< /CS1 {sep_xref} 0 R >>"
            doc.update_object(cs_xref, updated)
            doc.xref_set_key(res_xref, "ColorSpace", f"{cs_xref} 0 R")

    # Build rectangle content
    x0, y0, x1, y1 = rect
    w = 0 if hairline else stroke_width
    content = (
        "q\n"
        f"{w} w\n"
        "/CS1 CS\n"
        "1 SCN\n"
        f"{x0} {y0} {x1 - x0} {y1 - y0} re\n"
        "S\n"
        "Q\n"
    ).encode("ascii")

    # Add stream
    stream_xref = doc.get_new_xref()
    doc.update_object(stream_xref, "<<>>")
    doc.update_stream(stream_xref, content)

    cont_key = doc.xref_get_key(page_xref, "Contents")[1]
    if not cont_key:
        doc.xref_set_key(page_xref, "Contents", f"{stream_xref} 0 R")
    else:
        if cont_key.endswith(" R"):
            old_xref = int(cont_key.split()[0])
            arr_xref = doc.get_new_xref()
            doc.update_object(
                arr_xref, 
                f"[ {old_xref} 0 R {stream_xref} 0 R ]"
            )
            doc.xref_set_key(page_xref, "Contents", f"{arr_xref} 0 R")
        elif cont_key.strip().startswith("["):
            arr = cont_key.strip()
            updated = arr[:-1] + f" {stream_xref} 0 R ]"
            arr_xref = doc.get_new_xref()
            doc.update_object(arr_xref, updated)
            doc.xref_set_key(page_xref, "Contents", f"{arr_xref} 0 R")
        else:
            old_xref = doc.get_new_xref()
            doc.update_object(old_xref, "<<>>")
            doc.update_stream(old_xref, cont_key.encode("latin1"))
            arr_xref = doc.get_new_xref()
            doc.update_object(
                arr_xref, 
                f"[ {old_xref} 0 R {stream_xref} 0 R ]"
            )
            doc.xref_set_key(page_xref, "Contents", f"{arr_xref} 0 R")

    return doc


def image_to_pdf_with_dimensions(
    image: Image.Image, 
    dpi: int
) -> fitz.Document:
    """Convert PIL image to PDF document with proper DPI."""
    with BytesIO() as img_buffer:
        image.save(img_buffer, format="JPEG")
        img_bytes = img_buffer.getvalue()
    
    # Calculate dimensions in points (72 points per inch)
    width_pts = (image.width / dpi) * 72
    height_pts = (image.height / dpi) * 72
    
    pdf_doc = fitz.open()
    page = pdf_doc.new_page(width=width_pts, height=height_pts)
    page.insert_image(
        fitz.Rect(0, 0, width_pts, height_pts), 
        stream=img_bytes
    )
    return pdf_doc
# ============================================================================
# MASK HELPERS
# ============================================================================
def prepare_image_and_mask(
    image: Image.Image,
    width: int,
    height: int,
    overlap_percentage: int,
    resize_option: str,
    custom_resize_percentage: int,
    alignment: str,
    overlap_left: bool,
    overlap_right: bool,
    overlap_top: bool,
    overlap_bottom: bool
) -> tuple[Image.Image, Image.Image]:
    """Prepare image and mask for AI extension preview."""
    target_size = (width, height)

    # Calculate the scaling factor to fit the image within the target size
    scale_factor = min(target_size[0] / image.width, \
                       target_size[1] / image.height)
    new_width = int(image.width * scale_factor)
    new_height = int(image.height * scale_factor)
    
    # Resize the source image to fit within target size
    source = image.resize((new_width, new_height), Image.LANCZOS)

    # Apply resize option using percentages
    if resize_option == "Full":
        resize_percentage = 100
    elif resize_option == "50%":
        resize_percentage = 50
    elif resize_option == "33%":
        resize_percentage = 33
    elif resize_option == "25%":
        resize_percentage = 25
    else:  # Custom
        resize_percentage = custom_resize_percentage

    # Calculate new dimensions based on percentage
    resize_factor = resize_percentage / 100
    new_width = int(source.width * resize_factor)
    new_height = int(source.height * resize_factor)

    # Ensure minimum size of 64 pixels
    new_width = max(new_width, 64)
    new_height = max(new_height, 64)

    # Resize the image
    source = source.resize((new_width, new_height), Image.LANCZOS)

    # Calculate the overlap in pixels based on the percentage
    overlap_x = int(new_width * (overlap_percentage / 100))
    overlap_y = int(new_height * (overlap_percentage / 100))

    # Ensure minimum overlap of 1 pixel
    overlap_x = max(overlap_x, 1)
    overlap_y = max(overlap_y, 1)

    # Calculate margins based on alignment
    if alignment == "Middle":
        margin_x = (target_size[0] - new_width) // 2
        margin_y = (target_size[1] - new_height) // 2
    elif alignment == "Left":
        margin_x = 0
        margin_y = (target_size[1] - new_height) // 2
    elif alignment == "Right":
        margin_x = target_size[0] - new_width
        margin_y = (target_size[1] - new_height) // 2
    elif alignment == "Top":
        margin_x = (target_size[0] - new_width) // 2
        margin_y = 0
    elif alignment == "Bottom":
        margin_x = (target_size[0] - new_width) // 2
        margin_y = target_size[1] - new_height

    # Adjust margins to eliminate gaps
    margin_x = max(0, min(margin_x, target_size[0] - new_width))
    margin_y = max(0, min(margin_y, target_size[1] - new_height))

    # Create a new background image and paste the resized source image
    background = Image.new('RGB', target_size, (255, 255, 255))
    background.paste(source, (margin_x, margin_y))

    # Create the mask
    mask = Image.new('L', target_size, 255)
    mask_draw = ImageDraw.Draw(mask)

    # Calculate overlap areas
    white_gaps_patch = 2

    left_overlap = margin_x + overlap_x if overlap_left else \
        margin_x + white_gaps_patch
    right_overlap = margin_x + new_width - overlap_x if overlap_right else \
        margin_x + new_width - white_gaps_patch
    top_overlap = margin_y + overlap_y if overlap_top else \
        margin_y + white_gaps_patch
    bottom_overlap = margin_y + new_height - overlap_y if overlap_bottom else \
        margin_y + new_height - white_gaps_patch
    
    if alignment == "Left":
        left_overlap = margin_x + overlap_x if overlap_left else margin_x
    elif alignment == "Right":
        right_overlap = margin_x + new_width - overlap_x if overlap_right \
            else margin_x + new_width
    elif alignment == "Top":
        top_overlap = margin_y + overlap_y if overlap_top else margin_y
    elif alignment == "Bottom":
        bottom_overlap = margin_y + new_height - overlap_y if overlap_bottom \
            else margin_y + new_height

    # Draw the mask
    mask_draw.rectangle([
        (left_overlap, top_overlap),
        (right_overlap, bottom_overlap)
    ], fill=0)

    return background, mask


def preview_image_and_mask(
    image: Image.Image,
    width: int,
    height: int,
    overlap_percentage: int,
    resize_option: str,
    custom_resize_percentage: int,
    alignment: str,
    overlap_left: bool,
    overlap_right: bool,
    overlap_top: bool,
    overlap_bottom: bool
) -> Image.Image:
    """Create preview image showing the mask overlay."""
    background, mask = prepare_image_and_mask(
        image, width, height, overlap_percentage, resize_option,
        custom_resize_percentage, alignment, overlap_left,
        overlap_right, overlap_top, overlap_bottom
    )
    
    # Create a preview image showing the mask
    preview = background.copy().convert('RGBA')
    
    # Create a semi-transparent red overlay (25% opacity)
    red_overlay = Image.new('RGBA', background.size, (255, 0, 0, 64))
    
    # Convert black pixels in the mask to semi-transparent red
    red_mask = Image.new('RGBA', background.size, (0, 0, 0, 0))
    red_mask.paste(red_overlay, (0, 0), mask)
    
    # Overlay the red mask on the background
    preview = Image.alpha_composite(preview, red_mask)
    
    return preview




# ============================================================================
# ENDPOINTS
# ============================================================================


@app.post(f"{prefix}/process_for_print")
async def process_for_print_endpoint(
    file: UploadFile = File(...),
    target_width: float = Form(...),
    target_height: float = Form(...),
    unit: str = Form("mm"),
    dpi: int = Form(300),
    add_bleed: bool = Form(True),
    bleed_mm: float = Form(3.0),
):
    """
    Complete workflow for print production.
    
    Workflow (frontend handles PDF conversion + cropping first):
    1. Frontend: Upload PDF → Convert to image via /pdf_to_image
    2. Frontend: User crops the image (or uses full image)
    3. Frontend: Send cropped image to this endpoint
    4. Backend: Calculate desired dimensions, ratio, scaling factor
    5. Backend: Determine extension strategy
    6. Backend: Extend image with AI if needed
    7. Backend: Add mirror bleed (if enabled)
    8. Backend: Upscale image to final dimensions
    9. Backend: Convert to PDF with cutline
    10. Backend: Return downloadable PDF
    
    Args:
        file: Image file ONLY (PNG/JPEG) - PDFs already converted by frontend
        target_width: Target width (in mm or inches)
        target_height: Target height (in mm or inches)
        unit: "mm" or "inch"
        dpi: Target DPI (default 300)
        add_bleed: Whether to add bleed (default True)
        bleed_mm: Bleed size in mm (default 3.0)
        
    Returns:
        PDF with bleed and cutline
    """
    # Only accept images - PDFs are converted by frontend first
    if file.content_type not in ("image/jpeg", "image/png", "image/jpg"):
        raise HTTPException(
            400, 
            "Only images accepted. PDFs must be converted via /pdf_to_image first"
        )

    # Validate inputs
    if target_width <= 0 or target_height <= 0 or dpi <= 0:
        raise HTTPException(400, "Dimensions and DPI must be positive")
    
    unit = unit.strip().lower()
    if unit not in ("mm", "inch", "in", "inches"):
        raise HTTPException(400, "Unit must be mm or inch")

    # Convert to mm for consistency
    if unit == "mm":
        target_width = target_width / 25.4
        target_height = target_height / 25.4

    raw = await file.read()
    
    try:
        # Step 1: Load image (already converted from PDF if needed)
        pil_image = Image.open(BytesIO(raw)).convert("RGB")
        
        # Step 3: Calculate desired dimensions and ratios
        desired_x_px, desired_y_px, desired_ratio = \
            calculate_desired_pixels(
                target_width, target_height, dpi
            )
        logger.info(
            f"Desired: {desired_x_px}x{desired_y_px}px "
            f"(ratio {desired_ratio:.3f})"
        )
        
        actual_x_px, actual_y_px, actual_ratio = \
            read_image_dimensions_and_ratio(pil_image)
        logger.info(
            f"Actual: {actual_x_px}x{actual_y_px}px "
            f"(ratio {actual_ratio:.3f})"
        )
        if actual_ratio > 1:
            logger.info("Orientation: Landscape")
        elif actual_ratio < 1:
            logger.info("Orientation: Portrait")
        else:
            logger.info("Orientation: Square")
        # Calculate bleed in pixels
        bleed_px = 0
        if add_bleed:
            bleed_px = calculate_desired_bleed_in_pixels(
                bleed_inch=bleed_mm / 25.4, desired_ppi=dpi
            )
        logger.info(f"Bleed: {bleed_px}px")
        
        # Step 4 & 5: Determine strategy and extend if needed
        strategy = determine_extension_strategy(actual_ratio, desired_ratio)
        logger.info(f"Extension strategy: {strategy}")
        
        
        if strategy != "no_extension_needed":
            # Save temp file for AI extension
            with tempfile.NamedTemporaryFile(
                suffix=".jpeg", delete=False
            ) as tmp:
                pil_image.save(tmp, format="JPEG")
                tmp_path = tmp.name
            
            try:
                # Step 6: Extend with AI
                extended_img_path, mask_path = extend_image_with_ai(
                    tmp_path, strategy, 
                    actual_x_px, actual_y_px, desired_ratio
                )
                pil_image = Image.open(extended_img_path).convert("RGB")
                logger.info(
                    f"AI extended to {pil_image.width}x{pil_image.height}px"
                )
            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
        
        # Update dimensions after extension
        current_w, current_h = pil_image.size
        
        # Step 7: Add mirror bleed (before upscaling)
        trim_x1, trim_y1, trim_x2, trim_y2 = 0, 0, current_w, current_h
        
        if add_bleed and bleed_px > 0:
            pil_image, trim_x1, trim_y1, trim_x2, trim_y2 = \
                add_desired_mirror_bleed(pil_image, bleed_px)
            logger.info(
                f"Added {bleed_px}px bleed. "
                f"New size: {pil_image.width}x{pil_image.height}px, "
                f"Trim box: ({trim_x1},{trim_y1})-({trim_x2},{trim_y2})"
            )
        
        # Step 8: Upscale to final dimensions
        # Target includes bleed
        final_width_px = desired_x_px + (2 * bleed_px if add_bleed else 0)
        final_height_px = desired_y_px + (2 * bleed_px if add_bleed else 0)
        
        scale_factor = determine_scaling_factor(
            final_width_px, final_height_px,
            pil_image.width, pil_image.height
        )
        
        if scale_factor != 1.0:
            pil_image = upscale_with_LANCZOS(pil_image, scale_factor)
            # Update trim box coordinates
            trim_x1 = int(trim_x1 * scale_factor)
            trim_y1 = int(trim_y1 * scale_factor)
            trim_x2 = int(trim_x2 * scale_factor)
            trim_y2 = int(trim_y2 * scale_factor)
            logger.info(
                f"Upscaled by {scale_factor:.3f}x to "
                f"{pil_image.width}x{pil_image.height}px"
            )
        
        # Step 9: Convert to PDF
        pdf_doc = image_to_pdf_with_dimensions(pil_image, dpi)
        
        # Step 10: Add cutline at trim box
        if add_bleed:
            # Convert trim box to PDF points
            width_pts = (pil_image.width / dpi) * 72
            height_pts = (pil_image.height / dpi) * 72
            trim_x1_pts = (trim_x1 / dpi) * 72
            trim_y1_pts = (trim_y1 / dpi) * 72
            trim_x2_pts = (trim_x2 / dpi) * 72
            trim_y2_pts = (trim_y2 / dpi) * 72
            
            trim_rect = (trim_x1_pts, trim_y1_pts, trim_x2_pts, trim_y2_pts)
            pdf_doc = add_cutline(pdf_doc, trim_rect, "CutContour")
            logger.info(f"Added cutline at {trim_rect}")
        
        # Step 11: Return PDF
        pdf_bytes = pdf_doc.tobytes()
        pdf_doc.close()
        
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": \
                    'attachment; filename="print_ready.pdf"'
            }
        )
        
    except ValueError as e:
        logger.error(f"ValueError: {e}")
        raise HTTPException(400, str(e))
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(f"Processing failed: {exc}")
        raise HTTPException(500, f"Processing failed: {str(exc)}")



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


@app.post(f"{prefix}/analyze", response_model=AnalysisResponse)
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


@app.post(f"{prefix}/remove_background")
async def remove_background_endpoint(file: UploadFile = File(None)):
    # Placeholder endpoint – to be implemented
    return {"message": "Will be implemented soon"}




@app.post(f"{prefix}/resize")
async def resize_image_endpoint(
    file: UploadFile = File(...),
    width: float = Form(...),
    height: float = Form(...),
    dpi: int = Form(...),
    unit: str = Form("mm"),
):
    """Resize an image to target physical dimensions at a given DPI.

    - width/height: physical size (in mm or inch based on `unit`)
    - dpi: dots per inch
    Returns PNG image of computed pixel size.
    """
    if file.content_type not in ("image/jpeg", "image/png", "image/jpg"):
        raise HTTPException(status_code=400, detail="Unsupported file type")

    if width <= 0 or height <= 0 or dpi <= 0:
        raise HTTPException(status_code=400, detail="width, height and dpi must be positive")

    try:
        raw = await file.read()
        pil = Image.open(BytesIO(raw)).convert("RGB")
        u = (unit or "mm").strip().lower()
        if u not in ("mm", "inch", "in", "inches"):
            raise HTTPException(status_code=400, detail="unit must be mm or inch")
        if u == "mm":
            width_in = width / 25.4
            height_in = height / 25.4
        else:
            width_in = width
            height_in = height

        target_w = max(1, int(round(width_in * dpi)))
        target_h = max(1, int(round(height_in * dpi)))

        resized = pil.resize((target_w, target_h), Image.Resampling.LANCZOS)
        buf = BytesIO()
        resized.save(buf, format="PNG")
        return Response(content=buf.getvalue(), media_type="image/png")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("resize failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post(f"{prefix}/extend_image")
async def extend_image_endpoint(
    file: UploadFile = File(...),
    target_width: int = Form(...),
    target_height: int = Form(...),
    prompt: str = Form("seamless continuation"),
    overlap_percentage: int = Form(50),
    num_inference_steps: int = Form(20),
):
    """
    Extend an image using AI to reach target dimensions.
    Useful when aspect ratio conversion is needed (landscape to portrait or vice versa).
    
    Args:
        file: Image file to extend (jpeg/png)
        target_width: Target width in pixels
        target_height: Target height in pixels
        prompt: Description to guide AI extension (default: "high quality, professional, seamless")
        overlap_percentage: How much to overlap when extending (default: 50, range: 10-90)
        num_inference_steps: Quality of AI generation (default: 20, higher = better quality but slower)
        
    Returns:
        Extended image as PNG
    """
    if file.content_type not in ("image/jpeg", "image/png", "image/jpg"):
        raise HTTPException(status_code=400, detail="Unsupported file type; expected image/jpeg or image/png")

    if target_width <= 0 or target_height <= 0:
        raise HTTPException(status_code=400, detail="Target dimensions must be positive")
    
    if overlap_percentage < 10 or overlap_percentage > 90:
        raise HTTPException(status_code=400, detail="Overlap percentage must be between 10 and 90")
    
    if num_inference_steps < 1 or num_inference_steps > 50:
        raise HTTPException(status_code=400, detail="Number of inference steps must be between 1 and 50")

    try:
        raw = await file.read()
        pil_image = Image.open(BytesIO(raw)).convert("RGB")
        
        current_w, current_h = pil_image.size
        current_ratio = current_w / current_h
        target_ratio = target_width / target_height
        
        logger.info(f"Extending image from {current_w}x{current_h}px (ratio {current_ratio:.2f}) to {target_width}x{target_height}px (ratio {target_ratio:.2f})")
        
        # Check if extension is actually needed
        ratio_difference = abs(current_ratio - target_ratio)
        if ratio_difference < 0.05:  # Less than 5% difference
            logger.info("Aspect ratios are very similar. Just resizing without AI extension.")
            resized = pil_image.resize((target_width, target_height), Image.Resampling.LANCZOS)
            buf = BytesIO()
            resized.save(buf, format="PNG")
            return Response(content=buf.getvalue(), media_type="image/png")
        
        # Save to temp file for Gradio client
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            pil_image.save(tmp, format="PNG")
            temp_input_path = tmp.name
        
        try:
            # Determine which sides to extend
            # Only use relevant overlaps: horizontal OR vertical, not both
            alignment = "Middle"
            
            if current_ratio < target_ratio:
                # Need to extend width (portrait → landscape or square → landscape)
                # Horizontal extension only
                overlap_left = True
                overlap_right = True
                overlap_top = False
                overlap_bottom = False
                logger.info("Extending horizontally (left and right only)")
            elif current_ratio > target_ratio:
                # Need to extend height (landscape → portrait or square → portrait)
                # Vertical extension only
                overlap_left = False
                overlap_right = False
                overlap_top = True
                overlap_bottom = True
                logger.info("Extending vertically (top and bottom only)")
            else:
                # Same ratio, shouldn't reach here due to earlier check
                overlap_left = False
                overlap_right = False
                overlap_top = False
                overlap_bottom = False
            
            # Connect to AI service
            logger.info("Connecting to AI image extension service...")
            client = Client("https://4udlwa02add62f-7860.proxy.runpod.net/")
            
            logger.info(f"Starting AI extension with prompt: '{prompt}'")
            result = client.predict(
                image=handle_file(temp_input_path),
                width=target_width,
                height=target_height,
                overlap_percentage=overlap_percentage,
                num_inference_steps=num_inference_steps,
                resize_option="Full",
                custom_resize_percentage=100,
                prompt_input=prompt,
                alignment=alignment,
                overlap_left=overlap_left,
                overlap_right=overlap_right,
                overlap_top=overlap_top,
                overlap_bottom=overlap_bottom,
                api_name="/infer"
            )
            
            # Result is tuple of (cnet_image, generated_image)
            if isinstance(result, (list, tuple)) and len(result) >= 2:
                extended_image_path = result[1]  # The final generated image
                logger.info(f"AI extension completed: {extended_image_path}")
                
                # Load and return the extended image
                extended_image = Image.open(extended_image_path).convert("RGB")
                buf = BytesIO()
                extended_image.save(buf, format="PNG")
                
                return Response(content=buf.getvalue(), media_type="image/png")
            else:
                logger.warning(f"Unexpected result format from AI service: {type(result)}")
                raise HTTPException(status_code=500, detail="Unexpected response from AI service")
                
        finally:
            # Clean up temp input file
            if os.path.exists(temp_input_path):
                os.unlink(temp_input_path)
        
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("AI image extension failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"AI extension error: {str(exc)}")


@app.post(f"{prefix}/add_bleed")
async def add_bleed_endpoint(
    file: UploadFile = File(...),
    bleed_mm: float = Form(3.0),
    dpi: int = Form(300),
):
    """
    Add mirror bleed to an image.
    
    Args:
        file: Image file (jpeg/png)
        bleed_mm: Bleed size in millimeters (default: 3.0)
        dpi: DPI to calculate pixel size (default: 300)
        
    Returns:
        Image with bleed added as PNG
    """
    if file.content_type not in ("image/jpeg", "image/png", "image/jpg"):
        raise HTTPException(status_code=400, detail="Unsupported file type; expected image/jpeg or image/png")

    if bleed_mm < 0:
        raise HTTPException(status_code=400, detail="Bleed must be non-negative")
    
    if dpi <= 0:
        raise HTTPException(status_code=400, detail="DPI must be positive")

    try:
        raw = await file.read()
        pil_image = Image.open(BytesIO(raw)).convert("RGB")
        
        logger.info(f"Adding {bleed_mm}mm bleed at {dpi} DPI to {pil_image.size[0]}x{pil_image.size[1]}px image")
        
        # Add mirror bleed
        pil_image_with_bleed = add_mirror_bleed(pil_image, bleed_mm, dpi)
        
        logger.info(f"Bleed added. New size: {pil_image_with_bleed.size[0]}x{pil_image_with_bleed.size[1]}px")
        
        # Return as PNG
        buf = BytesIO()
        pil_image_with_bleed.save(buf, format="PNG")
        return Response(content=buf.getvalue(), media_type="image/png")
        
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Add bleed failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Add bleed error: {str(exc)}")


@app.post(f"{prefix}/upscale_to_dpi")
async def upscale_to_dpi_endpoint(
    file: UploadFile = File(...),
    target_width: float = Form(...),
    target_height: float = Form(...),
    unit: str = Form("mm"),
    dpi: int = Form(300),
):
    """
    Upscale image to exact dimensions at target DPI.
    
    Args:
        file: Image file (jpeg/png)
        target_width: Target width in mm or inches
        target_height: Target height in mm or inches
        unit: "mm" or "inch" (default: mm)
        dpi: Target DPI (default: 300)
        
    Returns:
        Upscaled image as PNG
    """
    if file.content_type not in ("image/jpeg", "image/png", "image/jpg"):
        raise HTTPException(status_code=400, detail="Unsupported file type; expected image/jpeg or image/png")

    if target_width <= 0 or target_height <= 0:
        raise HTTPException(status_code=400, detail="Dimensions must be positive")
    
    if dpi <= 0:
        raise HTTPException(status_code=400, detail="DPI must be positive")
    
    unit = unit.strip().lower()
    if unit not in ("mm", "inch", "in", "inches"):
        raise HTTPException(status_code=400, detail="Unit must be mm or inch")

    try:
        raw = await file.read()
        pil_image = Image.open(BytesIO(raw)).convert("RGB")
        
        # Convert to mm for consistency
        if unit in ("inch", "in", "inches"):
            target_width_mm = target_width * 25.4
            target_height_mm = target_height * 25.4
        else:
            target_width_mm = target_width
            target_height_mm = target_height
        
        logger.info(f"Upscaling from {pil_image.size[0]}x{pil_image.size[1]}px to {target_width_mm}x{target_height_mm}mm at {dpi} DPI")
        
        # Upscale to target DPI
        upscaled_image = upscale_to_target_dpi(pil_image, target_width_mm, target_height_mm, dpi)
        
        logger.info(f"Upscaled to {upscaled_image.size[0]}x{upscaled_image.size[1]}px")
        
        # Return as PNG
        buf = BytesIO()
        upscaled_image.save(buf, format="PNG")
        return Response(content=buf.getvalue(), media_type="image/png")
        
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Upscale to DPI failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Upscale error: {str(exc)}")


@app.post(f"{prefix}/add_cutline_to_pdf")
async def add_cutline_to_pdf_endpoint(
    file: UploadFile = File(...),
    bleed_mm: float = Form(3.0),
    dpi: int = Form(300),
):
    """
    Convert image to PDF and add CutContour spot color cutline.
    
    Args:
        file: Image file (jpeg/png) - should already have bleed added
        bleed_mm: Bleed size in mm (for calculating cutline position, default: 3.0)
        dpi: DPI for point conversion (default: 300)
        
    Returns:
        PDF with CutContour spot color cutline
    """
    if file.content_type not in ("image/jpeg", "image/png", "image/jpg"):
        raise HTTPException(status_code=400, detail="Unsupported file type; expected image/jpeg or image/png")

    if bleed_mm < 0:
        raise HTTPException(status_code=400, detail="Bleed must be non-negative")
    
    if dpi <= 0:
        raise HTTPException(status_code=400, detail="DPI must be positive")

    try:
        raw = await file.read()
        pil_image = Image.open(BytesIO(raw)).convert("RGB")
        
        logger.info(f"Converting {pil_image.size[0]}x{pil_image.size[1]}px image to PDF with cutline at {bleed_mm}mm bleed")
        
        # Convert to PDF with cutline
        pdf_bytes = image_to_pdf_with_cutline(pil_image, bleed_mm, dpi)
        
        logger.info("PDF with CutContour cutline generated successfully")
        
        return Response(content=pdf_bytes, media_type="application/pdf")
        
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Add cutline to PDF failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Add cutline error: {str(exc)}")


@app.post(f"{prefix}/pdf_to_image")
async def pdf_to_image_endpoint(
    file: UploadFile = File(...),
):
    """Convert the first page of a PDF to a PNG image and return it."""
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Unsupported file type; expected application/pdf")

    try:
        raw = await file.read()
        # Render first page of PDF to image using PyMuPDF
        pdf_doc = fitz.open(stream=raw, filetype="pdf")
        if pdf_doc.page_count == 0:
            raise HTTPException(status_code=400, detail="Empty PDF")
        page = pdf_doc.load_page(0)
        # Use a higher zoom for better quality
        zoom = 2.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        mode = "RGB" if pix.n < 4 else "RGBA"
        pil_image = Image.frombytes(mode, (pix.width, pix.height), pix.samples)
        if pil_image.mode != "RGB":
            pil_image = pil_image.convert("RGB")
        
        # Convert to PNG
        buf = BytesIO()
        pil_image.save(buf, format="PNG")
        return Response(content=buf.getvalue(), media_type="image/png")
    except Exception as exc:
        logger.exception("pdf_to_image failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post(f"{prefix}/image_to_pdf")
async def image_to_pdf_endpoint(
    file: UploadFile = File(...),
):
    """Convert an uploaded image (PNG/JPEG) to a single-page PDF and return it."""
    if file.content_type not in ("image/jpeg", "image/png", "image/jpg"):
        raise HTTPException(status_code=400, detail="Unsupported file type; expected image/jpeg or image/png")

    try:
        raw = await file.read()
        pil = Image.open(BytesIO(raw)).convert("RGB")
        buf = BytesIO()
        pil.save(buf, format="PDF")
        return Response(content=buf.getvalue(), media_type="application/pdf")
    except Exception as exc:
        logger.exception("image_to_pdf failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
    
    

@app.post(f"{prefix}/read_pdf_with_fitz")
async def read_pdf_with_fitz_endpoint(
    file: UploadFile = File(...),
):
    """Read a PDF file using PyMuPDF and return it."""
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Unsupported file type; expected application/pdf")
    
    raw = await file.read()
    try:
        read_pdf_with_fitz(raw)
        return Response("Successfully read PDF with PyMuPDF")
    except Exception as exc:
        logger.exception("read_pdf_with_fitz failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
    

def read_pdf_with_fitz(bytes_data):
    try:
        pdf = fitz.open(stream=bytes_data, filetype="pdf")
        
        return pdf
    except Exception as exc:
        logger.exception("read_pdf_with_fitz failed: %s", exc)
        raise exc


def ai_extension_parallel_overlaps(
    image_path: str,
    target_width: int,
    target_height: int,
    overlap_horizontally: bool,
    overlap_vertically: bool,
    overlap_percentages: list[int] = [3, 5, 10, 15]
) -> list[dict]:
    """
    Run AI extension in parallel with multiple overlap percentages.
    Returns list of results with extended images and mask previews.
    """
    logger.info(
        f"Running parallel AI extensions with overlaps: {overlap_percentages}"
    )
    
    # Load original image for mask preview generation
    orig_image = Image.open(image_path)
    
    # Prepare overlap flags for mask preview
    overlap_left = overlap_right = False
    overlap_top = overlap_bottom = False
    if overlap_vertically:
        overlap_top = overlap_bottom = True
    if overlap_horizontally:
        overlap_left = overlap_right = True
    
    # Run AI extensions in parallel using ThreadPoolExecutor
    results = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {}
        for overlap_pct in overlap_percentages:
            logger.info(f"Submitting AI extension task for {overlap_pct}% overlap")
            future = executor.submit(
                ai_image_extension,
                image_path,
                target_width,
                target_height,
                overlap_horizontally,
                overlap_vertically,
                overlap_pct
            )
            futures[future] = overlap_pct
        
        logger.info(f"Submitted {len(futures)} AI extension tasks. Waiting for completion...")
        
        # Collect results using as_completed for better tracking
        for future in as_completed(futures):
            overlap_pct = futures[future]
            try:
                logger.info(f"Processing result for {overlap_pct}% overlap...")
                extended_path, mask_path = future.result(timeout=120)
                
                logger.info(f"AI extension succeeded for {overlap_pct}%, generating mask preview...")
                
                # Generate mask preview
                mask_preview = preview_image_and_mask(
                    orig_image,
                    target_width,
                    target_height,
                    overlap_pct,
                    "Full",
                    100,
                    "Middle",
                    overlap_left,
                    overlap_right,
                    overlap_top,
                    overlap_bottom
                )
                
                # Save mask preview to temp file
                mask_preview_path = extended_path.replace(
                    ".webp", 
                    f"_mask_preview.png"
                )
                mask_preview.save(mask_preview_path, "PNG")
                
                results.append({
                    "overlap_percentage": overlap_pct,
                    "extended_image_path": extended_path,
                    "mask_path": mask_path,
                    "mask_preview_path": mask_preview_path
                })
                
                logger.info(
                    f"✓ Completed AI extension with {overlap_pct}% overlap "
                    f"({len(results)}/{len(overlap_percentages)})"
                )
            except Exception as e:
                logger.error(
                    f"✗ FAILED AI extension with {overlap_pct}% overlap: {e}",
                    exc_info=True
                )
    
    # Sort results by overlap percentage for consistency
    results.sort(key=lambda x: x["overlap_percentage"])
    
    logger.info(f"Completed {len(results)} parallel AI extensions")
    return results


@app.post(f"{prefix}/ai_extend_with_mask")
async def ai_extend_with_mask_endpoint(
    file: UploadFile = File(...),
    target_width: int = Form(...),
    target_height: int = Form(...),
    overlap_percentage: int = Form(10),
    overlap_horizontally: bool = Form(False),
    overlap_vertically: bool = Form(False),
):
    """
    AI extend an image with mask preview generation.
    
    Single-responsibility endpoint for AI extension.
    Returns extended image and mask preview as base64 data URLs.
    
    Args:
        file: Image file to extend
        target_width: Target width in pixels
        target_height: Target height in pixels  
        overlap_percentage: Overlap percentage (5-20)
        overlap_horizontally: Extend left/right
        overlap_vertically: Extend top/bottom
        
    Returns:
        JSON with extended_image and mask_preview as base64 data URLs
    """
    if file.content_type not in ("image/jpeg", "image/png", "image/jpg"):
        raise HTTPException(
            status_code=400,
            detail="Only image files accepted"
        )
    
    if overlap_percentage < 1 or overlap_percentage > 20:
        raise HTTPException(
            status_code=400,
            detail="Overlap percentage must be between 1 and 20"
        )
    
    try:
        raw = await file.read()
        pil_image = Image.open(BytesIO(raw)).convert("RGB")
        
        # Save to temp file for AI extension
        temp_dir = tempfile.mkdtemp()
        temp_path = os.path.join(temp_dir, f"input_{uuid.uuid4()}.png")
        pil_image.save(temp_path, "PNG")
        
        logger.info(
            f"AI extending to {target_width}x{target_height}px "
            f"with {overlap_percentage}% overlap "
            f"(h={overlap_horizontally}, v={overlap_vertically})"
        )
        
        # Call AI extension
        extended_path, mask_path = ai_image_extension(
            temp_path,
            target_width,
            target_height,
            overlap_horizontally,
            overlap_vertically,
            overlap_percentage
        )
        
        # Generate mask preview
        overlap_left = overlap_right = overlap_horizontally
        overlap_top = overlap_bottom = overlap_vertically
        
        mask_preview = preview_image_and_mask(
            pil_image,
            target_width,
            target_height,
            overlap_percentage,
            "Full",
            100,
            "Middle",
            overlap_left,
            overlap_right,
            overlap_top,
            overlap_bottom
        )
        
        # Convert to RGB and encode extended image
        ext_img = Image.open(extended_path).convert("RGB")
        ext_img_b64 = encode_image_from_pil(ext_img)
        
        # Encode mask preview
        mask_prev_b64 = encode_image_from_pil(mask_preview)
        
        logger.info(
            f"✓ AI extension complete for {overlap_percentage}% overlap"
        )
        
        return JSONResponse(content={
            "status": "success",
            "overlap_percentage": overlap_percentage,
            "extended_image": f"data:image/png;base64,{ext_img_b64}",
            "mask_preview": f"data:image/png;base64,{mask_prev_b64}",
            "temp_path": extended_path
        })
        
    except Exception as exc:
        logger.exception(f"AI extension failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@app.post(f"{prefix}/process_for_print_step1")
async def process_for_print_step1_endpoint(
    file: UploadFile = File(...),
    target_width: float = Form(...),
    target_height: float = Form(...),
    unit: str = Form("mm"),
    dpi: int = Form(300),
):
    """
    Step 1: Calculate strategy and return extension parameters.
    
    Does NOT perform AI extension - just returns the parameters needed.
    Frontend will call /ai_extend_with_mask endpoint 4 times in parallel.
    """
    # Only accept images
    if file.content_type not in ("image/jpeg", "image/png", "image/jpg"):
        raise HTTPException(
            status_code=400,
            detail="Only image files are accepted. Convert PDFs via " \
                   "/pdf_to_image first."
        )

    # Validate inputs
    if target_width <= 0 or target_height <= 0 or dpi <= 0:
        raise HTTPException(status_code=400, detail="Invalid dimensions/DPI")
    
    unit = unit.strip().lower()
    if unit not in ("mm", "inch", "in", "inches"):
        raise HTTPException(status_code=400, detail="Unit must be mm or inch")

    # Convert to mm
    if unit == "mm":
        target_width_mm = target_width
        target_height_mm = target_height
    else:
        target_width_mm = target_width * 25.4
        target_height_mm = target_height * 25.4

    raw = await file.read()
    
    try:
        pil_image = Image.open(BytesIO(raw)).convert("RGB")
        actual_x_px, actual_y_px, current_ratio = \
            read_image_dimensions_and_ratio(pil_image)
        
        # Calculate desired dimensions
        desired_x_inch = target_width_mm / 25.4
        desired_y_inch = target_height_mm / 25.4
        desired_x_px, desired_y_px, desired_ratio = \
            calculate_desired_pixels(desired_x_inch, desired_y_inch, dpi)
        
        # Determine extension strategy
        strategy = determine_extension_strategy(current_ratio, desired_ratio)
        logger.info(f"Strategy: {strategy}")
        
        # If no extension needed, return early
        if strategy == "no_extension_needed":
            return JSONResponse(content={
                "status": "no_extension_needed",
                "message": "Image already matches desired aspect ratio",
                "strategy": strategy,
                "current_ratio": current_ratio,
                "desired_ratio": desired_ratio
            })
        
        # Determine target dimensions and overlap directions for AI
        # Check if this is a two-step strategy
        is_two_step = strategy in [
            "portrait_to_square_to_landscape",
            "landscape_to_square_to_portrait"
        ]
        
        if is_two_step:
            # Two-step strategies require intermediate square conversion
            logger.info(f"Two-step strategy detected: {strategy}")
            
            # Step 1: Convert to square (1024x1024)
            if strategy == "portrait_to_square_to_landscape":
                step1_params = (1024, 1024, True, False)  # Extend horizontally
            else:  # landscape_to_square_to_portrait
                step1_params = (1024, 1024, False, True)  # Extend vertically
            
            # Step 2: Convert square to final ratio
            rec_x, rec_y = calculate_constrained_dimensions(desired_ratio)
            if strategy == "portrait_to_square_to_landscape":
                step2_params = (rec_x, rec_y, True, False)  # Extend horizontally
            else:  # landscape_to_square_to_portrait
                step2_params = (rec_x, rec_y, False, True)  # Extend vertically
            
            logger.info(
                f"Two-step parameters: "
                f"Step1={step1_params[0]}x{step1_params[1]}, "
                f"Step2={step2_params[0]}x{step2_params[1]}"
            )
            
            return JSONResponse(content={
                "status": "needs_two_step_extension",
                "strategy": strategy,
                "current_ratio": current_ratio,
                "desired_ratio": desired_ratio,
                "target_dimensions_px": {
                    "width": desired_x_px,
                    "height": desired_y_px
                },
                "step1_params": {
                    "target_width": step1_params[0],
                    "target_height": step1_params[1],
                    "overlap_horizontally": step1_params[2],
                    "overlap_vertically": step1_params[3],
                    "overlap_percentages": [3, 5, 10, 15]
                },
                "step2_params": {
                    "target_width": step2_params[0],
                    "target_height": step2_params[1],
                    "overlap_horizontally": step2_params[2],
                    "overlap_vertically": step2_params[3],
                    "overlap_percentages": [3, 5, 10, 15]
                }
            })
        else:
            # Single-step strategy
            recommended_x, recommended_y, overlap_h, overlap_v = \
                _get_extension_params(strategy, desired_ratio)
            
            # Return parameters for frontend to call AI extension endpoint
            logger.info(
                f"Returning AI extension parameters: "
                f"{recommended_x}x{recommended_y}, "
                f"overlap_h={overlap_h}, overlap_v={overlap_v}"
            )
            
            return JSONResponse(content={
                "status": "needs_extension",
                "strategy": strategy,
                "current_ratio": current_ratio,
                "desired_ratio": desired_ratio,
                "target_dimensions_px": {
                    "width": desired_x_px,
                    "height": desired_y_px
                },
                "ai_extension_params": {
                    "target_width": recommended_x,
                    "target_height": recommended_y,
                    "overlap_horizontally": overlap_h,
                    "overlap_vertically": overlap_v,
                    "overlap_percentages": [3, 5, 10, 15]
                }
            })
        
    except Exception as exc:
        logger.exception("Step 1 failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


def _get_extension_params(strategy: str, desired_ratio: float) \
        -> tuple[int, int, bool, bool]:
    """Helper to get extension parameters for a given strategy."""
    if strategy == "landscape_extend_width":
        rec_x, rec_y = calculate_constrained_dimensions(desired_ratio)
        return rec_x, rec_y, True, False
    elif strategy == "landscape_extend_height":
        rec_x, rec_y = calculate_constrained_dimensions(desired_ratio)
        return rec_x, rec_y, False, True
    elif strategy == "portrait_extend_width":
        rec_x, rec_y = calculate_constrained_dimensions(desired_ratio)
        return rec_x, rec_y, True, False
    elif strategy == "portrait_extend_height":
        rec_x, rec_y = calculate_constrained_dimensions(desired_ratio)
        return rec_x, rec_y, False, True
    elif strategy == "landscape_to_square":
        return 1024, 1024, False, True
    elif strategy == "portrait_to_square":
        return 1024, 1024, True, False
    elif strategy == "square_to_landscape":
        rec_x, rec_y = calculate_constrained_dimensions(desired_ratio)
        return rec_x, rec_y, True, False
    elif strategy == "square_to_portrait":
        rec_x, rec_y = calculate_constrained_dimensions(desired_ratio)
        return rec_x, rec_y, False, True
    else:
        raise ValueError(f"Unknown strategy: {strategy}")


@app.post(f"{prefix}/process_for_print_step2")
async def process_for_print_step2_endpoint(
    selected_image_path: str = Form(...),
    target_width: float = Form(...),
    target_height: float = Form(...),
    unit: str = Form("mm"),
    dpi: int = Form(300),
    add_bleed: bool = Form(True),
    bleed_mm: float = Form(3.0),
):
    """
    Step 2: Complete processing with selected AI extension result.
    
    Takes the selected extended image and completes:
    - Add mirror bleed
    - Upscale to target DPI
    - Convert to PDF with cutline
    """
    unit = unit.strip().lower()
    if unit == "mm":
        target_width_mm = target_width
        target_height_mm = target_height
    else:
        target_width_mm = target_width * 25.4
        target_height_mm = target_height * 25.4

    try:
        # Load the selected extended image
        pil_image = Image.open(selected_image_path).convert("RGB")
        
        # Step 7: Add mirror bleed
        if add_bleed and bleed_mm > 0:
            bleed_inch = bleed_mm / 25.4
            bleed_px = calculate_desired_bleed_in_pixels(bleed_inch, dpi)
            pil_image, x1, y1, x2, y2 = add_desired_mirror_bleed(
                pil_image, bleed_px
            )
            logger.info(f"Step 7: Added {bleed_mm}mm bleed ({bleed_px}px)")
        else:
            w, h = pil_image.size
            x1, y1, x2, y2 = 0, 0, w, h
            logger.info("Step 7: No bleed added")
        
        # Step 8: Upscale with LANCZOS
        desired_x_inch = target_width_mm / 25.4
        desired_y_inch = target_height_mm / 25.4
        desired_x_px, desired_y_px, _ = calculate_desired_pixels(
            desired_x_inch, desired_y_inch, dpi
        )
        
        actual_x_px, actual_y_px, _ = read_image_dimensions_and_ratio(
            pil_image
        )
        scaling_factor = determine_scaling_factor(
            desired_x_px, desired_y_px, actual_x_px, actual_y_px
        )
        
        if scaling_factor > 1.01:
            pil_image = upscale_with_LANCZOS(pil_image, scaling_factor)
            logger.info(f"Step 8: Upscaled by {scaling_factor:.2f}x")
        else:
            logger.info("Step 8: No upscaling needed")
        
        # Step 9: Convert to CMYK
        pil_image = image_to_CMYK(pil_image)
        logger.info("Step 9: Converted to CMYK")
        
        # Step 10: Create PDF with cutline
        pdf_doc = image_to_pdf_with_dimensions(pil_image, dpi)
        
        if add_bleed and bleed_mm > 0:
            # Calculate cutline position in points
            bleed_pts = (bleed_mm / 25.4) * 72
            page = pdf_doc[0]
            pw, ph = page.rect.width, page.rect.height
            cutline_rect = (
                bleed_pts,
                bleed_pts,
                pw - bleed_pts,
                ph - bleed_pts
            )
            pdf_doc = add_cutline(pdf_doc, cutline_rect)
            logger.info("Step 10: Added CutContour spot color cutline")
        else:
            logger.info("Step 10: No cutline added (no bleed)")
        
        pdf_bytes = pdf_doc.tobytes()
        
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": "attachment; filename=print_ready.pdf"
            }
        )
        
    except Exception as exc:
        logger.exception("Step 2 failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
