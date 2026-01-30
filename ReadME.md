# Data-Sync: MySQL ↔ Google Sheets Real-time Sync

A production-grade bidirectional synchronization system between MySQL and Google Sheets. Edit your spreadsheet, see it in the database. Update the database, see it in the sheet. Built to handle real-world edge cases, race conditions, and multiplayer collaboration.

## Live Demo

- **Editable Google Sheet**: https://docs.google.com/spreadsheets/d/19sZT1fhtIu6Mv7iT_WWaf4pQ0xvMlVVB8DKil1JJvmA/edit?pli=1&gid=0#gid=0
- **Database Viewer**: https://mysqlmanager.streamlit.app/

Try editing the Google Sheet and watch the changes appear in the database viewer within seconds. Or use the viewer to see how database updates reflect back in the sheet.

## Architecture

```
Google Sheets ←→ Apps Script Trigger ←→ FastAPI (Render) ←→ MySQL (Railway)
                                           ↓
                                    Streamlit Viewer
```

**Key Design Decisions:**

1. **Event-driven Sheets→MySQL**: Google Apps Script `onEdit` trigger fires webhook immediately when users edit cells, providing fast syncs with multiplayer support.

2. **Polling for MySQL→Sheets**: 30-second polling interval checks for database changes. Polling was chosen over triggers because it's simpler to deploy and maintain across hosting platforms.

3. **State-based conflict resolution**: Uses MD5 hashing and timestamps to detect changes and prevent infinite sync loops. Each sync records its direction and timestamp to skip redundant operations.

4. **Schema evolution**: Dynamically adds rows as they appear in sheets and removes AUTO_INCREMENT from id columns which was perventing from rewriting entire data.

## Tech Stack

- **Backend**: FastAPI with SQLAlchemy for async operations and connection pooling
- **Database**: MySQL on Railway (easily swappable to any MySQL-compatible database)
- **Sheets API**: Google Apps Script for triggers + gspread for Python integration
- **Viewer & Editor**: Streamlit with auto-refresh for real-time monitoring and updating the MySQL database.
- **Hosting**: Render (API), Railway (DB), Streamlit Cloud (viewer & editor)

## Project Structure

```
├── main.py                    # FastAPI app, endpoints, periodic tasks
├── mysql_sync.py              # Sheets→MySQL sync with schema evolution
├── sheets_sync.py             # MySQL→Sheets sync with change detection
├── sync_utils.py              # State management, hashing, utilities
├── streamlit_app.py           # Real-time database viewer & editor
├── config.py                  # Environment configuration
├── credentials.json           # Google service account key
└── sync_state.json            # Sync state tracking (auto-generated)
```

## Edge Cases Handled

**Data Integrity:**
- Empty cell handling (converts to NULL in MySQL)
- Variable row lengths (pads with empty strings)
- Row deletions (removes rows from DB when deleted from sheet)
- Column additions (dynamically adds new columns without downtime)

**Concurrency & Race Conditions:**
- Multiplayer sheet edits tracked with user email and timestamps
- 5-second sync cooldown prevents infinite loops
- Data hashing detects actual changes vs. no-op syncs
- Direction tracking (sheets_to_mysql vs mysql_to_sheets) prevents conflicts

**Schema Evolution:**
- Automatic table creation on first sync
- Removes AUTO_INCREMENT from id columns (required for manual row management)
- Adds missing columns without data loss
- Supports arbitrary column count (A, B, C... Z, AA, AB...)

**Robustness:**
- Connection pooling for database efficiency
- Background task execution for non-blocking operations
- Comprehensive error handling with informative logs
- Health check endpoint for monitoring

## Setup

### Prerequisites

```bash
pip install -r requirements.txt
```

### 1. Google Service Account

1. Create project in Google Cloud Console
2. Enable Google Sheets API
3. Create service account, download `credentials.json`
4. Share your Google Sheet with the service account email

### 2. Configure Environment

```python
# .env
SPREADSHEET_ID="your_spreadsheet_id"
DATABASE_URL="your_database_url"

```

