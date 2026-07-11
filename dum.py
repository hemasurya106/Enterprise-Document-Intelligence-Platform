import pytesseract, PIL, subprocess, sys
print("pytesseract OK")
print("Pillow version:", PIL.__version__)
subprocess.check_call(["tesseract", "--version"])