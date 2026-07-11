#!/usr/bin/env python3
"""
Test script for the new document parser with support for multiple file formats and OCR.
"""

import os
import sys
import tempfile
from pathlib import Path

# Add the app directory to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from utils.document_parser import DocumentParser
from utils.table_processor import TableProcessor


def test_document_parser():
    """Test the document parser with different file types."""
    parser = DocumentParser()
    
    print("=== Document Parser Test ===\n")
    
    # Test supported extensions
    print("Supported file extensions:")
    for ext in parser.supported_extensions.keys():
        print(f"  - {ext}")
    print()
    
    # Test OCR availability
    print("OCR Support:")
    try:
        import pytesseract
        from PIL import Image
        print("  ✓ OCR (pytesseract) available")
    except ImportError:
        print("  ✗ OCR (pytesseract) not available")
    
    # Test table processor availability
    print("\nTable Processor Support:")
    try:
        from utils.table_processor import TableProcessor
        print("  ✓ Table processor available")
    except ImportError:
        print("  ✗ Table processor not available")
    
    # Test library availability
    print("\nLibrary Support:")
    libraries = [
        ("python-docx", "DOCX parsing"),
        ("openpyxl", "XLSX parsing"),
        ("pandas", "Data analysis"),
        ("docx2txt", "DOC parsing"),
        ("xlrd", "XLS parsing"),
        ("Pillow", "Image processing")
    ]
    
    for lib_name, description in libraries:
        try:
            __import__(lib_name.replace("-", "_"))
            print(f"  ✓ {lib_name}: {description}")
        except ImportError:
            print(f"  ✗ {lib_name}: {description}")
    
    print("\n=== Test Complete ===")


def create_test_files():
    """Create test files for different formats."""
    test_dir = Path("test_files")
    test_dir.mkdir(exist_ok=True)
    
    # Create a simple text file
    with open(test_dir / "test.txt", "w") as f:
        f.write("This is a test text file.\nIt contains multiple lines.\n")
    
    # Create a simple .NET file
    with open(test_dir / "test.cs", "w") as f:
        f.write("""
using System;

namespace TestProject
{
    public class TestClass
    {
        public string TestProperty { get; set; }
        
        public void TestMethod()
        {
            Console.WriteLine("Hello, World!");
        }
    }
}
""")
    
    # Create a simple .NET config file
    with open(test_dir / "test.config", "w") as f:
        f.write("""
<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <appSettings>
    <add key="TestKey" value="TestValue" />
  </appSettings>
  <connectionStrings>
    <add name="TestConnection" connectionString="Server=localhost;Database=test;" />
  </connectionStrings>
</configuration>
""")
    
    print("Test files created in 'test_files' directory")
    return test_dir


def test_file_parsing():
    """Test parsing of different file types."""
    test_dir = create_test_files()
    parser = DocumentParser()
    
    print("\n=== File Parsing Test ===\n")
    
    test_files = [
        ("test.txt", "Text file"),
        ("test.cs", "C# file"),
        ("test.config", "Config file")
    ]
    
    for filename, description in test_files:
        file_path = test_dir / filename
        if file_path.exists():
            print(f"Testing {description} ({filename}):")
            try:
                result = parser.extract_text_from_file(str(file_path))
                print(f"  File type: {result['file_type']}")
                print(f"  Text length: {len(result['text'])} characters")
                print(f"  Tables found: {len(result['tables'])}")
                print(f"  Preview: {result['text'][:100]}...")
            except Exception as e:
                print(f"  Error: {e}")
            print()


def test_table_processor():
    """Test the table processor functionality."""
    print("\n=== Table Processor Test ===\n")
    
    try:
        processor = TableProcessor()
        print("✓ Table processor initialized successfully")
        
        # Test configuration
        config = processor.table_analysis_config
        print(f"Configuration:")
        for key, value in config.items():
            print(f"  {key}: {value}")
        
    except Exception as e:
        print(f"✗ Error initializing table processor: {e}")


def main():
    """Run all tests."""
    print("Document Parser and OCR Support Test Suite")
    print("=" * 50)
    
    # Test basic functionality
    test_document_parser()
    
    # Test table processor
    test_table_processor()
    
    # Test file parsing
    test_file_parsing()
    
    print("\n" + "=" * 50)
    print("Test suite completed!")


if __name__ == "__main__":
    main() 