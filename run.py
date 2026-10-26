import os
from pathlib import Path
from dotenv import load_dotenv
import uvicorn

if __name__ == "__main__":
    load_dotenv(Path(__file__).with_name(".env"), override=False)
    # Chỉ mở trên máy của bạn. Chưa dùng bản baseline này làm dịch vụ công khai.
    uvicorn.run("app.main:app", host="127.0.0.1", port=int(os.getenv("PORT", "8000")), access_log=False)

