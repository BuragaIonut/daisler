from reportlab.pdfgen import canvas
from reportlab.lib.colors import Color, PCMYKColor
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, ArrayObject, NumberObject, BooleanObject, NameObject, TextStringObject, IndirectObject
from datetime import datetime


def create_cut_color(spot_name='CUT', c=0, m=87, y=87, k=13, density=100):
    """
    Create a spot color for cutting using ReportLab's PCMYKColor
    
    Args:
        spot_name: Name of the spot color (default: 'CUT')
        c, m, y, k: CMYK values (0-100) for the equivalent color
        density: Density of the spot color (0-100)
    
    Returns:
        PCMYKColor: A ReportLab spot color object
    
    Example:
        # Default red cut color
        cut_color = create_cut_color()
        
        # Custom blue cut color  
        blue_cut = create_cut_color('BLUE_CUT', c=100, m=50, y=0, k=0)
        
        # Custom green cut color
        green_cut = create_cut_color('GREEN_CUT', c=50, m=0, y=100, k=0)
    """
    return PCMYKColor(c, m, y, k, spotName=spot_name, density=density)

class CutSpotColor(Color):
    """Custom spot color class for cutting machines"""
    def __init__(self, spotName='CUT', equiv_cmyk=(0.0, 0.9, 0.9, 0.0)):
        # The equivalent CMYK color for preview (reddish)
        self.spotName = spotName
        self.equiv_cmyk = equiv_cmyk
        super().__init__(equiv_cmyk[0], equiv_cmyk[1], equiv_cmyk[2], equiv_cmyk[3])
        
    def __repr__(self):
        return f"CutSpotColor({self.spotName})"

def create_cutline_pdf_reportlab(filename="cutline_reportlab.pdf", width=500, height=500):
    """
    Create a cutting machine compatible PDF using ReportLab with spot colors
    """
    
    # Convert dimensions to points (ReportLab uses points)
    width_pts = width * 72 / 100  # Assuming input is in some unit, convert to points
    height_pts = height * 72 / 100
    
    # Create the PDF
    c = canvas.Canvas(filename, pagesize=(width_pts, height_pts))
    
    # Define the CUT spot color
    cut_color = CutSpotColor('CUT', (0.0, 0.87, 0.87, 0.13))  # Equivalent CMYK for the red color
    
    # Register the spot color with ReportLab
    # This creates the separation color space in the PDF
    c.setFillColor(cut_color)
    c.setStrokeColor(cut_color)
    
    # Fill the background with white first
    c.setFillColor('white')
    c.rect(0, 0, width_pts, height_pts, fill=1, stroke=0)
    
    # Set the cut color for the rectangle outline
    c.setStrokeColor(cut_color)
    c.setFillColor(cut_color)
    c.setLineWidth(2)
    
    # Draw a centered rectangle
    rect_width = 200 * 72 / 100  # Convert to points
    rect_height = 150 * 72 / 100
    
    x = (width_pts - rect_width) / 2
    y = (height_pts - rect_height) / 2
    
    # Draw rectangle outline only (no fill for cutting)
    c.rect(x, y, rect_width, rect_height, fill=0, stroke=1)
    
    # Add some metadata
    c.setTitle("Cutline Rectangle")
    c.setAuthor("ReportLab Generator")
    c.setSubject("Cutting Machine Compatible PDF")
    c.setCreator("Python/ReportLab")
    
    # Save the PDF
    c.save()
    
    # Now enhance with cutting machine specific metadata using pypdf
    enhance_for_cutting_machine(filename)
    
    print(f"Created cutting PDF: {filename}")
    print(f"Page size: {width}x{height}")
    print(f"Rectangle: {200}x{150} (centered)")
    
    return filename

