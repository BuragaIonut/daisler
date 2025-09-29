import pymupdf

pdf_file_path = r"C:\Users\burag\VercelDaisler\daisler\api\cut line.pdf"
my_pdf = pymupdf.open(pdf_file_path)
color_space = pymupdf.Colorspace(pymupdf.CS_CMYK)
first_page = my_pdf[0]
# first_page.draw_rect(pymupdf.Rect(60, 60, 440, 440), color=(1,), colorspace=color_space, fill=None, stroke_opacity=1, line_width=0.5)

new_page = first_page.set_cropbox(pymupdf.Rect(0, 0, 500, 500))
print(new_page)



