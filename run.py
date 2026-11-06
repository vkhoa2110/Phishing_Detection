import os
from pathlib import Path
from dotenv import load_dotenv
import uvicorn

if __name__ == "__main__":
    load_dotenv(Path(__file__).with_name(".env"), override=False)
    # Keep the registered v3 baseline available for reproduction.
    profiles = {"quality-v4": "app.quality:app", "legacy": "app.main:app"}
    profile = os.getenv("PHISHLENS_PROFILE", "quality-v4")
    if profile not in profiles:
        raise SystemExit("PHISHLENS_PROFILE phải là quality-v4 hoặc legacy.")
    uvicorn.run(profiles[profile], host="127.0.0.1", port=int(os.getenv("PORT", "8000")), access_log=False)

