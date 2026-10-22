import os
import sys
import tempfile
from pathlib import Path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))
from utils.document_parser import DocumentParser
from utils.table_processor import TableProcessor

def test_document_parser():
    parser = DocumentParser()
    print('=== Document Parser Test ===\n')
    print('Supported file extensions:')
    for ext in parser.supported_extensions.keys():
        print(f'  - {ext}')
    print()
    print('OCR Support:')
    try:
        import pytesseract
        from PIL import Image
        print('  ✓ OCR (pytesseract) available')
    except ImportError:
        print('  ✗ OCR (pytesseract) not available')
    print('\nTable Processor Support:')
    try:
        from utils.table_processor import TableProcessor
        print('  ✓ Table processor available')
    except ImportError:
        print('  ✗ Table processor not available')
    print('\nLibrary Support:')
    libraries = [('python-docx', 'DOCX parsing'), ('openpyxl', 'XLSX parsing'), ('pandas', 'Data analysis'), ('docx2txt', 'DOC parsing'), ('xlrd', 'XLS parsing'), ('Pillow', 'Image processing')]
    for lib_name, description in libraries:
        try:
            __import__(lib_name.replace('-', '_'))
            print(f'  ✓ {lib_name}: {description}')
        except ImportError:
            print(f'  ✗ {lib_name}: {description}')
    print('\n=== Test Complete ===')

def create_test_files():
    test_dir = Path('test_files')
    test_dir.mkdir(exist_ok=True)
    with open(test_dir / 'test.txt', 'w') as f:
        f.write('This is a test text file.\nIt contains multiple lines.\n')
    with open(test_dir / 'test.cs', 'w') as f:
        f.write('\nusing System;\n\nnamespace TestProject\n{\n    public class TestClass\n    {\n        public string TestProperty { get; set; }\n        \n        public void TestMethod()\n        {\n            Console.WriteLine("Hello, World!");\n        }\n    }\n}\n')
    with open(test_dir / 'test.config', 'w') as f:
        f.write('\n<?xml version="1.0" encoding="utf-8"?>\n<configuration>\n  <appSettings>\n    <add key="TestKey" value="TestValue" />\n  </appSettings>\n  <connectionStrings>\n    <add name="TestConnection" connectionString="Server=localhost;Database=test;" />\n  </connectionStrings>\n</configuration>\n')
    print("Test files created in 'test_files' directory")
    return test_dir

def test_file_parsing():
    test_dir = create_test_files()
    parser = DocumentParser()
    print('\n=== File Parsing Test ===\n')
    test_files = [('test.txt', 'Text file'), ('test.cs', 'C# file'), ('test.config', 'Config file')]
    for filename, description in test_files:
        file_path = test_dir / filename
        if file_path.exists():
            print(f'Testing {description} ({filename}):')
            try:
                result = parser.extract_text_from_file(str(file_path))
                print(f"  File type: {result['file_type']}")
                print(f"  Text length: {len(result['text'])} characters")
                print(f"  Tables found: {len(result['tables'])}")
                print(f"  Preview: {result['text'][:100]}...")
            except Exception as e:
                print(f'  Error: {e}')
            print()

def test_table_processor():
    print('\n=== Table Processor Test ===\n')
    try:
        processor = TableProcessor()
        print('✓ Table processor initialized successfully')
        config = processor.table_analysis_config
        print(f'Configuration:')
        for key, value in config.items():
            print(f'  {key}: {value}')
    except Exception as e:
        print(f'✗ Error initializing table processor: {e}')

def main():
    print('Document Parser and OCR Support Test Suite')
    print('=' * 50)
    test_document_parser()
    test_table_processor()
    test_file_parsing()
    print('\n' + '=' * 50)
    print('Test suite completed!')
if __name__ == '__main__':
    main()