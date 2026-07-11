"""Quick sanity test for Tesseract + Gemini Vision OCR wiring."""
import io
import os
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont

load_dotenv()

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app.utils.document_parser import DocumentParser, _format_combined_ocr_output
from app.utils.vision_ocr import extract_text_with_gemini_vision


def make_test_image(path: Path) -> None:
    img = Image.new("RGB", (420, 120), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((10, 20), "Policy ID: HRX-2026-001", fill="black")
    draw.text((10, 55), "Premium: Rs 12,500", fill="black")
    draw.text((10, 90), "Tamil sample: (unicode not rendered in default font)", fill="black")
    img.save(path, format="PNG")


def main() -> None:
    print("=== _format_combined_ocr_output ===")
    combined = _format_combined_ocr_output("partial eng 123", "Full Gemini text here")
    print(combined)
    print()

    with tempfile.TemporaryDirectory() as tmp:
        img_path = Path(tmp) / "test_ocr.png"
        make_test_image(img_path)

        parser = DocumentParser()
        print("=== _parse_image (Tesseract + Gemini) ===")
        result = parser._parse_image(img_path)
        print(result["text"])
        print()

        with open(img_path, "rb") as f:
            image_bytes = f.read()

        tesseract_only = ""
        try:
            import pytesseract
            tesseract_only = pytesseract.image_to_string(
                Image.open(io.BytesIO(image_bytes)), config=parser.ocr_config
            ).strip()
        except Exception as exc:
            tesseract_only = f"(Tesseract unavailable: {exc})"

        print("=== extract_text_with_gemini_vision direct ===")
        if os.getenv("GEMINI_AI_API_KEY"):
            gemini_text = extract_text_with_gemini_vision(image_bytes, tesseract_only)
            print(gemini_text or "(empty Gemini response)")
        else:
            print("GEMINI_AI_API_KEY not set — skipped live Gemini call")
            fallback = extract_text_with_gemini_vision(image_bytes, tesseract_only)
            print(f"Fallback returned: {fallback!r} (expected empty string on missing key)")


if __name__ == "__main__":
    main()