def enhance_for_cutting_machine(pdf_path):
    """
    Add cutting machine specific metadata to the PDF
    """
    try:
        # Read the existing PDF
        reader = PdfReader(pdf_path)
        writer = PdfWriter()
        
        # Process each page
        for page_num, page in enumerate(reader.pages):
            
            # Add cutting machine specific resources if they don't exist
            if "/Resources" not in page:
                page[NameObject("/Resources")] = DictionaryObject()
            
            resources = page["/Resources"]
            
            # Enhance ExtGState for cutting compatibility
            if "/ExtGState" not in resources:
                resources[NameObject("/ExtGState")] = DictionaryObject()
            
            if "/ColorSpace" not in resources:
                resources[NameObject("/ColorSpace")] = DictionaryObject()
            
            if "/CS0" not in resources["/ColorSpace"]:
                cs0 = ArrayObject([
                    NameObject("/Separation"),
                    NameObject("/CUT"),
                    NameObject("/DeviceCMYK"),
                    DictionaryObject({
                        "/FunctionType": NumberObject(2),
                        "/Domain": ArrayObject([NumberObject(0), NumberObject(1)]),
                        "/C0": ArrayObject([NumberObject(1), NumberObject(1), NumberObject(1), NumberObject(1)]),
                        "/C1": ArrayObject([NumberObject(0), NumberObject(0.87), NumberObject(0.87), NumberObject(0.13)]),
                        "/N": NumberObject(1),
                        "/Range": ArrayObject([NumberObject(0.0), NumberObject(1), NumberObject(0.0), NumberObject(1), NumberObject(0.0), NumberObject(1), NumberObject(0.0), NumberObject(1)])
                    })
                ])
                resources["/ColorSpace"][NameObject("/CS0")] = cs0
            
            
            # Add cutting machine compatible ExtGState
            cut_extgstate = DictionaryObject({
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
            resources["/ExtGState"][NameObject("/GS_Cut")] = cut_extgstate
            
            # Add layer properties for cutting machines
            if "/Properties" not in resources:
                resources[NameObject("/Properties")] = DictionaryObject()
                
            layer_props = DictionaryObject({
                "/Title": TextStringObject("CUT Layer"),
                "/Visible": BooleanObject(True),
                "/Preview": BooleanObject(True), 
                "/Printed": BooleanObject(True),
                "/Dimmed": BooleanObject(False),
                "/Editable": BooleanObject(True),
                "/Color": ArrayObject([NumberObject(65535), NumberObject(8738), NumberObject(8738)])  # Red in RGB565
            })
            resources["/Properties"][NameObject("/MC_CUT")] = layer_props
            
            # Add page boxes for cutting machine compatibility
            page_width = float(page.mediabox[2])
            page_height = float(page.mediabox[3])
            
            page[NameObject("/CropBox")] = page.mediabox
            page[NameObject("/TrimBox")] = page.mediabox  
            page[NameObject("/BleedBox")] = page.mediabox
            
            # Art box with small margin
            margin = 36  # 0.5 inch margin
            page[NameObject("/ArtBox")] = ArrayObject([
                NumberObject(margin),
                NumberObject(margin), 
                NumberObject(page_width - margin),
                NumberObject(page_height - margin)
            ])
            
            # Add timestamp
            current_time = datetime.now().strftime("D:%Y%m%d%H%M%S+00'00'")
            page[NameObject("/LastModified")] = TextStringObject(current_time)
            
            # Add Adobe Illustrator compatibility info
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
            
            writer.add_page(page)
        
        # Copy document info and enhance it
        if reader.metadata:
            writer.add_metadata(reader.metadata)
            
        # Add cutting-specific metadata
        writer.add_metadata({
            '/Title': 'Cutline Document',
            '/Subject': 'Cutting Machine Compatible PDF',
            '/Keywords': 'cutting, die-cut, spot-color, CUT',
            '/Creator': 'ReportLab + PyPDF Enhancement',
            '/Producer': 'Python Cutting PDF Generator'
        })
        
        # Write the enhanced PDF
        with open(pdf_path, "wb") as output_file:
            writer.write(output_file)
            
        print(f"Enhanced PDF with cutting machine metadata: {pdf_path}")
        
    except Exception as e:
        print(f"Warning: Could not enhance PDF metadata: {e}")


# Example usage and testing
if __name__ == "__main__":
    
    print("Creating basic rectangle cutline PDF...")
    create_cutline_pdf_reportlab("rectangle_cut_2.pdf", 500, 500)
    
    
    print("\nDone! Check the generated PDF files.")
    print("\nTo verify the spot color was created correctly, open the PDF")
    print("in Adobe Acrobat and check the separations preview.")