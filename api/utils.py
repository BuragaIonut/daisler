
from PIL import Image
import fitz
from io import BytesIO
from gradio_client import Client, handle_file

# these will come from UI in future
DESIRED_X = 300 / 25.4  # in inches
DESIRED_Y = 360 / 25.4  # in inches
DESIRED_PPI = 150  # pixels per inch

def calculate_desired_pixels(desired_x_inch: float, desired_y_inch: float, desired_ppi: float) -> tuple[int, int]:
    desired_x_px = int(desired_x_inch * desired_ppi)
    desired_y_px = int(desired_y_inch * desired_ppi)
    desired_ratio = desired_x_px / desired_y_px
    return desired_x_px, desired_y_px, desired_ratio

def calculate_desired_bleed_in_pixels(bleed_inch: float, desired_ppi: float) -> int:
    bleed_px = int(bleed_inch * desired_ppi)
    return bleed_px


def image_to_CMYK(image: Image.Image) -> Image.Image:
    """Convert an image to CMYK color space."""
    return image.convert("CMYK")

def pdf_page_to_CMYK(bytes_data: bytes, page_number: int = 0) -> Image.Image:
    """Convert a specific page of a PDF (given as bytes) to a CMYK image."""
    with fitz.open(stream=bytes_data, filetype="pdf") as pdf_doc:
        page = pdf_doc.load_page(page_number)
        pix = page.get_pixmap()
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        return image_to_CMYK(img)
    
def image_to_bytes(image_path: str, format: str = "JPEG") -> bytes:
    """Convert an image file to bytes."""
    with Image.open(image_path) as img:
        with BytesIO() as output:
            img.save(output, format=format)
            return output.getvalue()

def pdf_to_bytes(pdf_path: str) -> bytes:
    """Convert a PDF file to bytes."""
    with open(pdf_path, "rb") as f:
        return f.read()
    
