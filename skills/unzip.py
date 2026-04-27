import zipfile
import sys
from pathlib import Path


def unpack(zip_path: str, dest: str = None) -> Path:
    zip_path = Path(zip_path)
    if not zip_path.exists():
        raise FileNotFoundError(f"File not found: {zip_path}")
    if not zipfile.is_zipfile(zip_path):
        raise ValueError(f"Not a valid zip file: {zip_path}")

    dest_path = Path(dest) if dest else zip_path.parent / zip_path.stem
    dest_path.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest_path)
        print(f"Extracted {len(zf.namelist())} file(s) to: {dest_path}")

    return dest_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python skills/unzip.py <file.zip> [destination]")
        sys.exit(1)

    zip_file = sys.argv[1]
    destination = sys.argv[2] if len(sys.argv) > 2 else None
    unpack(zip_file, destination)
