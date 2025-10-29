"""Helper functions for AI extension mask preview generation."""
from PIL import Image, ImageDraw


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
