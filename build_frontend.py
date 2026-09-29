import json
import os
import shutil
from pathlib import Path
from urllib.parse import urlsplit


PROJECT_ROOT = Path(__file__).resolve().parent
configured_api_url = os.getenv("API_BASE_URL", "").strip()
if not configured_api_url:
    raise RuntimeError("Set API_BASE_URL to the deployed FastAPI service host or URL.")

if "://" not in configured_api_url:
    configured_api_url = f"https://{configured_api_url}"

api_url = urlsplit(configured_api_url)
if (
    api_url.scheme not in {"http", "https"}
    or not api_url.netloc
    or api_url.username
    or api_url.password
    or api_url.path not in {"", "/"}
    or api_url.query
    or api_url.fragment
):
    raise ValueError(
        "API_BASE_URL must be an HTTP(S) origin without credentials, path, or query."
    )

api_origin = f"{api_url.scheme}://{api_url.netloc}"
output_directory = PROJECT_ROOT / ".render-frontend"
output_directory.mkdir(exist_ok=True)
for filename in ("index.html", "style.css", "script.js"):
    shutil.copyfile(PROJECT_ROOT / filename, output_directory / filename)

(output_directory / "frontend-config.js").write_text(
    f"window.API_BASE_URL = {json.dumps(api_origin)};\n",
    encoding="utf-8",
)
