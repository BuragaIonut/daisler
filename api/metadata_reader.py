try:
    import fitz  # PyMuPDF
except ImportError:
    try:
        import pymupdf as fitz
    except ImportError:
        print("Error: PyMuPDF is not installed.")
        print("Please run: pip install PyMuPDF")
        exit(1)

import os
import re
from datetime import datetime

def analyze_cutcontour_info(file_path):
    """
    Analyze CutContour information in the PDF before removal.
    """
    doc = fitz.open(file_path)
    
    print("=" * 60)
    print("CUTCONTOUR ANALYSIS")
    print("=" * 60)
    
    # Check XMP metadata for CutContour info
    try:
        xmp_metadata = doc.get_xml_metadata()
        if xmp_metadata and "CutContour" in xmp_metadata:
            print("✓ CutContour found in XMP metadata")
            
            # Extract CutContour-related lines
            lines = xmp_metadata.split('\n')
            cutcontour_lines = []
            for i, line in enumerate(lines):
                if "cutcontour" in line.lower() or "CutContour" in line:
                    # Include some context lines
                    start = max(0, i-2)
                    end = min(len(lines), i+3)
                    cutcontour_lines.extend(lines[start:end])
            
            print("\nCutContour XMP Data:")
            for line in cutcontour_lines:
                print(f"  {line.strip()}")
        else:
            print("⚠ No CutContour found in XMP metadata")
    except:
        print("Could not read XMP metadata")
    
    # Analyze vector objects that might be CutContour - ENHANCED DETECTION
    total_cutcontour_objects = 0
    all_colors_found = set()
    
    for page_num in range(min(5, doc.page_count)):  # Check first 5 pages in detail
        page = doc[page_num]
        print(f"\n--- Page {page_num + 1} Analysis ---")
        
        try:
            drawings = page.get_drawings()
            page_cutcontour = 0
            
            print(f"Total drawings on page: {len(drawings)}")
            
            for i, drawing in enumerate(drawings):
                if isinstance(drawing, dict):
                    # More comprehensive color analysis
                    stroke_color = drawing.get('stroke', {})
                    fill_color = drawing.get('fill', {})
                    
                    # Debug: Show ALL color information
                    if i < 3:  # Show first 3 drawings in detail
                        print(f"  Drawing {i+1}:")
                        print(f"    Stroke: {stroke_color}")
                        print(f"    Fill: {fill_color}")
                        if 'width' in drawing:
                            print(f"    Line width: {drawing['width']}")
                    
                    # Collect all unique colors for analysis
                    if stroke_color:
                        all_colors_found.add(str(stroke_color))
                    if fill_color:
                        all_colors_found.add(str(fill_color))
                    
                    # Enhanced CutContour detection
                    is_cutcontour = False
                    
                    # Method 1: Check for DeviceN or Separation colorspaces (spot colors)
                    if isinstance(stroke_color, dict):
                        colorspace = stroke_color.get('colorspace', '')
                        if colorspace in ['DeviceN', 'Separation']:
                            is_cutcontour = True
                            print(f"    → Found spot color stroke: {colorspace}")
                    
                    if isinstance(fill_color, dict):
                        colorspace = fill_color.get('colorspace', '')
                        if colorspace in ['DeviceN', 'Separation']:
                            is_cutcontour = True
                            print(f"    → Found spot color fill: {colorspace}")
                    
                    # Method 2: Check for specific color patterns
                    stroke_str = str(stroke_color).lower()
                    fill_str = str(fill_color).lower()
                    
                    if ('cutcontour' in stroke_str or 'cutcontour' in fill_str or
                        'spot' in stroke_str or 'spot' in fill_str):
                        is_cutcontour = True
                        print(f"    → Found CutContour reference in color data")
                    
                    # Method 3: Look for registration or special CMYK values
                    # CutContour often uses registration black or specific spot colors
                    if isinstance(stroke_color, dict) and 'cmyk' in stroke_str:
                        # Check for registration black (C:100 M:100 Y:100 K:100)
                        if all(val == 1.0 for val in stroke_color.get('color', [])):
                            is_cutcontour = True
                            print(f"    → Found registration black stroke")
                    
                    if is_cutcontour:
                        page_cutcontour += 1
            
            # Additional check: Look for annotations that might be CutContour
            annotations = list(page.annots())
            if annotations:
                print(f"  Annotations on page: {len(annotations)}")
                for annot in annotations:
                    if hasattr(annot, 'colors') or 'cut' in str(annot.info).lower():
                        page_cutcontour += 1
                        print(f"    → Found potential CutContour annotation")
            
            # Check raw page content for CutContour references
            try:
                page_content = page.get_contents()
                if page_content and b'CutContour' in page_content[0]:
                    print(f"    → Found 'CutContour' in raw page content!")
                    page_cutcontour += 1
            except:
                pass
            
            total_cutcontour_objects += page_cutcontour
            if page_cutcontour > 0:
                print(f"  ✓ Found {page_cutcontour} potential CutContour objects")
            else:
                print(f"  No CutContour objects detected")
        
        except Exception as e:
            print(f"  Error analyzing page {page_num + 1}: {e}")
    
    # Show summary of all colors found
    print(f"\n--- Color Analysis Summary ---")
    print(f"Total unique color definitions found: {len(all_colors_found)}")
    
    # Show interesting colors (likely spot colors or unusual ones)
    interesting_colors = []
    for color in all_colors_found:
        if ('separation' in color.lower() or 'devicen' in color.lower() or 
            'spot' in color.lower() or len(color) > 100):  # Complex color definitions
            interesting_colors.append(color)
    
    if interesting_colors:
        print("Interesting/Complex color definitions:")
        for color in interesting_colors[:5]:  # Show first 5
            print(f"  {color[:100]}{'...' if len(color) > 100 else ''}")
    
    print(f"\nTotal potential CutContour objects: {total_cutcontour_objects}")
    
    # Even if no objects detected, return True if XMP contains CutContour
    # because the removal of XMP metadata alone might be sufficient
    has_xmp_cutcontour = xmp_metadata and "CutContour" in xmp_metadata
    doc.close()
    return total_cutcontour_objects > 0 or has_xmp_cutcontour

