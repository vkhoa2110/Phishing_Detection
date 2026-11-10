import os
from pathlib import Path
from dotenv import load_dotenv
import uvicorn

if __name__ == "__main__":
    load_dotenv(Path(__file__).with_name(".env"), override=False)
    profiles = {
        "stable": "app.main:app",
        "quality-v4": "app.main:app",
        "candidate": "app.api.interaction:app",
        "candidate-v5": "app.api.candidate:app",
        "legacy": "app.api.legacy:app",
    }
    profile = os.getenv("PHISHLENS_PROFILE", "stable")
    if profile not in profiles:
        raise SystemExit("PHISHLENS_PROFILE phải là stable, candidate, candidate-v5 hoặc legacy.")
    uvicorn.run(profiles[profile], host="127.0.0.1", port=int(os.getenv("PORT", "8000")), access_log=False)

