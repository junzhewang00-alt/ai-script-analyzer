import os

MAX_SCRIPT_LENGTH = 30000


def parse_text(text: str) -> str:
    """Clean and truncate raw text input."""
    text = text.strip()
    if not text:
        raise ValueError("剧本内容为空")
    if len(text) > MAX_SCRIPT_LENGTH:
        text = text[:MAX_SCRIPT_LENGTH] + "\n\n[剧本过长，已截断至前30000字符...]"
    return text


def parse_file(filepath: str) -> str:
    """Parse uploaded file (txt/pdf) to plain text."""
    ext = os.path.splitext(filepath)[1].lower()

    if ext == ".txt":
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    elif ext == ".pdf":
        from PyPDF2 import PdfReader
        reader = PdfReader(filepath)
        pages = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
        content = "\n".join(pages)
    elif ext == ".fdx":
        # Final Draft XML — extract <Text> elements
        import xml.etree.ElementTree as ET
        tree = ET.parse(filepath)
        root = tree.getroot()
        texts = root.iter("{http://www.finaldraft.com/fdx7}Text")
        content = "\n".join(t.text or "" for t in texts)
    else:
        raise ValueError(f"不支持的文件格式: {ext}，支持 .txt / .pdf / .fdx")

    content = content.strip()
    if not content:
        raise ValueError("文件中未解析出有效文本")

    if len(content) > MAX_SCRIPT_LENGTH:
        content = content[:MAX_SCRIPT_LENGTH] + "\n\n[剧本过长，已截断至前30000字符...]"

    return content
