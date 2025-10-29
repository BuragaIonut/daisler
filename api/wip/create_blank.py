import fitz  # PyMuPDF
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, ArrayObject, TextStringObject, NumberObject, BooleanObject, NameObject
import io
from datetime import datetime

def create_cutline_pdf(output_path="cutline_rectangle.pdf", width=500, height=500):
    """
    Create a PDF with cutting machine compatible metadata and a rectangle cutline.
    """
    
    # Create a basic PDF with PyMuPDF first
    doc = fitz.open()
    page = doc.new_page(width=width, height=height)
    
    # Draw a white background
    page.draw_rect(fitz.Rect(0, 0, width, height), color=(1, 1, 1), fill=(1, 1, 1))
    
    # Draw a rectangle outline in the center (this will become our cutline)
    center_x, center_y = width/2, height/2
    rect_width, rect_height = 200, 150
    
    rect = fitz.Rect(
        center_x - rect_width/2,
        center_y - rect_height/2, 
        center_x + rect_width/2,
        center_y + rect_height/2
    )
    
    # Draw the rectangle outline
    page.draw_rect(rect, color=(0.862745, 0.133333, 0.129412), width=2)
    
    # Save to bytes buffer
    pdf_bytes = doc.write()
    doc.close()
    
    # Now modify the PDF with pypdf to add cutting machine metadata
    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()
    
    # Get the page
    page = reader.pages[0]
    
    # Create the separation color space for cutting
    separation_colorspace = ArrayObject([
        NameObject("/Separation"),
        NameObject("/CUT"),
        NameObject("/DeviceRGB"),
        DictionaryObject({
            "/FunctionType": NumberObject(2),
            "/Domain": ArrayObject([NumberObject(0), NumberObject(1)]),
            "/C0": ArrayObject([NumberObject(1), NumberObject(1), NumberObject(1)]),
            "/C1": ArrayObject([NumberObject(0.862745), NumberObject(0.133333), NumberObject(0.129412)]),
            "/N": NumberObject(1),
            "/Range": ArrayObject([NumberObject(0.0), NumberObject(1), NumberObject(0.0), NumberObject(1), NumberObject(0.0), NumberObject(1)])
        })
    ])
    
    # Create ExtGState
    ext_gstate = DictionaryObject({
        "/Type": NameObject("/ExtGState"),
        "/AIS": BooleanObject(False),
        "/BM": NameObject("/Normal"),
        "/CA": NumberObject(1),
        "/OP": BooleanObject(False),
        "/OPM": NumberObject(1),
        "/SA": BooleanObject(True),
        "/SMask": NameObject("/None"),
        "/ca": NumberObject(1),
        "/op": BooleanObject(False)
    })
    
    # Create layer properties for cutting machine
    layer_properties = DictionaryObject({
        "/Title": TextStringObject("Layer 1"),
        "/Visible": BooleanObject(True),
        "/Preview": BooleanObject(True),
        "/Printed": BooleanObject(True),
        "/Dimmed": BooleanObject(False),
        "/Editable": BooleanObject(True),
        "/Color": ArrayObject([NumberObject(20224), NumberObject(32768), NumberObject(65535)])
    })
    
    # Update page resources
    if "/Resources" not in page:
        page[NameObject("/Resources")] = DictionaryObject()
    
    resources = page["/Resources"]
    
    # Add ColorSpace
    if "/ColorSpace" not in resources:
        resources[NameObject("/ColorSpace")] = DictionaryObject()
    resources["/ColorSpace"][NameObject("/CS0")] = separation_colorspace
    
    # Add ExtGState
    if "/ExtGState" not in resources:
        resources[NameObject("/ExtGState")] = DictionaryObject()
    resources["/ExtGState"][NameObject("/GS0")] = ext_gstate
    
    # Add Properties (Layer info)
    if "/Properties" not in resources:
        resources[NameObject("/Properties")] = DictionaryObject()
    resources["/Properties"][NameObject("/MC0")] = layer_properties
    
    # Add page boxes for cutting machine compatibility
    page[NameObject("/MediaBox")] = ArrayObject([NumberObject(0.0), NumberObject(0.0), NumberObject(width), NumberObject(height)])
    page[NameObject("/CropBox")] = ArrayObject([NumberObject(0.0), NumberObject(0.0), NumberObject(width), NumberObject(height)])
    page[NameObject("/TrimBox")] = ArrayObject([NumberObject(0.0), NumberObject(0.0), NumberObject(width), NumberObject(height)])
    page[NameObject("/BleedBox")] = ArrayObject([NumberObject(0.0), NumberObject(0.0), NumberObject(width), NumberObject(height)])
    
    # Add art box (defines the meaningful content area)
    margin = 50
    page[NameObject("/ArtBox")] = ArrayObject([
        NumberObject(margin), 
        NumberObject(margin), 
        NumberObject(width - margin), 
        NumberObject(height - margin)
    ])
    
    # Add modification timestamp
    current_time = datetime.now().strftime("D:%Y%m%d%H%M%S+00'00'")
    page[NameObject("/LastModified")] = TextStringObject(current_time)
    
    # Create Adobe Illustrator PieceInfo for better compatibility
    illustrator_info = DictionaryObject({
        "/LastModified": TextStringObject(current_time),
        "/Private": DictionaryObject({
            "/ContainerVersion": NumberObject(9),
            "/CreatorVersion": NumberObject(29),
            "/RoundtripVersion": NumberObject(29),
            "/RoundtripStreamType": NumberObject(2),
            "/NumBlock": NumberObject(1)
        })
    })
    
    page[NameObject("/PieceInfo")] = DictionaryObject({
        "/Illustrator": illustrator_info
    })
    
    # Create custom content stream for cutline
    cutline_content = f"""
/Layer /MC0 BDC 
q
0 {height} {width} -{height} re
W n
1 1 1 rg
/GS0 gs
q 1 0 0 1 {center_x} {center_y} cm
{-rect_width/2} {-rect_height/2} m
{rect_width/2} {-rect_height/2} l
{rect_width/2} {rect_height/2} l
{-rect_width/2} {rect_height/2} l
{-rect_width/2} {-rect_height/2} l
f
Q
/CS0 CS 1 SCN
q 1 0 0 1 {center_x} {center_y} cm
{-rect_width/2} {-rect_height/2} m
{rect_width/2} {-rect_height/2} l
{rect_width/2} {rect_height/2} l
{-rect_width/2} {rect_height/2} l
{-rect_width/2} {-rect_height/2} l
h
S
Q
EMC 
Q
""".strip()
    
    # Update the content stream
    from pypdf.generic import StreamObject
    content_stream = StreamObject()
    content_stream.update({
    NameObject("/Filter"): NameObject("/FlateDecode"),  # Set filter
})
    content_stream._data = cutline_content.encode('latin-1')
    
    page[NameObject("/Contents")] = content_stream
    
    # Add the page to writer
    writer.add_page(page)
    
    # Add metadata to the document
    writer.add_metadata({
        '/Title': 'Cutline Rectangle',
        '/Creator': 'Python PDF Generator',
        '/Producer': 'PyPDF/PyMuPDF',
        '/Subject': 'Cutting machine compatible PDF',
        '/CreationDate': current_time,
        '/ModDate': current_time
    })
    
    # Write the final PDF
    with open(output_path, "wb") as output_file:
        writer.write(output_file)
    
    print(f"Cutline PDF created: {output_path}")
    print(f"Dimensions: {width}x{height}")
    print(f"Rectangle cutline: {rect_width}x{rect_height} (centered)")
    return output_path

