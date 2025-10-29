import fitz  # PyMuPDF

# --- config ---
PAGE_W, PAGE_H = 500, 500
RECT = (60, 60, 440, 440)  # x0, y0, x1, y1
SPOT_NAME = "CutContour"   # or "CUT"
ALT_CMYK = [0.3, 0.5, 1, 0]    # alternate (magenta) so it's obvious on-screen
HAIRLINE = True            # True -> hairline (device pixel width), False -> set an explicit width (pt)
STROKE_WIDTH_PT = 0.5      # used only if HAIRLINE is False
OUTFILE = "cut_spot_rect_3.pdf"

doc = fitz.open()
page = doc.new_page(width=PAGE_W, height=PAGE_H)

# --- 1) Create a Separation colorspace object for the spot (/CutContour or /CUT) ---
# We'll define:
#   [/Separation /CutContour /DeviceCMYK << /FunctionType 2 /Domain [0 1] /C0 [0 0 0 0] /C1 [0 1 0 0] /N 1 >>]
# The tint 1.0 = 100% of the spot; alternate is CMYK ALT_CMYK for on-screen / non-spot viewers.

sep_obj = (
    f"[ /Separation /{SPOT_NAME} /DeviceCMYK "
    f"<< /FunctionType 2 /Domain [0 1] /C0 [0 0 0 0] /C1 [{' '.join(map(str, ALT_CMYK))}] /N 1 >> ]"
)

# Allocate a new xref for the Separation object and write it
sep_xref = doc.get_new_xref()           # low-level: create a new object number
doc.update_object(sep_xref, sep_obj)        # store its content

# --- 2) Ensure the page has a /Resources dict with a /ColorSpace entry that maps /CS1 -> sep_xref ---
page_xref = page.xref

# Get /Resources; if missing, create an empty dict
res_key = doc.xref_get_key(page_xref, "Resources")[1]
if not res_key:
    res_xref = doc.get_new_xref()
    doc.update_object(res_xref, "<<>>")
    doc.xref_set_key(page_xref, "Resources", f"{res_xref} 0 R")
else:
    # It’s a reference like "123 0 R" or an inline dict. Normalize to an xref.
    if res_key.endswith(" R"):
        res_xref = int(res_key.split()[0])
    else:
        # Inline dict: move it to its own object so we can edit reliably
        res_xref = doc.get_new_xref()
        doc.update_object(res_xref, res_key)
        doc.xref_set_key(page_xref, "Resources", f"{res_xref} 0 R")

# Fetch existing ColorSpace dict (if any)
cs_key = doc.xref_get_key(res_xref, "ColorSpace")[1]
if not cs_key:
    # no /ColorSpace: create one with /CS1 mapped to our Separation object
    cs_xref = doc.get_new_xref()
    doc.update_object(cs_xref, f"<< /CS1 {sep_xref} 0 R >>")
    doc.xref_set_key(res_xref, "ColorSpace", f"{cs_xref} 0 R")
else:
    # there is a /ColorSpace entry; make sure it is an indirect object we can edit
    if cs_key.endswith(" R"):
        cs_xref = int(cs_key.split()[0])
        # Read current dict content and append /CS1 if missing
        current = doc.xref_object(cs_xref)
        # Strip "obj ... endobj" wrapper if present
        if "obj" in current and "endobj" in current:
            current = current[current.find("<<"):current.rfind(">>")+2]
        # If /CS1 not present, add it
        if "/CS1" not in current:
            updated = current[:-2] + f" /CS1 {sep_xref} 0 R >>"
            doc.update_object(cs_xref, updated)
    else:
        # Inline dictionary — convert to indirect and add /CS1
        cs_xref = doc.get_new_xref()
        base = cs_key.strip()
        if base.endswith(">>"):
            updated = base[:-2] + f" /CS1 {sep_xref} 0 R >>"
        else:
            updated = f"<< /CS1 {sep_xref} 0 R >>"
        doc.update_object(cs_xref, updated)
        doc.xref_set_key(res_xref, "ColorSpace", f"{cs_xref} 0 R")

# --- 3) Append a small content stream that uses that spot color and draws the rectangle (stroke only) ---
x0, y0, x1, y1 = RECT
w = 0 if HAIRLINE else STROKE_WIDTH_PT

# PDF drawing:
# q               save graphics state
# {w} w          line width (0 = hairline)
# /CS1 CS        set stroking color space to our Separation
# 1 SCN          set stroking color (tint = 1.0 => 100% spot)
# x y width height re   rectangle path
# S               stroke
# Q               restore
# EMC             end marked content
content = (
    "/Layer /MC0 BDC\n"  # Begin marked content (optional, for print workflows)
    "q\n"
    f"{w} w\n"
    "/CS1 CS\n"
    "1 SCN\n"
    f"{x0} {y0} {x1 - x0} {y1 - y0} re\n"
    "S\n"
    "Q\n"
    "EMC\n"  # End marked content
).encode("ascii")

# Add this as an additional page content stream
stream_xref = doc.get_new_xref()
doc.update_object(stream_xref, "<<>>")
doc.update_stream(stream_xref, content)

# Attach the stream to the page's /Contents (preserving any existing content)
cont_key = doc.xref_get_key(page_xref, "Contents")[1]
if not cont_key:
    # No content yet — set directly
    doc.xref_set_key(page_xref, "Contents", f"{stream_xref} 0 R")
else:
    # If multiple or single, normalize to an array and append our stream
    if cont_key.endswith(" R"):
        # single stream -> make an array [old new]
        old_xref = int(cont_key.split()[0])
        arr_xref = doc.get_new_xref()
        doc.update_object(arr_xref, f"[ {old_xref} 0 R {stream_xref} 0 R ]")
        doc.xref_set_key(page_xref, "Contents", f"{arr_xref} 0 R")
    elif cont_key.strip().startswith("["):
        # inline array -> append
        arr = cont_key.strip()
        updated = arr[:-1] + f" {stream_xref} 0 R ]"
        arr_xref = doc.get_new_xref()
        doc.update_object(arr_xref, updated)
        doc.xref_set_key(page_xref, "Contents", f"{arr_xref} 0 R")
    else:
        # inline stream — rare; wrap it into an array with our new stream
        old_xref = doc.get_new_xref()
        doc.update_object(old_xref, "<<>>")  # <-- Add this line
        doc.update_stream(old_xref, cont_key.encode("latin1"))
        arr_xref = doc.get_new_xref()
        doc.update_object(arr_xref, f"[ {old_xref} 0 R {stream_xref} 0 R ]")
        doc.xref_set_key(page_xref, "Contents", f"{arr_xref} 0 R")

# Add a basic ExtGState if you want to use /GS0 gs (optional)
gs_dict = "<< /GS0 << /CA 1 /ca 1 >> >>"
gs_xref = doc.get_new_xref()
doc.update_object(gs_xref, gs_dict)
doc.xref_set_key(res_xref, "ExtGState", f"{gs_xref} 0 R")

# Save the PDF
doc.save(OUTFILE)
doc.close()

print(f"Done. Wrote {OUTFILE}")
