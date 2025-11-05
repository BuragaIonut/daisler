from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, JSONResponse
from io import BytesIO
import base64
import logging
import os
import json
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
    bleed_mm: float, 
    desired_ppi: float
) -> int:
    """Calculate bleed in pixels from millimeters and PPI."""
    bleed_inch = bleed_mm / 25.4
    bleed_px = int(bleed_inch * desired_ppi)
    return bleed_px


def calculate_desired_pixels(
    desired_x_mm: float, 
    desired_y_mm: float, 
    desired_ppi: float
) -> tuple[int, int, float]:
    """Calculate desired dimensions in pixels and aspect ratio."""
    desired_x_px = int((desired_x_mm / 25.4) * desired_ppi)
    desired_y_px = int((desired_y_mm / 25.4) * desired_ppi)
    desired_ratio = desired_x_px / desired_y_px
    return desired_x_px, desired_y_px, desired_ratio


def mm_to_pixels(x_mm, y_mm, dpi):
    """
    Calculates the number of pixels for given dimensions in millimeters (mm)
    and a specific resolution in Dots Per Inch (DPI).

    Args:
        x_mm (float): The width in millimeters.
        y_mm (float): The height in millimeters.
        dpi (int): The resolution in Dots Per Inch.

    Returns:
        tuple: A tuple (x_pixels, y_pixels) representing the needed pixels.
    """
    # 1 inch = 25.4 millimeters
    MM_PER_INCH = 25.4

    # Calculate inches: distance_in_inches = distance_in_mm / 25.4
    x_inches = x_mm / MM_PER_INCH
    y_inches = y_mm / MM_PER_INCH

    # Calculate pixels: distance_in_pixels = distance_in_inches * dpi
    x_pixels = x_inches * dpi
    y_pixels = y_inches * dpi
    ratio = x_pixels / y_pixels
    # Return the results, often rounded to the nearest integer for practical pixel use
    return round(x_pixels), round(y_pixels), ratio

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
    target_width_mm: int, 
    target_height_mm: int, 
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
        f"AI Extension: target={target_width_mm}x{target_height_mm}, "
        f"overlap_h={overlap_horizontally}, overlap_v={overlap_vertically}"
    )
    
    client = Client("https://6o4c9k5qwfwtgx-7860.proxy.runpod.net/")
    
    result = client.predict(
        image=handle_file(image_path),
        width=target_width_mm,
        height=target_height_mm,
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
    logger.info(f"Added mirror bleed: ({x1}, {y1}), ({x2}, {y2})")
    
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
    logger.info(f"Rectangle cutline on page {page_num}, rect={rect}")
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
    rect_width = x1 - x0
    rect_height = y1 - y0
    w = 0 if hairline else stroke_width
    
    logger.info(
        f"Drawing cutline rectangle: x={x0:.2f}, y={y0:.2f}, "
        f"width={rect_width:.2f}, height={rect_height:.2f}"
    )
    
    content = (
        "q\n"
        f"{w} w\n"
        "/CS1 CS\n"
        "1 SCN\n"
        f"{x0} {y0} {rect_width} {rect_height} re\n"
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
    Complete workflow for print production with comprehensive debugging.
    
    Debug information includes:
    - Bleed: Pixel/inch measurements, trim box coordinates before/after
    - Upscale: Scale factor, dimensions before/after, trim box tracking
    - Cutline: Conversion formulas (with/without doubling), Y-flip \
calculations,
               expected vs actual bleed distances in mm/inches/points
    
    Workflow (frontend handles PDF conversion + cropping first):
    1. Frontend: Upload PDF → Convert to image via /pdf_to_image
    2. Frontend: User crops the image (or uses full image)
    3. Frontend: Send cropped image to this endpoint
    4. Backend: Calculate desired dimensions, ratio, scaling factor
    5. Backend: Determine extension strategy
    6. Backend: Extend image with AI if needed
    7. Backend: Add mirror bleed (if enabled) - TRACKED IN DEBUG
    8. Backend: Upscale image to final dimensions - TRACKED IN DEBUG
    9. Backend: Convert to PDF with cutline - TRACKED IN DEBUG
    10. Backend: Return downloadable PDF with X-Debug-Info header
    
    Args:
        file: Image file ONLY (PNG/JPEG) - PDFs already converted by frontend
        target_width: Target width (in mm or inches)
        target_height: Target height (in mm or inches)
        unit: "mm" or "inch"
        dpi: Target DPI (default 300)
        add_bleed: Whether to add bleed (default True)
        bleed_mm: Bleed size in mm (default 3.0)
        
    Returns:
        PDF with bleed and cutline, plus comprehensive debug info in \
X-Debug-Info header
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
        
        # Store original image coordinates before bleed (for debug)
        bleed_debug = {
            "step": "7_add_bleed",
            "bleed_mm": bleed_mm,
            "bleed_px": bleed_px,
            "image_before_bleed": {
                "width_px": current_w,
                "height_px": current_h,
                "width_inches": current_w / dpi,
                "height_inches": current_h / dpi
            }
        }
        
        if add_bleed and bleed_px > 0:
            pil_image, trim_x1, trim_y1, trim_x2, trim_y2 = \
                add_desired_mirror_bleed(pil_image, bleed_px)
            
            bleed_debug["image_after_bleed"] = {
                "width_px": pil_image.width,
                "height_px": pil_image.height,
                "width_inches": pil_image.width / dpi,
                "height_inches": pil_image.height / dpi
            }
            bleed_debug["trim_box_pixels"] = {
                "x1": trim_x1,
                "y1": trim_y1,
                "x2": trim_x2,
                "y2": trim_y2,
                "width": trim_x2 - trim_x1,
                "height": trim_y2 - trim_y1,
                "note": "Where original image starts in bleeded image"
            }
            bleed_debug["trim_box_inches"] = {
                "x1": trim_x1 / dpi,
                "y1": trim_y1 / dpi,
                "x2": trim_x2 / dpi,
                "y2": trim_y2 / dpi,
                "width": (trim_x2 - trim_x1) / dpi,
                "height": (trim_y2 - trim_y1) / dpi
            }
            
            logger.info(
                f"Added {bleed_px}px ({bleed_mm}mm) bleed. "
                f"Image: {current_w}x{current_h}px -> "
                f"{pil_image.width}x{pil_image.height}px. "
                f"Trim box: ({trim_x1},{trim_y1})-({trim_x2},{trim_y2})px"
            )
        else:
            bleed_debug["image_after_bleed"] = bleed_debug["image_before_bleed"]
            bleed_debug["trim_box_pixels"] = {
                "x1": 0, "y1": 0, "x2": current_w, "y2": current_h,
                "note": "No bleed added"
            }
        
        # Step 8: Upscale to final dimensions
        # Target includes bleed
        final_width_px = desired_x_px + (2 * bleed_px if add_bleed else 0)
        final_height_px = desired_y_px + (2 * bleed_px if add_bleed else 0)
        
        scale_factor = determine_scaling_factor(
            final_width_px, final_height_px,
            pil_image.width, pil_image.height
        )
        
        upscale_debug = {
            "step": "8_upscale",
            "scale_factor": round(scale_factor, 3),
            "target_with_bleed_px": {
                "width": final_width_px,
                "height": final_height_px
            },
            "image_before_upscale": {
                "width_px": pil_image.width,
                "height_px": pil_image.height
            },
            "trim_box_before_upscale_px": {
                "x1": trim_x1, "y1": trim_y1, "x2": trim_x2, "y2": trim_y2
            }
        }
        
        if scale_factor != 1.0:
            pil_image = upscale_with_LANCZOS(pil_image, scale_factor)
            # Update trim box coordinates
            trim_x1 = int(trim_x1 * scale_factor)
            trim_y1 = int(trim_y1 * scale_factor)
            trim_x2 = int(trim_x2 * scale_factor)
            trim_y2 = int(trim_y2 * scale_factor)
            
            upscale_debug["image_after_upscale"] = {
                "width_px": pil_image.width,
                "height_px": pil_image.height,
                "width_inches": pil_image.width / dpi,
                "height_inches": pil_image.height / dpi
            }
            upscale_debug["trim_box_after_upscale_px"] = {
                "x1": trim_x1, "y1": trim_y1, "x2": trim_x2, "y2": trim_y2,
                "width": trim_x2 - trim_x1,
                "height": trim_y2 - trim_y1
            }
            upscale_debug["trim_box_after_upscale_inches"] = {
                "x1": trim_x1 / dpi,
                "y1": trim_y1 / dpi,
                "x2": trim_x2 / dpi,
                "y2": trim_y2 / dpi,
                "width": (trim_x2 - trim_x1) / dpi,
                "height": (trim_y2 - trim_y1) / dpi
            }
            
            logger.info(
                f"Upscaled by {scale_factor:.3f}x. "
                f"Image: {upscale_debug['image_before_upscale']['width_px']}x"
                f"{upscale_debug['image_before_upscale']['height_px']}px -> "
                f"{pil_image.width}x{pil_image.height}px. "
                f"Trim box: ({trim_x1},{trim_y1})-({trim_x2},{trim_y2})px"
            )
        else:
            upscale_debug["image_after_upscale"] = \
                upscale_debug["image_before_upscale"]
            upscale_debug["trim_box_after_upscale_px"] = \
                upscale_debug["trim_box_before_upscale_px"]
        
        # Step 9: Convert to PDF
        pdf_doc = image_to_pdf_with_dimensions(pil_image, dpi)
        
        # Step 10: Add cutline at trim box
        cutline_coords = None
        cutline_debug = {
            "step": "10_add_cutline",
            "enabled": add_bleed
        }
        
        if add_bleed:
            # CRITICAL: The trim box coordinates are in SCALED pixels
            # The image has been upscaled, so trim coordinates are also scaled
            # We need to convert these scaled pixels to PDF points using the
            # target DPI
            
            # Calculate PDF page dimensions (this determines physical size)
            width_pts = (pil_image.width / dpi) * 72
            height_pts = (pil_image.height / dpi) * 72
            
            cutline_debug["pdf_page_size_pts"] = {
                "width": round(width_pts, 2),
                "height": round(height_pts, 2)
            }
            cutline_debug["pdf_page_size_inches"] = {
                "width": round(width_pts / 72, 4),
                "height": round(height_pts / 72, 4)
            }
            
            cutline_debug["scale_factor_applied"] = round(scale_factor, 3)
            cutline_debug["note"] = (
                "Trim box coordinates are in SCALED pixels. "
                "They were multiplied by scale_factor during upscaling."
            )
            
            # Convert trim box from SCALED pixels to PDF points
            # Simple formula: (pixels / dpi) * 72
            # NO DOUBLING - coordinates are already scaled correctly!
            trim_x1_pts = (trim_x1 / dpi) * 72
            trim_y1_pts = (trim_y1 / dpi) * 72
            trim_x2_pts = (trim_x2 / dpi) * 72
            trim_y2_pts = (trim_y2 / dpi) * 72
            
            cutline_debug["conversion_formula"] = {
                "description": "Simple conversion from scaled pixels to points",
                "formula": "(pixels / dpi) * 72",
                "x1": f"({trim_x1} / {dpi}) * 72 = {trim_x1_pts:.2f}",
                "y1": f"({trim_y1} / {dpi}) * 72 = {trim_y1_pts:.2f}",
                "x2": f"({trim_x2} / {dpi}) * 72 = {trim_x2_pts:.2f}",
                "y2": f"({trim_y2} / {dpi}) * 72 = {trim_y2_pts:.2f}"
            }
            
            cutline_debug["trim_box_before_y_flip_pts"] = {
                "x1": round(trim_x1_pts, 2),
                "y1": round(trim_y1_pts, 2),
                "x2": round(trim_x2_pts, 2),
                "y2": round(trim_y2_pts, 2),
                "width": round(trim_x2_pts - trim_x1_pts, 2),
                "height": round(trim_y2_pts - trim_y1_pts, 2)
            }
            
            # Flip Y coordinates for PDF coordinate system (bottom-left origin)
            trim_y1_pdf = height_pts - trim_y2_pts
            trim_y2_pdf = height_pts - trim_y1_pts
            
            cutline_debug["y_flip_calculation"] = {
                "formula": "y_flipped = page_height - y_original",
                "y1_flipped": f"{height_pts:.2f} - {trim_y2_pts:.2f} = "
                              f"{trim_y1_pdf:.2f}",
                "y2_flipped": f"{height_pts:.2f} - {trim_y1_pts:.2f} = "
                              f"{trim_y2_pdf:.2f}"
            }
            
            cutline_debug["trim_box_after_y_flip_pts"] = {
                "x1": round(trim_x1_pts, 2),
                "y1": round(trim_y1_pdf, 2),
                "x2": round(trim_x2_pts, 2),
                "y2": round(trim_y2_pdf, 2),
                "width": round(trim_x2_pts - trim_x1_pts, 2),
                "height": round(trim_y2_pdf - trim_y1_pdf, 2)
            }
            
            cutline_debug["trim_box_after_y_flip_inches"] = {
                "x1": round(trim_x1_pts / 72, 4),
                "y1": round(trim_y1_pdf / 72, 4),
                "x2": round(trim_x2_pts / 72, 4),
                "y2": round(trim_y2_pdf / 72, 4),
                "width": round((trim_x2_pts - trim_x1_pts) / 72, 4),
                "height": round((trim_y2_pdf - trim_y1_pdf) / 72, 4)
            }
            
            cutline_debug["expected_bleed_distance"] = {
                "mm": bleed_mm,
                "inches": round(bleed_mm / 25.4, 4),
                "points": round((bleed_mm / 25.4) * 72, 2),
                "note": "Cutline should be at this distance from page edge"
            }
            
            cutline_debug["actual_cutline_distance_from_edge"] = {
                "left_pts": round(trim_x1_pts, 2),
                "top_pts": round(trim_y1_pdf, 2),
                "left_inches": round(trim_x1_pts / 72, 4),
                "top_inches": round(trim_y1_pdf / 72, 4),
                "left_mm": round((trim_x1_pts / 72) * 25.4, 2),
                "top_mm": round((trim_y1_pdf / 72) * 25.4, 2)
            }
            
            logger.info(
                f"PDF conversion:\n"
                f"  Page: {width_pts:.2f}x{height_pts:.2f}pts "
                f"({width_pts/72:.4f}x{height_pts/72:.4f}in)\n"
                f"  Trim box (pixels): ({trim_x1},{trim_y1})-"
                f"({trim_x2},{trim_y2})\n"
                f"  Trim box (points, before Y-flip): "
                f"({trim_x1_pts:.2f},{trim_y1_pts:.2f})-"
                f"({trim_x2_pts:.2f},{trim_y2_pts:.2f})\n"
                f"  Trim box (points, after Y-flip): "
                f"({trim_x1_pts:.2f},{trim_y1_pdf:.2f})-"
                f"({trim_x2_pts:.2f},{trim_y2_pdf:.2f})\n"
                f"  Expected bleed distance: {bleed_mm}mm = "
                f"{(bleed_mm/25.4)*72:.2f}pts\n"
                f"  Actual cutline distance from edge: "
                f"{trim_x1_pts:.2f}pts = {(trim_x1_pts/72)*25.4:.2f}mm"
            )
            
            trim_rect = (trim_x1_pts, trim_y1_pdf, trim_x2_pts, trim_y2_pdf)
            pdf_doc = add_cutline(pdf_doc, trim_rect, "CutContour")
            
            cutline_coords = {
                "x1": round(trim_x1_pts, 2),
                "y1": round(trim_y1_pdf, 2),
                "x2": round(trim_x2_pts, 2),
                "y2": round(trim_y2_pdf, 2),
                "unit": "points"
            }
        else:
            cutline_debug["reason_not_added"] = "Bleed not enabled"
        
        # Prepare comprehensive debug information
        debug_info = {
            "original_image": {
                "width_px": actual_x_px,
                "height_px": actual_y_px,
                "aspect_ratio": round(actual_ratio, 3)
            },
            "target_dimensions": {
                "width_px": desired_x_px,
                "height_px": desired_y_px,
                "aspect_ratio": round(desired_ratio, 3),
                "dpi": dpi,
                "width_inches": round(desired_x_px / dpi, 4),
                "height_inches": round(desired_y_px / dpi, 4)
            },
            "strategy": strategy,
            "scale_factor": round(scale_factor, 3),
            "bleed_debug": bleed_debug,
            "upscale_debug": upscale_debug,
            "cutline_debug": cutline_debug,
            "cutline_coordinates": cutline_coords
        }
        
        logger.info(f"Debug info: {json.dumps(debug_info, indent=2)}")
        
        # Step 11: Return PDF
        pdf_bytes = pdf_doc.tobytes()
        pdf_doc.close()
        
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": \
                    'attachment; filename="print_ready.pdf"',
                "X-Debug-Info": json.dumps(debug_info)
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


@app.post(f"{prefix}/test_add_bleed")
async def test_add_bleed_endpoint(
    file: UploadFile = File(...),
    bleed_mm: float = Form(3.0),
    dpi: int = Form(300),
    target_width_mm: float = Form(None),
    target_height_mm: float = Form(None),
    upscale: bool = Form(False),
):
    """
    TEST ENDPOINT: Add mirror bleed to an image and optionally upscale it.
    
    This endpoint is for testing bleed visualization and upscaling. It adds 
    mirror bleed to the image, optionally upscales it to target dimensions,
    and returns it as a PNG so you can visually inspect the bleed area.
    
    Args:
        file: Image file (jpeg/png) without bleed
        bleed_mm: Bleed size in millimeters (default: 3.0)
        dpi: DPI for calculating bleed in pixels (default: 300)
        target_width_mm: Target width in mm for upscaling (optional)
        target_height_mm: Target height in mm for upscaling (optional)
        upscale: Whether to upscale to target dimensions (default: False)
        
    Returns:
        PNG image with bleed added (and optionally upscaled)
        
    Example usage:
        1. Without upscaling:
           Upload a 100x100px image with 3mm bleed at 300 DPI
           Result will be ~135x135px (3mm = ~35px at 300 DPI on each side)
        
        2. With upscaling:
           Upload a 100x100px image, add 3mm bleed, upscale to 210x297mm (A4)
           Result will be final A4 size with bleed at 300 DPI
    """
    if file.content_type not in ("image/jpeg", "image/png", "image/jpg"):
        raise HTTPException(
            status_code=400, 
            detail="Only image files accepted (jpeg/png)"
        )

    if bleed_mm < 0:
        raise HTTPException(status_code=400, detail="Bleed must be non-negative")
    
    if dpi <= 0:
        raise HTTPException(status_code=400, detail="DPI must be positive")

    try:
        raw = await file.read()
        pil_image = Image.open(BytesIO(raw)).convert("RGB")
        
        original_width, original_height = pil_image.size
        logger.info(
            f"TEST: Adding {bleed_mm}mm bleed at {dpi} DPI to "
            f"{original_width}x{original_height}px image"
        )
        
        # Calculate bleed in pixels
        bleed_inch = bleed_mm / 25.4
        bleed_px = calculate_desired_bleed_in_pixels(bleed_inch, dpi)
        
        logger.info(f"TEST: Bleed = {bleed_mm}mm = {bleed_inch:.4f}in = {bleed_px}px")
        
        # Add mirror bleed
        pil_image_with_bleed, x1, y1, x2, y2 = add_desired_mirror_bleed(
            pil_image, bleed_px
        )
        
        new_width, new_height = pil_image_with_bleed.size
        logger.info(
            f"TEST: Bleed added. Size: {original_width}x{original_height}px -> "
            f"{new_width}x{new_height}px"
        )
        logger.info(
            f"TEST: Original image area (trim box): "
            f"({x1}, {y1}) to ({x2}, {y2})"
        )
        
        # Optional: Upscale to target dimensions
        scaling_factor = 1.0
        if upscale and target_width_mm and target_height_mm:
            logger.info(
                f"TEST: Upscaling to {target_width_mm}x{target_height_mm}mm "
                f"at {dpi} DPI"
            )
            
            # Calculate target dimensions in pixels (including bleed)
            target_width_inch = target_width_mm / 25.4
            target_height_inch = target_height_mm / 25.4
            target_width_px = int(target_width_inch * dpi)
            target_height_px = int(target_height_inch * dpi)
            
            logger.info(
                f"TEST: Target size with bleed: {target_width_px}x{target_height_px}px"
            )
            
            # Determine scaling factor
            scaling_factor = determine_scaling_factor(
                target_width_px, target_height_px,
                new_width, new_height
            )
            
            logger.info(f"TEST: Scaling factor: {scaling_factor:.4f}")
            
            if scaling_factor > 1.01:
                # Upscale the image
                pil_image_with_bleed = upscale_with_LANCZOS(
                    pil_image_with_bleed, scaling_factor
                )
                
                # Update trim box coordinates after scaling
                x1 = int(x1 * scaling_factor)
                y1 = int(y1 * scaling_factor)
                x2 = int(x2 * scaling_factor)
                y2 = int(y2 * scaling_factor)
                
                new_width, new_height = pil_image_with_bleed.size
                logger.info(
                    f"TEST: Upscaled to {new_width}x{new_height}px "
                    f"(factor: {scaling_factor:.4f})"
                )
                logger.info(
                    f"TEST: Scaled trim box: ({x1}, {y1}) to ({x2}, {y2})"
                )
            else:
                logger.info("TEST: No upscaling needed (factor <= 1.01)")
        
        # Add visual markers to show the trim box (optional debug overlay)
        # Draw red lines at the bleed boundary
        draw = ImageDraw.Draw(pil_image_with_bleed)
        
        # Draw trim box rectangle in red
        draw.rectangle(
            [(x1, y1), (x2, y2)], 
            outline=(255, 0, 0), 
            width=max(2, int(2 * scaling_factor))  # Scale line width too
        )
        
        logger.info("TEST: Added red trim box overlay for visualization")
        
        # Return as PNG
        buf = BytesIO()
        pil_image_with_bleed.save(buf, format="PNG")
        
        # Generate descriptive filename
        if upscale and scaling_factor > 1.01:
            filename = f"with_bleed_upscaled_{bleed_mm}mm_{dpi}dpi_{new_width}x{new_height}px.png"
        else:
            filename = f"with_bleed_{bleed_mm}mm_{dpi}dpi_{new_width}x{new_height}px.png"
        
        return Response(
            content=buf.getvalue(), 
            media_type="image/png",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Original-Size": f"{original_width}x{original_height}",
                "X-New-Size": f"{new_width}x{new_height}",
                "X-Bleed-MM": str(bleed_mm),
                "X-Bleed-PX": str(bleed_px),
                "X-Trim-Box": f"{x1},{y1},{x2},{y2}",
                "X-Scaling-Factor": f"{scaling_factor:.4f}",
                "X-Upscaled": str(upscale and scaling_factor > 1.01),
                "X-DPI": str(dpi)
            }
        )
        
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("TEST: Add bleed failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Add bleed error: {str(exc)}")


@app.post(f"{prefix}/test_add_cutline")
async def test_add_cutline_endpoint(
    file: UploadFile = File(...),
    bleed_mm: float = Form(3.0),
    dpi: int = Form(300),
):
    """
    TEST ENDPOINT: Add cutline to an image with bleed and return as PDF.
    
    This endpoint is for testing cutline positioning. It assumes the input
    image already has bleed added. It converts the image to PDF and adds
    a CutContour spot color cutline at the bleed boundary.
    
    IMPORTANT: The input image should already have bleed added! 
    Use /test_add_bleed first to add bleed, then pass that result here.
    
    Args:
        file: Image file (jpeg/png) WITH bleed already added
        bleed_mm: Bleed size in millimeters that was added (default: 3.0)
        dpi: DPI of the image (default: 300)
        
    Returns:
        PDF with CutContour spot color cutline at the bleed boundary
        
    Example workflow:
        1. POST image to /test_add_bleed -> get PNG with bleed
        2. POST that PNG to /test_add_cutline -> get PDF with cutline
        3. Open PDF in Adobe Acrobat/Illustrator to verify cutline position
    """
    if file.content_type not in ("image/jpeg", "image/png", "image/jpg"):
        raise HTTPException(
            status_code=400, 
            detail="Only image files accepted (jpeg/png)"
        )

    if bleed_mm < 0:
        raise HTTPException(status_code=400, detail="Bleed must be non-negative")
    
    if dpi <= 0:
        raise HTTPException(status_code=400, detail="DPI must be positive")

    try:
        raw = await file.read()
        pil_image = Image.open(BytesIO(raw)).convert("RGB")
        
        img_width, img_height = pil_image.size
        logger.info(
            f"TEST: Adding cutline to {img_width}x{img_height}px image "
            f"with {bleed_mm}mm bleed at {dpi} DPI"
        )
        
        # Convert image to PDF
        pdf_doc = image_to_pdf_with_dimensions(pil_image, dpi)
        
        # Get PDF page dimensions
        page = pdf_doc[0]
        page_width_pts = page.rect.width
        page_height_pts = page.rect.height
        
        logger.info(
            f"TEST: PDF page size: {page_width_pts:.2f}x{page_height_pts:.2f} pts "
            f"({page_width_pts/72:.4f}x{page_height_pts/72:.4f} inches)"
        )
        
        # Calculate cutline position (bleed distance from edge)
        bleed_pts = (bleed_mm / 25.4) * 72
        
        logger.info(
            f"TEST: Bleed = {bleed_mm}mm = {bleed_mm/25.4:.4f}in = "
            f"{bleed_pts:.2f}pts"
        )
        
        # Cutline rectangle (inside the bleed)
        cutline_x1 = bleed_pts
        cutline_y1 = bleed_pts
        cutline_x2 = page_width_pts - bleed_pts
        cutline_y2 = page_height_pts - bleed_pts
        
        cutline_rect = (cutline_x1, cutline_y1, cutline_x2, cutline_y2)
        
        logger.info(
            f"TEST: Cutline rectangle (points): "
            f"({cutline_x1:.2f}, {cutline_y1:.2f}) to "
            f"({cutline_x2:.2f}, {cutline_y2:.2f})"
        )
        logger.info(
            f"TEST: Cutline dimensions: "
            f"{cutline_x2 - cutline_x1:.2f}x{cutline_y2 - cutline_y1:.2f} pts"
        )
        logger.info(
            f"TEST: Distance from edge: "
            f"left={cutline_x1:.2f}pts ({cutline_x1/72*25.4:.2f}mm), "
            f"top={cutline_y1:.2f}pts ({cutline_y1/72*25.4:.2f}mm)"
        )
        
        # Add CutContour spot color cutline
        pdf_doc = add_cutline(pdf_doc, cutline_rect, "CutContour")
        
        logger.info("TEST: CutContour spot color cutline added successfully")
        
        # Get PDF bytes
        pdf_bytes = pdf_doc.tobytes()
        pdf_doc.close()
        
        # Generate descriptive filename
        filename = f"with_cutline_{bleed_mm}mm_{dpi}dpi_{img_width}x{img_height}px.pdf"
        
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Image-Size-PX": f"{img_width}x{img_height}",
                "X-PDF-Size-PTS": f"{page_width_pts:.2f}x{page_height_pts:.2f}",
                "X-Bleed-MM": str(bleed_mm),
                "X-Bleed-PTS": f"{bleed_pts:.2f}",
                "X-Cutline-Rect": f"{cutline_x1:.2f},{cutline_y1:.2f},{cutline_x2:.2f},{cutline_y2:.2f}",
                "X-DPI": str(dpi)
            }
        )
        
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("TEST: Add cutline failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Add cutline error: {str(exc)}") 

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
    target_width_mm: float = Form(...),
    target_height_mm: float = Form(...),
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
    if target_width_mm <= 0 or target_height_mm <= 0 or dpi <= 0:
        raise HTTPException(status_code=400, detail="Invalid dimensions/DPI")
    
    unit = unit.strip().lower()
    if unit != "mm":
        raise HTTPException(status_code=400, detail="Unit must be mm")

    # Convert to mm
    if unit == "mm":
        target_width_mm = target_width_mm
        target_height_mm = target_height_mm

    raw = await file.read()
    
    try:
        pil_image = Image.open(BytesIO(raw)).convert("RGB")
        actual_x_px, actual_y_px, current_ratio = \
            read_image_dimensions_and_ratio(pil_image)
        logger.info(
            f"Image size: {actual_x_px}x{actual_y_px}px, "
            f"Current ratio: {current_ratio:.4f}"
        )
        desired_x_mm = target_width_mm
        desired_y_mm = target_height_mm

        logger.info(
            f"Desired size: {desired_x_mm}x{desired_y_mm}mm at {dpi} DPI"
        )


        desired_x_px, desired_y_px, desired_ratio = \
            calculate_desired_pixels(desired_x_mm, desired_y_mm, dpi)


        logger.info(
            f"Desired size in pixels: {desired_x_px}x{desired_y_px}px, "
            f"Desired ratio: {desired_ratio:.4f}"
        )

        scaling_factor = determine_scaling_factor(
            desired_x_px, desired_y_px,
            actual_x_px, actual_y_px
        )

        logger.info(f"Scaling factor: {scaling_factor:.4f}")

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
                "desired_ratio": desired_ratio,
                "overlap_percentages": [3, 5, 10, 15]
            })
        elif strategy == "portrait_to_square":
            return JSONResponse(content={
                "status": "needs_extension",
                "message": "Image is portrait and needs extension to square format",
                "strategy": strategy,
                "current_ratio": current_ratio,
                "desired_ratio": desired_ratio,
                "target_width": 1024,
                "target_height": 1024,
                "overlap_horizontally": True,
                "overlap_vertically": False,
                "overlap_percentages": [3, 5, 10, 15]
            })
        elif strategy == "landscape_to_square":
            return JSONResponse(content={
                "status": "needs_extension",
                "message": "Image is landscape and needs extension to square format",
                "strategy": strategy,
                "current_ratio": current_ratio,
                "desired_ratio": desired_ratio,
                "target_width": 1024,
                "target_height": 1024,
                "overlap_horizontally": False,
                "overlap_vertically": True,
                "overlap_percentages": [3, 5, 10, 15]
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

            logger.info(
                f"Calculated constrained dimensions for step 2: {rec_x}x{rec_y}"
            )

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
            recommended_x_px, recommended_y_px, overlap_h, overlap_v = \
                _get_extension_params(strategy, desired_ratio)
            
            # Return parameters for frontend to call AI extension endpoint
            logger.info(
                f"Returning AI extension parameters: "
                f"{recommended_x_px}x{recommended_y_px}, "
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
                    "target_width": recommended_x_px,
                    "target_height": recommended_y_px,
                    "overlap_horizontally": overlap_h,
                    "overlap_vertically": overlap_v,
                    "overlap_percentages": [3, 5, 10, 15]
                }
            })
        
    except Exception as exc:
        logger.exception("Step 1 failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

@app.post(f"{prefix}/process_for_print_step2")
async def process_for_print_step2_endpoint(
    selected_image_path: str = Form(...),
    target_width: float = Form(...),
    target_height: float = Form(...),
    unit: str = Form("mm"),
    dpi: int = Form(300),
    add_bleed: bool = Form(True),
    bleed_mm: float = Form(3.0),
    to_add_cutline: bool = Form(False),
):
    """
    Step 2: Complete processing with selected AI extension result.
    
    Takes the selected extended image and completes:
    - Add mirror bleed
    - Upscale to target DPI
    - Convert to PDF with cutline (if requested)
    """
    unit = unit.strip().lower()
    target_width_mm = target_width
    target_height_mm = target_height

    try:
        # Load the selected extended image
        pil_image = Image.open(selected_image_path).convert("RGB")
        
        # Step 7: Add mirror bleed
        if add_bleed and bleed_mm > 0:
            bleed_px = calculate_desired_bleed_in_pixels(bleed_mm, dpi)
            pil_image, x1, y1, x2, y2 = add_desired_mirror_bleed(
                pil_image, bleed_px
            )
            logger.info(f"Step 7: Added {bleed_mm}mm bleed ({bleed_px}px)")
            logger.info(f"Coordinates of original image area: ({x1}, {y1}) to ({x2}, {y2})")
        else:
            w, h = pil_image.size
            x1, y1, x2, y2 = 0, 0, w, h
            logger.info("Step 7: No bleed added")

        # Step 8: Upscale to target dimensions at desired DPI
        desired_x_px, desired_y_px, _ = calculate_desired_pixels(
            target_width_mm, target_height_mm, dpi
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
        
        if to_add_cutline and add_bleed and bleed_mm > 0:
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
            if not to_add_cutline:
                logger.info("Step 10: Cutline not requested")
            elif not add_bleed or bleed_mm <= 0:
                logger.info("Step 10: No cutline added (no bleed)")
            else:
                logger.info("Step 10: No cutline added")
        
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
