import json
import re
from pathlib import Path
from datetime import datetime

import requests
from bs4 import BeautifulSoup

CONTEXT_DIR = Path(__file__).parent.parent / "context"
INDEX_FILE = CONTEXT_DIR / "index.json"


def _ensure_dirs():
    CONTEXT_DIR.mkdir(exist_ok=True)


def _load_index() -> list[dict]:
    if INDEX_FILE.exists():
        return json.loads(INDEX_FILE.read_text())
    return []


def _save_index(entries: list[dict]):
    INDEX_FILE.write_text(json.dumps(entries, indent=2))


def fetch_and_store(url: str, label: str = "") -> dict:
    """Fetch a webpage, extract its text, and store it as context."""
    _ensure_dirs()

    response = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    text = soup.get_text(separator="\n")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    slug = re.sub(r"[^\w]+", "_", url)[:60]
    filename = f"{slug}.txt"
    (CONTEXT_DIR / filename).write_text(text, encoding="utf-8")

    entry = {
        "url": url,
        "label": label or soup.title.string.strip() if soup.title else url,
        "file": filename,
        "fetched_at": datetime.now().isoformat(),
        "chars": len(text),
    }

    index = _load_index()
    index = [e for e in index if e["url"] != url]  # replace if exists
    index.append(entry)
    _save_index(index)

    return entry


def delete_context(url: str):
    index = _load_index()
    entry = next((e for e in index if e["url"] == url), None)
    if entry:
        f = CONTEXT_DIR / entry["file"]
        if f.exists():
            f.unlink()
        index = [e for e in index if e["url"] != url]
        _save_index(index)


def load_all_context(max_chars_per_doc: int = 3000) -> str:
    """Return all stored context as a single string to inject into prompts."""
    index = _load_index()
    if not index:
        return ""
    parts = ["## Firm-Specific Context & Compliance Guidelines\n"]
    for entry in index:
        f = CONTEXT_DIR / entry["file"]
        if f.exists():
            content = f.read_text(encoding="utf-8")[:max_chars_per_doc]
            parts.append(f"### {entry['label']}\nSource: {entry['url']}\n\n{content}\n")
    return "\n---\n".join(parts)


def list_context() -> list[dict]:
    return _load_index()
