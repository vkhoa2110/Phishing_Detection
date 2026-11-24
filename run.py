import os
from pathlib import Path
from dotenv import load_dotenv
import uvicorn

if __name__ == "__main__":
    load_dotenv(Path(__file__).with_name(".env"), override=False)
    profiles = {
        "stable": "app.api.runtime:create_stable_app",
        "quality-v4": "app.api.runtime:create_stable_app",
        "candidate": "app.api.runtime:create_candidate_app",
        "focused": "app.api.runtime:create_focused_app",
        "verifier-shadow": "app.api.runtime:create_verifier_shadow_app",
        "candidate-v5": "app.api.runtime:create_v5_app",
        "legacy": "app.api.runtime:create_legacy_app",
    }
    profile = os.getenv("PHISHLENS_PROFILE", "stable")
    if profile not in profiles:
        raise SystemExit("PHISHLENS_PROFILE phải là " + ", ".join(profiles) + ".")
    uvicorn.run(profiles[profile], factory=True, host="127.0.0.1", port=int(os.getenv("PORT", "8000")), access_log=False)

