import io
from pathlib import Path

def extract_resume_text(file_input):
    """
    Extract text from a resume file.
    file_input can be a string/Path filename or a file-like object with .name and .getvalue() or .read().
    Supports PDF, DOCX, and TXT formats.
    """
    if isinstance(file_input, (str, Path)):
        p = Path(file_input)
        name = p.name.lower()
        data = p.read_bytes()
    elif hasattr(file_input, "getvalue"):
        name = getattr(file_input, "name", "").lower()
        data = file_input.getvalue()
    elif hasattr(file_input, "read"):
        name = getattr(file_input, "name", "").lower()
        data = file_input.read()
    else:
        raise ValueError("Unsupported input type for resume extraction.")

    if name.endswith(".pdf"):
        try:
            import pymupdf
            doc = pymupdf.open(stream=data, filetype="pdf")
            return "\n".join(page.get_text() for page in doc)
        except ImportError:
            try:
                import fitz
                doc = fitz.open(stream=data, filetype="pdf")
                return "\n".join(page.get_text() for page in doc)
            except ImportError:
                raise ImportError("PyMuPDF is required to parse PDF resumes. Run: pip install pymupdf")

    if name.endswith(".docx"):
        try:
            from docx import Document
            doc = Document(io.BytesIO(data))
            return "\n".join(p.text for p in doc.paragraphs)
        except ImportError:
            # Fallback: extract XML text from docx zip if python-docx is not installed
            try:
                import zipfile
                import xml.etree.ElementTree as ET
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    xml_content = z.read("word/document.xml")
                    tree = ET.fromstring(xml_content)
                    texts = [node.text for node in tree.iter() if node.text]
                    return " ".join(texts)
            except Exception:
                raise ImportError("python-docx is required to parse DOCX resumes. Run: pip install python-docx")

    if name.endswith(".txt"):
        return data.decode("utf-8", errors="replace")

    raise ValueError("Supported resume formats: PDF, DOCX, TXT")