### 3. Google Apps Script Trigger

In your Google Sheet: Extensions > Apps Script

```javascript
function handleMultiplayerSync(e) {
  if (!e) return;

  var payload = {
    range: {
      rowStart: e.range.getRow(),
      columnStart: e.range.getColumn()
    },
    value: e.value || "",
    oldValue: e.oldValue || "",
    userEmail: Session.getActiveUser().getEmail() || "collaborator",
    timestamp: new Date().toISOString()
  };

  var options = {
    method: "post",
    contentType: "application/json",
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  };

  UrlFetchApp.fetch("https://your-api-url/webhooks/sheets", options);
}
```
**NOTE**: If API is not hosted you can use ngrok to get the API URL for testing.

Set up installable trigger: Trigger type = On Edit

### 4. Run

```bash
# API
fastapi run main.py

# Database viewer and editor
streamlit run streamlit_app.py
```

## How Sync Works

### Sheets → MySQL (Event-Driven)

1. User edits cell in Google Sheets
2. Apps Script trigger captures change with user email and timestamp
3. Webhook sends full sheet data to `/webhooks/sheets`
4. System compares with last sync state (checks if MySQL just synced)
5. If safe, updates MySQL: upserts rows, adds columns, deletes removed rows
6. Records sync state with hash and timestamp

### MySQL → Sheets (Polling)

1. Every 30 seconds, FastAPI checks MySQL data
2. Computes hash of current data
3. Compares with last known hash and checks last sync direction
4. If data changed AND sheets didn't just sync (5-second buffer):
   - Clears sheet
   - Writes MySQL data
   - Records sync state

### Conflict Resolution

Uses a simple "last write wins" approach with buffering:
- Each sync records timestamp and direction
- Opposite direction waits 5 seconds before attempting sync
- Data hashing prevents unnecessary syncs when nothing changed
- In true conflicts (simultaneous edits), most recent edit wins

## Scalability Considerations

**Current Implementation:**
- Single-table sync with hardcoded table names
- Polling interval of 30 seconds
- Synchronous database operations

**Production Scaling Path:**

1. **Multi-table support**: Map different sheets to different tables through config files instead of hardcoding table names.

2. **Real-time updates**: Use MySQL binlog or triggers to detect changes instantly, then push to sheets via WebSocket instead of polling every 30 seconds.

3. **Queue-based processing**: Add a message queue (Redis/RabbitMQ) so webhooks don't block, and use background workers to handle sync jobs asynchronously.

4. **Performance improvements**: Add database indexes, use connection pooling, and cache sync state in Redis to reduce database hits.

The current architecture is simple by design but can scale up without rewriting everything.

## API Endpoints

- `POST /webhooks/sheets` - Sheets change webhook (triggered by Apps Script)
- `POST /webhooks/mysql-to-sheets/{table_name}` - Manual MySQL sync trigger
- `GET /health` - Service health check

## Database Schema

Tables auto-generate with this structure:

```sql
CREATE TABLE `Sync7` (
  `id` INT PRIMARY KEY,      -- Sheet row number
  `A` TEXT,                   -- Column A
  `B` TEXT,                   -- Column B
  `C` TEXT,                   -- Column C
  ...
)
```

Sheet rows map to `id`, sheet columns map to `A`, `B`, `C`, etc. This maintains positional integrity while allowing arbitrary column expansion.

## Multiplayer Optimization

- Concurrent edits tracked via user email in webhook payload
- Race condition prevention with sync direction tracking
- Idempotent operations (same edit twice = same result)
- Fast webhook response (< 100ms) to prevent trigger timeouts


## Known Limitations
- Unauthorized users can't trigger update in MySQL database, therefore their updates are overwritten by the database after 30 seconds.
- Databse viewing and editing has limited functionality.
- 30-second polling means MySQL changes take up to 30s to appear in sheet
- Last write wins for simultaneous conflicting edits
- Single spreadsheet/table pairing
- No audit log or version history
- Large datasets (>10k rows) may hit performance limits