def create_custom_cutline_pdf(output_path, width=500, height=500, shapes=None):
    """
    Create a PDF with custom shapes for cutting.
    
    Args:
        output_path: Output file path
        width, height: Page dimensions
        shapes: List of shape dictionaries, e.g.:
                [{"type": "rectangle", "x": 100, "y": 100, "width": 200, "height": 150},
                 {"type": "circle", "x": 300, "y": 300, "radius": 50}]
    """
    if shapes is None:
        # Default rectangle
        shapes = [{"type": "rectangle", "x": 150, "y": 175, "width": 200, "height": 150}]
    
    # Create basic PDF
    doc = fitz.open()
    page = doc.new_page(width=width, height=height)
    
    # White background
    page.draw_rect(fitz.Rect(0, 0, width, height), color=(1, 1, 1), fill=(1, 1, 1))
    
    # Draw shapes
    cutline_color = (0.862745, 0.133333, 0.129412)  # Red color for cutlines
    
    for shape in shapes:
        if shape["type"] == "rectangle":
            rect = fitz.Rect(
                shape["x"], 
                shape["y"], 
                shape["x"] + shape["width"], 
                shape["y"] + shape["height"]
            )
            page.draw_rect(rect, color=cutline_color, width=2)
            
        elif shape["type"] == "circle":
            center = fitz.Point(shape["x"], shape["y"])
            page.draw_circle(center, shape["radius"], color=cutline_color, width=2)
    
    # Save and process similar to above...
    pdf_bytes = doc.write()
    doc.close()
    
    # Apply the same metadata processing as the main function
    # (You would copy the same pypdf processing code here)
    
    return create_cutline_pdf(output_path, width, height)

if __name__ == "__main__":
    # Example usage
    
    # Create a basic rectangle cutline PDF
    create_cutline_pdf("rectangle_cutline.pdf", 500, 500)
    
    # Create custom shapes (you can modify this)
    custom_shapes = [
        {"type": "rectangle", "x": 100, "y": 100, "width": 300, "height": 200},
        {"type": "circle", "x": 400, "y": 400, "radius": 50}
    ]
    create_custom_cutline_pdf("custom_cutline.pdf", 500, 500, custom_shapes)