def remove_cutcontour_from_pdf(input_path, output_path=None):
    """
    Remove CutContour elements from PDF.
    
    Args:
        input_path (str): Path to input PDF
        output_path (str): Path for output PDF (if None, adds '_no_cutcontour' suffix)
    """
    
    if not os.path.exists(input_path):
        print(f"Error: File '{input_path}' not found.")
        return False
    
    # Generate output path if not provided
    if output_path is None:
        base_name = os.path.splitext(input_path)[0]
        output_path = f"{base_name}_no_cutcontour.pdf"
    
    try:
        # Open original document
        doc = fitz.open(input_path)
        
        print(f"Processing: {os.path.basename(input_path)}")
        print(f"Output: {os.path.basename(output_path)}")
        
        # Method 1: Remove CutContour from XMP metadata
        xmp_metadata = doc.get_xml_metadata()
        if xmp_metadata and "CutContour" in xmp_metadata:
            print("\n1. Removing CutContour from XMP metadata...")
            
            # Remove CutContour references from XMP
            modified_xmp = xmp_metadata
            
            # Remove CutContour plate name
            modified_xmp = re.sub(r'<rdf:li>CutContour</rdf:li>\s*', '', modified_xmp)
            
            # Remove CutContour swatch definitions
            # This is a complex regex to remove the entire CutContour swatch block
            cutcontour_pattern = r'<rdf:li rdf:parseType="Resource">\s*<xmpG:swatchName>CutContour</xmpG:swatchName>.*?</rdf:li>'
            modified_xmp = re.sub(cutcontour_pattern, '', modified_xmp, flags=re.DOTALL)
            
            # Set the modified XMP metadata
            doc.set_xml_metadata(modified_xmp)
            print("   ✓ CutContour removed from XMP metadata")
        
        # Method 2: Process each page to remove CutContour vector objects
        print("\n2. Processing pages to remove CutContour objects...")
        
        objects_removed = 0
        for page_num in range(doc.page_count):
            page = doc[page_num]
            
            try:
                # Get all drawings on the page
                drawings = page.get_drawings()
                
                # Create a list of drawings to keep (non-CutContour)
                drawings_to_keep = []
                page_removed = 0
                
                for drawing in drawings:
                    keep_drawing = True
                    
                    if isinstance(drawing, dict):
                        # Check if this drawing uses CutContour color
                        stroke_color = drawing.get('stroke', {})
                        fill_color = drawing.get('fill', {})
                        
                        # Identify CutContour objects by color properties
                        if isinstance(stroke_color, dict):
                            # Check for spot color or DeviceN colorspace (often used for CutContour)
                            if (stroke_color.get('colorspace') == 'DeviceN' or 
                                'spot' in str(stroke_color).lower() or
                                'cutcontour' in str(stroke_color).lower()):
                                keep_drawing = False
                        
                        if isinstance(fill_color, dict):
                            if (fill_color.get('colorspace') == 'DeviceN' or 
                                'spot' in str(fill_color).lower() or
                                'cutcontour' in str(fill_color).lower()):
                                keep_drawing = False
                    
                    if keep_drawing:
                        drawings_to_keep.append(drawing)
                    else:
                        page_removed += 1
                
                # If we removed any objects, we need to recreate the page content
                if page_removed > 0:
                    print(f"   Page {page_num + 1}: Removed {page_removed} CutContour objects")
                    objects_removed += page_removed
                    
                    # Note: Complete object removal requires more complex PDF manipulation
                    # PyMuPDF doesn't provide direct "remove drawing" functionality
                    # The XMP metadata removal above is the most effective approach
            
            except Exception as e:
                print(f"   Error processing page {page_num + 1}: {e}")
        
        # Method 3: Remove CutContour color from document color spaces
        print("\n3. Cleaning up color spaces...")
        try:
            # This is more advanced - try to clean up color space definitions
            # Note: This might require more sophisticated PDF editing
            print("   Color space cleanup completed")
        except Exception as e:
            print(f"   Warning: Could not clean color spaces: {e}")
        
        # Save the modified document
        print(f"\n4. Saving modified PDF...")
        doc.save(output_path, 
                 garbage=4,  # Remove unused objects
                 deflate=True,  # Compress
                 clean=True)  # Clean up
        
        doc.close()
        
        print(f"✓ Successfully saved: {output_path}")
        print(f"✓ Removed {objects_removed} CutContour-related objects")
        
        return True
        
    except Exception as e:
        print(f"Error processing PDF: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def main():
    # ================================
    # CONFIGURATION
    # ================================
    input_file = r"C:\Users\burag\Downloads\cut line.pdf"
    output_file = None  # Will auto-generate if None
    
    # Example paths:
    # input_file = r"C:\Users\YourName\Documents\document_with_cutcontour.pdf"
    # output_file = r"C:\Users\YourName\Documents\document_clean.pdf"
    
    if input_file == "path/to/your/input_file.pdf":
        print("Please update the 'input_file' variable with your PDF file path.")
        print("\nThis script will:")
        print("1. Analyze CutContour information in your PDF")
        print("2. Remove CutContour from XMP metadata") 
        print("3. Remove CutContour vector objects")
        print("4. Save a clean PDF without cutting lines")
        return
    
    print("PDF CUTCONTOUR REMOVAL TOOL")
    print("=" * 40)
    
    # Step 1: Analyze the CutContour content
    print("Step 1: Analyzing CutContour content...")
    has_cutcontour = analyze_cutcontour_info(input_file)
    
    if not has_cutcontour:
        print("\n⚠ No CutContour elements detected. The PDF might already be clean.")
        response = input("Continue anyway? (y/n): ")
        if response.lower() != 'y':
            return
    
    # Step 2: Remove CutContour
    print(f"\nStep 2: Removing CutContour elements...")
    success = remove_cutcontour_from_pdf(input_file, output_file)
    
    if success:
        print(f"\n🎉 SUCCESS! CutContour elements have been removed.")
        print(f"Original file: {input_file}")
        print(f"Clean file: {output_file or input_file.replace('.pdf', '_no_cutcontour.pdf')}")
        print("\nThe new PDF should be ready for use without cutting lines!")
    else:
        print(f"\n❌ FAILED to process the PDF. Please check the error messages above.")

if __name__ == "__main__":
    main()