def read_image_dimensions_and_ratio(image: Image) -> tuple[int, int, float]:
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
    Favors dimensions near the middle of the range for balanced resolution.
    
    Args:
        desired_ratio: Target aspect ratio (width/height)
        min_dimension: Minimum allowed dimension (default: 720)
        max_dimension: Maximum allowed dimension (default: 1536)
        tolerance: Acceptable ratio deviation (default: 0.01)
    
    Returns:
        Tuple of (width, height) in pixels
    
    Raises:
        ValueError: If no valid dimensions found within constraints
    """
    best_match = None
    best_error = float('inf')
    target_dimension = (min_dimension + max_dimension) / 2  # Midpoint: 1128
    best_distance_from_target = float('inf')
    
    # Try all possible combinations within constraints
    for width in range(min_dimension, max_dimension + 1):
        # Calculate ideal height for this width
        ideal_height = width / desired_ratio
        
        # Try rounding down and up
        for height in [int(ideal_height), int(ideal_height) + 1]:
            if min_dimension <= height <= max_dimension:
                actual_ratio = width / height
                error = abs(actual_ratio - desired_ratio)
                
                # Accept if within tolerance
                if error <= tolerance:
                    # Calculate distance from target (prefer middle range)
                    avg_dimension = (width + height) / 2
                    distance_from_target = abs(avg_dimension - \
                                                target_dimension)
                    
                    # Prefer dimensions closer to middle, with ratio \
                    # accuracy as tiebreaker
                    if distance_from_target < best_distance_from_target or \
                       (distance_from_target == best_distance_from_target \
                        and error < best_error):
                        best_error = error
                        best_match = (width, height)
                        best_distance_from_target = distance_from_target
                elif error < best_error:
                    # Track best match even if outside tolerance
                    best_error = error
                    if best_match is None:
                        best_match = (width, height)
    
    if best_match is None:
        raise ValueError(
            f"Cannot achieve ratio {desired_ratio:.3f} within "
            f"constraints [{min_dimension}, {max_dimension}]"
        )
    
    # Check if best match exceeds tolerance
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
    """Determine the scaling factor based on desired and actual dimensions."""
    scale_x = desired_x_px / actual_x_px
    scale_y = desired_y_px / actual_y_px
    return max(scale_x, scale_y)

def determine_extension_strategy(current_ratio: float, desired_ratio: float) -> str:
    if desired_ratio > 2.133:
        raise ValueError("Desired ratio exceeds maximum limit of 2.133")
    elif desired_ratio < 0.4687:
        raise ValueError("Desired ratio is below minimum limit of 0.4687")
    if 2.133 > desired_ratio > 1:
        # landscape desired
        if 2.133 > current_ratio > 1:
            # current is landscape
            if current_ratio < desired_ratio:
                # need to extend width (wider landscape)
                strategy = "landscape_extend_width"
            elif current_ratio > desired_ratio:
                # need to extend height (taller landscape)
                strategy = "landscape_extend_height"
            else:
                strategy = "no_extension_needed"
        elif current_ratio < 1:
            # current is portrait (portrait to landscape)
            strategy = "portrait_to_square_to_landscape"
        else:
            # current is square ( square to landscape)
            strategy = "square_to_landscape"
    elif 0.4687 < desired_ratio < 1:
        # portrait desired
        if current_ratio < 1:
            # current is portrait
            if current_ratio > desired_ratio:
                # need to extend height (taller portrait)
                strategy = "portrait_extend_height"
            elif current_ratio < desired_ratio:
                # need to extend width (wider portrait)
                strategy = "portrait_extend_width"
            else:
                strategy = "no_extension_needed"
        elif current_ratio > 1:
            # current is landscape (landscape to portrait)
            strategy = "landscape_to_square_to_portrait"
        else:
            # current is square ( square to portrait)
            strategy = "square_to_portrait"
    else:
        # square desired
        if current_ratio > 1:
            # current is landscape (landscape to square)
            strategy = "landscape_to_square"
        elif current_ratio < 1:
            # current is portrait (portrait to square)
            strategy = "portrait_to_square"
        else:
            # current is square ( square to square)
            strategy = "no_extension_needed"
    return strategy

def extend_image_with_ai(
    image_path: str,
    strategy: str,
    actual_x_px: int, 
    actual_y_px: int, 
    desired_ratio: float
) -> Image.Image:
    """
    Determine extension steps based on ratio transformations.
    Returns guidance on how to transform current ratio to desired ratio.
    """
    if 0.4687 < desired_ratio < 2.1333:
        if strategy == "landscape_extend_width":
            recommended_x, recommended_y = calculate_constrained_dimensions(desired_ratio)
            print(f"From {actual_x_px}x{actual_y_px} to {recommended_x}x{recommended_y}")
            extended_image = ai_image_extension(
                image_path=image_path,
                target_width=recommended_x,
                target_height=recommended_y,
                overlap_horizontally=True,
                overlap_vertically=False,
                overlap_percentage=10
            )

        elif strategy == "landscape_extend_height":
            recommended_x, recommended_y = calculate_constrained_dimensions(desired_ratio)
            extended_image = ai_image_extension(
                image_path=image_path,
                target_width=recommended_x,
                target_height=recommended_y,
                overlap_horizontally=True,
                overlap_vertically=False,
                overlap_percentage=10
            )
            print(f"From {actual_x_px}x{actual_y_px} to {recommended_x}x{recommended_y}")
        elif strategy == "portrait_extend_height":
            recommended_x, recommended_y = calculate_constrained_dimensions(desired_ratio)
            extended_image = ai_image_extension(
                image_path=image_path,
                target_width=recommended_x,
                target_height=recommended_y,
                overlap_horizontally=True,
                overlap_vertically=False,
                overlap_percentage=10
            )
            print(f"From {actual_x_px}x{actual_y_px} to {recommended_x}x{recommended_y}")
        elif strategy == "portrait_extend_width":
            recommended_x, recommended_y = calculate_constrained_dimensions(desired_ratio)
            extended_image = ai_image_extension(
                image_path=image_path,
                target_width=recommended_x,
                target_height=recommended_y,
                overlap_horizontally=True,
                overlap_vertically=False,
                overlap_percentage=10
            )
            print(f"From {actual_x_px}x{actual_y_px} to {recommended_x}x{recommended_y}")
        elif strategy == "landscape_to_square":
            recommended_x, recommended_y = 1024, 1024
            extended_image = ai_image_extension(
                image_path=image_path,
                target_width=recommended_x,
                target_height=recommended_y,
                overlap_horizontally=False,
                overlap_vertically=True,
                overlap_percentage=10
            )
            print(f"From {actual_x_px}x{actual_y_px} to {recommended_x}x{recommended_y}")
        elif strategy == "portrait_to_square":
            recommended_x, recommended_y = 1024, 1024
            extended_image = ai_image_extension(
                image_path=image_path,
                target_width=recommended_x,
                target_height=recommended_y,
                overlap_horizontally=True,
                overlap_vertically=False,
                overlap_percentage=10
            )
            print(f"From {actual_x_px}x{actual_y_px} to {recommended_x}x{recommended_y}")
        elif strategy == "square_to_landscape":
            recommended_x, recommended_y = calculate_constrained_dimensions(desired_ratio)
            extended_image = ai_image_extension(
                image_path=image_path,
                target_width=recommended_x,
                target_height=recommended_y,
                overlap_horizontally=True,
                overlap_vertically=False,
                overlap_percentage=10
            )
            print(f"From {actual_x_px}x{actual_y_px} to {recommended_x}x{recommended_y}")
        elif strategy == "square_to_portrait":
            recommended_x, recommended_y = calculate_constrained_dimensions(desired_ratio)
            extended_image = ai_image_extension(
                image_path=image_path,
                target_width=recommended_x,
                target_height=recommended_y,
                overlap_horizontally=False,
                overlap_vertically=True,
                overlap_percentage=10
            )
            print(f"From {actual_x_px}x{actual_y_px} to {recommended_x}x{recommended_y}")
        elif strategy == "portrait_to_square_to_landscape":
            recommended_x, recommended_y = calculate_constrained_dimensions(desired_ratio)
            square_image = ai_image_extension(
                image_path=image_path,
                target_width=1024,
                target_height=1024,
                overlap_horizontally=False,
                overlap_vertically=True,
                overlap_percentage=10
            )
            extended_image = ai_image_extension(
                image_path=square_image,
                target_width=recommended_x,
                target_height=recommended_y,
                overlap_horizontally=True,
                overlap_vertically=False,
                overlap_percentage=10
            )
            print(f"From {actual_x_px}x{actual_y_px} to 1024x1024 to {recommended_x}x{recommended_y}")
        elif strategy == "landscape_to_square_to_portrait":
            recommended_x, recommended_y = calculate_constrained_dimensions(desired_ratio)
            square_image = ai_image_extension(
                image_path=image_path,
                target_width=1024,
                target_height=1024,
                overlap_horizontally=True,
                overlap_vertically=False,
                overlap_percentage=10
            )
            extended_image = ai_image_extension(
                image_path=square_image,
                target_width=recommended_x,
                target_height=recommended_y,
                overlap_horizontally=False,
                overlap_vertically=True,
                overlap_percentage=10
            )
            print(f"From {actual_x_px}x{actual_y_px} to 1024x1024 to {recommended_x}x{recommended_y}")
        else:
            recommended_x, recommended_y = actual_x_px, actual_y_px
            print(f"No extension needed. Current dimensions: {recommended_x}x{recommended_y}")
            extended_image = image_path
        print(type(extended_image))
        print(extended_image)
        return extended_image
    else:
        raise ValueError("Desired ratio is out of acceptable range (0.4687 to 2.1333)")


def ai_image_extension(image_path: str, target_width: int, target_height: int, overlap_horizontally: bool, overlap_vertically: bool, overlap_percentage: int) -> str:
    """Use this tool to extend an image using AI.
    target_width = int(target_width)
    target_height = int(target_height)
    overlap_percentage = int(overlap_percentage) - between 5 and 25
    """
    num_inference_steps = 12
    prompt = ""
    alignment = "Middle"
    overlap_left = False
    overlap_right = False
    overlap_top = False
    overlap_bottom = False
    if overlap_vertically:
        overlap_top = True
        overlap_bottom = True
    if overlap_horizontally:
        overlap_left = True
        overlap_right = True
    
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
    image_path = result[1]
    mask_path = result[0]
    return (image_path, mask_path)

def add_desired_mirror_bleed(
    image: Image.Image, 
    bleed_px: int
) -> tuple[Image.Image, int, int, int, int]:
    """
    Add bleed to an image using mirror technique for seamless blending.
    
    Args:
        image: Input PIL image
        bleed_px: Bleed size in pixels
        
    Returns:
        Tuple of:
        - PIL image with bleed added
        - x1: Left coordinate of original image in expanded canvas
        - y1: Top coordinate of original image in expanded canvas
        - x2: Right coordinate of original image in expanded canvas
        - y2: Bottom coordinate of original image in expanded canvas
    """
    if bleed_px <= 0:
        w, h = image.size
        return image, 0, 0, w, h
        
    pad = bleed_px
    w, h = image.size
    
    # Create expanded canvas
    expanded = Image.new(image.mode, (w + 2 * pad, h + 2 * pad))
    expanded.paste(image, (pad, pad))
    
    # Left and right bands (mirror horizontally)
    left_band = image.crop((0, 0, min(pad, w), h)) \
                     .transpose(Image.FLIP_LEFT_RIGHT)
    right_band = image.crop((max(0, w - pad), 0, w, h)) \
                      .transpose(Image.FLIP_LEFT_RIGHT)
    expanded.paste(left_band, (0, pad))
    expanded.paste(right_band, (pad + w, pad))
    
    # Top and bottom bands (mirror vertically)
    top_band = image.crop((0, 0, w, min(pad, h))) \
                    .transpose(Image.FLIP_TOP_BOTTOM)
    bottom_band = image.crop((0, max(0, h - pad), w, h)) \
                       .transpose(Image.FLIP_TOP_BOTTOM)
    expanded.paste(top_band, (pad, 0))
    expanded.paste(bottom_band, (pad, pad + h))
    
    # Corners (double reflection ~ rotate 180)
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
    
    # Calculate coordinates of original image in expanded canvas
    x1, y1 = pad, pad
    x2, y2 = pad + w, pad + h
    
    return expanded, x1, y1, x2, y2


def upscale_with_LANCZOS(image: Image.Image, scaling_factor: float) -> Image.Image:
    """Upscale an image using LANCZOS filter."""
    new_width = int(image.width * scaling_factor)
    new_height = int(image.height * scaling_factor)
    return image.resize((new_width, new_height), Image.LANCZOS)


def add_cutline(doc, rect, spot_name="CutContour", alt_cmyk=(0.3, 0.5, 1, 0),
                page_num=0, hairline=True, stroke_width=0.5):
    """
    Add a rectangle cutline (spot color stroke) to a PDF page.

    Args:
        doc (fitz.Document): an open PDF document
        rect (tuple): (x0, y0, x1, y1) coordinates of the rectangle
        spot_name (str): name of the spot color (default: "CutContour")
        alt_cmyk (tuple): alternate CMYK values for screen display
        page_num (int): zero-based page index (default: 0 = first page)
        hairline (bool): True = hairline stroke, False = use stroke_width
        stroke_width (float): width in pt, used if hairline=False

    Returns:
        fitz.Document: the modified document
    """
    page = doc[page_num]
    page_xref = page.xref

    # --- create Separation object for spot color ---
    sep_obj = (
        f"[ /Separation /{spot_name} /DeviceCMYK "
        f"<< /FunctionType 2 /Domain [0 1] /C0 [0 0 0 0] "
        f"/C1 [{' '.join(map(str, alt_cmyk))}] /N 1 >> ]"
    )
    sep_xref = doc.get_new_xref()
    doc.update_object(sep_xref, sep_obj)

    # --- ensure /Resources exists ---
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

    # --- ensure /ColorSpace includes /CS1 ---
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

    # --- build rectangle content ---
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

    # --- add stream ---
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
            doc.update_object(arr_xref, f"[ {old_xref} 0 R {stream_xref} 0 R ]")
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
            doc.update_object(arr_xref, f"[ {old_xref} 0 R {stream_xref} 0 R ]")
            doc.xref_set_key(page_xref, "Contents", f"{arr_xref} 0 R")

    return doc


def image_to_pdf(image: Image.Image) -> fitz.Document:
    """Convert a PIL image to a single-page PDF document."""
    with BytesIO() as img_buffer:
        image.save(img_buffer, format="JPEG")
        img_bytes = img_buffer.getvalue()
    pdf_doc = fitz.open()
    rect = fitz.Rect(0, 0, image.width, image.height)
    page = pdf_doc.new_page(width=image.width, height=image.height)
    page.insert_image(rect, stream=img_bytes)
    return pdf_doc

if __name__ == "__main__":
    image_path = r"api\files\drops_image.jpg"
    cmyk_image = image_to_CMYK(Image.open(image_path))
    # # Example usage for PDF conversion
    # pdf_bytes = pdf_to_bytes(r"api\files\desert.pdf")
    # cmyk_image = pdf_page_to_CMYK(pdf_bytes)
    desired_bleed = calculate_desired_bleed_in_pixels(3 / 25.4, DESIRED_PPI)
    desired_x_px, desired_y_px, desired_ratio = calculate_desired_pixels(DESIRED_X, DESIRED_Y, DESIRED_PPI)
    actual_x_px, actual_y_px, actual_ratio = read_image_dimensions_and_ratio(cmyk_image)
    scaling_factor = determine_scaling_factor(desired_x_px, desired_y_px, actual_x_px, actual_y_px)
    print(f"Desired bleed (px): {desired_bleed}")
    print(f"Desired dimensions (px): {desired_x_px} x {desired_y_px}, "
          f"ratio: {desired_ratio:.4f}")
    print(f"Actual dimensions (px): {actual_x_px} x {actual_y_px}, "
          f"ratio: {actual_ratio:.4f}")
    print(f"Scaling factor: {scaling_factor:.4f}")
    strategy = determine_extension_strategy(actual_ratio, desired_ratio)
    print(f"Determined strategy: {strategy}")
    
    # tuple_result = extend_image_with_ai(
    #     image_path=image_path,
    #     strategy=strategy,
    #     actual_x_px=actual_x_px,
    #     actual_y_px=actual_y_px,
    #     desired_ratio=desired_ratio
    # )
    # img_path, mask_path = tuple_result
    # mask_image = Image.open(mask_path)
    # extended_image = Image.open(img_path)
    # extended_image.save("final_extended_image.jpeg", format="JPEG")
    # mask_image.save("final_mask_image.png", format="PNG")
    # print("Final extended image and mask saved.")
    # # Add bleed
    # expanded_img, x1, y1, x2, y2 = add_desired_mirror_bleed(extended_image, bleed_px=desired_bleed)
    # # Now you know exactly where the original content is:
    # upscaled_image = upscale_with_LANCZOS(expanded_img, scaling_factor)
    # print(f"Original content coordinates in expanded image: ({x1*scaling_factor}, {y1*scaling_factor}) to ({x2*scaling_factor}, {y2*scaling_factor})")
    # # Optionally, draw rectangle to visualize original content area
    # upscaled_image.save("final_upscaled_image.jpeg", format="JPEG")
    # print("Final upscaled image saved.")


