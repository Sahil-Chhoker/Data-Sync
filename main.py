from fastapi import FastAPI, Request
from fastapi_utils.tasks import repeat_every
from config import settings
import time

from sync_utils import load_sync_state
from mysql_sync import sync_sheets_to_mysql
from sheets_sync import sync_mysql_to_sheets

app = FastAPI()


@app.on_event("startup")
@repeat_every(seconds=30)
async def periodic_mysql_to_sheets_sync():
    """Automatically sync MySQL to Sheets every 30 seconds if there are changes"""
    sync_mysql_to_sheets("Sync7", settings.SPREADSHEET_ID)


@app.post("/webhooks/sheets")
async def receive_sheet_update(request: Request):
    """Webhook endpoint triggered by Google Sheets changes"""
    try:
        # Check sync state to prevent race conditions
        sync_state = load_sync_state()
        last_state = sync_state.get("Sync", {})
        current_time = time.time()
        last_sync_time = last_state.get("last_sync", 0)
        time_since_last_sync = current_time - last_sync_time

        # If last sync was from sheets_sync and happened less than 5 seconds ago, skip
        if (
            last_state.get("direction") == "mysql_to_sheets"
            and time_since_last_sync < 5
        ):
            print("Skipping webhook - recent mysql_to_sheets sync detected")
            return {"status": "skipped", "reason": "recent_mysql_sync"}

        # Perform the sync
        result = sync_sheets_to_mysql("Sync7", settings.SPREADSHEET_ID)

        return result

    except Exception as e:
        print(f"Sync Error: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/webhooks/mysql-to-sheets/{table_name}")
async def trigger_mysql_to_sheets(table_name: str):
    """Manual endpoint to trigger MySQL → Sheets sync"""
    try:
        sync_mysql_to_sheets(table_name, settings.SPREADSHEET_ID)
        return {"status": "success", "table": table_name}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}
