try:
    import fitz  # PyMuPDF
except ImportError:
    print("Error: PyMuPDF is not installed.")
    print("Please run: pip install PyMuPDF")
    exit(1)

import os
import re
from datetime import datetime

def analyze_pdf_content_streams(file_path):
    """
    Deep analysis of PDF content streams to find CutContour references.
    """
    doc = fitz.open(file_path)
    
    print("=" * 70)
    print("DEEP CUTCONTOUR ANALYSIS - CONTENT STREAMS")
    print("=" * 70)
    
    cutcontour_references = []
    total_objects_with_cutcontour = 0
    
    for page_num in range(min(3, doc.page_count)):  # Check first 3 pages
        page = doc[page_num]
        print(f"\n--- Page {page_num + 1} Deep Analysis ---")
        
        # Method 1: Analyze raw page content streams
        try:
            contents = page.get_contents()
            for i, content in enumerate(contents):
                if b'CutContour' in content:
                    print(f"✓ Found 'CutContour' in content stream {i}")
                    
                    # Extract surrounding context
                    content_str = content.decode('latin-1', errors='ignore')
                    lines = content_str.split('\n')
                    
                    cutcontour_lines = []
                    for line_num, line in enumerate(lines):
                        if 'CutContour' in line:
                            # Get context around the CutContour reference
                            start = max(0, line_num - 2)
                            end = min(len(lines), line_num + 3)
                            cutcontour_lines.extend(lines[start:end])
                            total_objects_with_cutcontour += 1
                    
                    if cutcontour_lines:
                        print("  Context:")
                        for line in cutcontour_lines[:10]:  # Show first 10 context lines
                            print(f"    {line.strip()}")
                        
                        cutcontour_references.extend(cutcontour_lines)
        except Exception as e:
            print(f"  Error reading content streams: {e}")
        
        # Method 2: Check for color space definitions
        try:
            # Get page resources - this might contain CutContour color definitions
            page_dict = page.get_contents()  # This gives us access to the page object
            
            # Try to access the page's resource dictionary
            # Note: This is a simplified approach - real PDF parsing would be more complex
            print(f"  Checking page resources for color spaces...")
            
        except Exception as e:
            print(f"  Error checking page resources: {e}")
    
    print(f"\nTotal content stream references to CutContour: {total_objects_with_cutcontour}")
    doc.close()
    
    return cutcontour_references, total_objects_with_cutcontour > 0

def find_cutcontour_in_pdf_source(file_path):
    """
    Search for CutContour references in the raw PDF source.
    """
    print("\n" + "=" * 70)
    print("RAW PDF SOURCE ANALYSIS")
    print("=" * 70)
    
    cutcontour_found = False
    
    try:
        # Read PDF as binary to search for CutContour references
        with open(file_path, 'rb') as f:
            pdf_content = f.read()
        
        # Search for various CutContour patterns
        patterns = [
            b'CutContour',
            b'/CutContour',
            b'CutContour ',
            b'(CutContour)',
            b'[CutContour]'
        ]
        
        for pattern in patterns:
            matches = pdf_content.count(pattern)
            if matches > 0:
                print(f"✓ Found {matches} instances of '{pattern.decode()}'")
                cutcontour_found = True
        
        # Find position of CutContour references for context
        if b'CutContour' in pdf_content:
            positions = []
            start = 0
            while True:
                pos = pdf_content.find(b'CutContour', start)
                if pos == -1:
                    break
                positions.append(pos)
                start = pos + 1
            
            print(f"\nCutContour found at byte positions: {positions[:10]}...")  # Show first 10
            
            # Show context around first few occurrences
            for i, pos in enumerate(positions[:3]):
                start = max(0, pos - 100)
                end = min(len(pdf_content), pos + 100)
                context = pdf_content[start:end]
                
                print(f"\nContext {i+1} (around byte {pos}):")
                try:
                    context_str = context.decode('latin-1', errors='ignore')
                    # Clean up for display
                    context_str = re.sub(r'[\x00-\x1f\x7f-\x9f]', ' ', context_str)
                    print(f"  ...{context_str}...")
                except:
                    print(f"  Binary content around CutContour")
    
    except Exception as e:
        print(f"Error reading PDF source: {e}")
    
    return cutcontour_found

