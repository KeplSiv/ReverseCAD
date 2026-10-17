#!/usr/bin/env python3
"""Record the delivered source identity without including credentials or user scans."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
from datetime import datetime, timezone

root = Path(__file__).resolve().parents[1]
paths = set()
for folder in ("backend", "ios", "packages", "scripts", "schemas"):
    for path in (root / folder).rglob("*"):
        if not path.is_file() or any(p in {".build", "__pycache__", "xcuserdata"} for p in path.parts):
            continue
        if path.suffix in {".py", ".swift", ".sh", ".yml", ".json", ".plist", ".pbxproj", ".xcscheme"}:
            paths.add(path)
for name in ("pyproject.toml", "uv.lock", ".python-version"):
    paths.add(root / name)
files = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}
identity = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
result = {
    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    "source_identity_sha256": identity,
    "scope": "Source, generated project, schemas and sample metadata; no credentials or user scans",
    "files": files,
    "dependencies": {n: importlib.metadata.version(n) for n in ("cadquery", "cadquery-ocp", "open3d", "opencv-python-headless", "numpy", "fastapi", "pydantic", "httpx")},
}
target = root / "reports" / "build-manifest.json"
target.parent.mkdir(exist_ok=True)
target.write_text(json.dumps(result, indent=2) + "\n")
print(f"Source identity: {identity}\nSaved {target}")
