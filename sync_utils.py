import json
import hashlib

SYNC_STATE_FILE = "sync_state.json"


def get_column_letter(n):
    """Convert column number to letter (1->A, 2->B, etc.)"""
    result = ""
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        result = chr(65 + remainder) + result
    return result


def load_sync_state():
    """Load the last sync state from file"""
    try:
        with open(SYNC_STATE_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_sync_state(table_name, db_hash, sheet_hash, timestamp, direction):
    """
    Save the current sync state

    Args:
        table_name: Name of the table being synced
        db_hash: Hash of the database data
        sheet_hash: Hash of the sheet data
        timestamp: Unix timestamp of the sync
        direction: Either "sheets_to_mysql" or "mysql_to_sheets"
    """
    state = load_sync_state()
    state[table_name] = {
        "db_hash": db_hash,
        "sheet_hash": sheet_hash,
        "last_sync": timestamp,
        "direction": direction,
    }
    with open(SYNC_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def get_data_hash(data):
    """Generate MD5 hash of data for change detection"""
    return hashlib.md5(json.dumps(data, sort_keys=True).encode()).hexdigest()