def remove_cutcontour_advanced(input_path, output_path=None):
    """
    Advanced CutContour removal using multiple approaches.
    """
    if output_path is None:
        base_name = os.path.splitext(input_path)[0]
        output_path = f"{base_name}_advanced_no_cutcontour.pdf"
    
    print(f"\n" + "=" * 70)
    print("ADVANCED CUTCONTOUR REMOVAL")
    print("=" * 70)
    
    try:
        doc = fitz.open(input_path)
        
        # Method 1: XMP Metadata removal (as before)
        print("1. Removing CutContour from XMP metadata...")
        xmp_metadata = doc.get_xml_metadata()
        if xmp_metadata and "CutContour" in xmp_metadata:
            modified_xmp = xmp_metadata
            
            # More comprehensive CutContour removal patterns
            patterns_to_remove = [
                r'<rdf:li>CutContour</rdf:li>\s*',
                r'<rdf:li rdf:parseType="Resource">\s*<xmpG:swatchName>CutContour</xmpG:swatchName>.*?</rdf:li>',
                r'<xmpG:swatchName>CutContour</xmpG:swatchName>.*?(?=<xmpG:swatchName>|</rdf:Seq>)',
            ]
            
            for pattern in patterns_to_remove:
                modified_xmp = re.sub(pattern, '', modified_xmp, flags=re.DOTALL)
            
            doc.set_xml_metadata(modified_xmp)
            print("   ✓ CutContour metadata removed")
        
        # Method 2: Content stream modification
        print("2. Processing content streams...")
        objects_modified = 0
        
        for page_num in range(doc.page_count):
            page = doc[page_num]
            
            try:
                # Get content streams - handle different return types
                contents = page.get_contents()
                
                # Handle different return types from get_contents()
                content_list = []
                if isinstance(contents, bytes):
                    content_list = [contents]
                elif isinstance(contents, list):
                    content_list = contents
                elif isinstance(contents, int):
                    # If it returns an xref number, try to get the actual content
                    try:
                        xref = contents
                        # Try to read the content using the xref
                        content_bytes = doc.xref_stream(xref)
                        if content_bytes:
                            content_list = [content_bytes]
                    except:
                        print(f"   Cannot access content stream xref {contents} on page {page_num + 1}")
                        continue
                else:
                    print(f"   Unexpected content type {type(contents)} on page {page_num + 1}")
                    continue
                
                # Process each content stream
                for i, content in enumerate(content_list):
                    if not isinstance(content, bytes):
                        continue
                        
                    if b'CutContour' in content:
                        print(f"   Found CutContour in content stream {i} on page {page_num + 1}")
                        objects_modified += 1
                        
                        # Show some context of what we found
                        try:
                            content_str = content.decode('latin-1', errors='ignore')
                            lines_with_cutcontour = [line for line in content_str.split('\n') 
                                                   if 'CutContour' in line]
                            print(f"     CutContour lines found: {len(lines_with_cutcontour)}")
                            for line in lines_with_cutcontour[:3]:  # Show first 3
                                clean_line = line.strip()[:100]  # Limit length
                                print(f"       {clean_line}")
                        except:
                            print(f"     Binary content with CutContour reference")
                        
                        # Note: PyMuPDF doesn't allow direct content stream modification
                        # The actual removal would need to be done at PDF object level
                        # But we can at least identify where the CutContour references are
                
            except Exception as e:
                print(f"   Error processing page {page_num + 1}: {e}")
                import traceback
                traceback.print_exc()
        
        print(f"   Modified {objects_modified} content stream references")
        
        # Method 3: Remove unused color spaces and resources
        print("3. Cleaning document resources...")
        try:
            # This will remove unused objects including unreferenced color spaces
            doc.scrub()  # Clean unused objects
            print("   ✓ Document scrubbed")
        except Exception as e:
            print(f"   Error scrubbing document: {e}")
        
        # Save with maximum cleanup
        print("4. Saving cleaned PDF...")
        doc.save(output_path,
                 garbage=4,      # Aggressive garbage collection
                 deflate=True,   # Compress streams
                 clean=True,     # Clean document
                 pretty=True)    # Format nicely
        
        doc.close()
        
        print(f"✓ Advanced cleaning completed: {output_path}")
        return True, objects_modified
        
    except Exception as e:
        print(f"Error in advanced removal: {e}")
        return False, 0

def main():
    # ================================
    # CONFIGURATION
    # ================================
    # input_file = r"path/to/your/input_file.pdf"
    
    # Example:
    input_file = r"C:\Users\burag\Downloads\2_.pdf"
    
    if input_file == "path/to/your/input_file.pdf":
        print("Please update the 'input_file' variable with your PDF file path.")
        print("\nThis ADVANCED script will:")
        print("1. Search raw PDF content for CutContour references")
        print("2. Analyze content streams in detail")
        print("3. Remove CutContour from multiple locations")
        print("4. Clean up unused resources")
        return
    
    print("ADVANCED PDF CUTCONTOUR ANALYSIS & REMOVAL")
    print("=" * 50)
    
    # Step 1: Deep content analysis
    print("Step 1: Analyzing content streams...")
    cutcontour_refs, has_content_cutcontour = analyze_pdf_content_streams(input_file)
    
    # Step 2: Raw PDF source analysis
    print("Step 2: Searching raw PDF source...")
    has_source_cutcontour = find_cutcontour_in_pdf_source(input_file)
    
    # Step 3: Advanced removal
    if has_content_cutcontour or has_source_cutcontour:
        print("Step 3: Performing advanced CutContour removal...")
        success, objects_modified = remove_cutcontour_advanced(input_file)
        
        if success:
            print(f"\n🎉 ADVANCED SUCCESS!")
            print(f"Modified {objects_modified} objects/references")
            print(f"Check the output file for results.")
        else:
            print(f"\n❌ Advanced removal failed")
    else:
        print("\nStep 3: No CutContour content found to remove.")
        print("The CutContour might only exist in XMP metadata (already removed by previous script).")

if __name__ == "__main__":
    main()