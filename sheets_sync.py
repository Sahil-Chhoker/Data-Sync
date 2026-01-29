import gspread
from sqlalchemy import create_engine, inspect, text
from config import settings
import time

from sync_utils import (
    load_sync_state,
    save_sync_state,
    get_data_hash,
    get_column_letter,
)

engine = create_engine(settings.DATABASE_URL)
gc = gspread.service_account(filename="credentials.json")


def sync_mysql_to_sheets(table_name, spreadsheet_id):
    """
    Sync data from MySQL to Google Sheets

    Args:
        table_name: Name of the MySQL table
        spreadsheet_id: Google Sheets ID
    """
    print(f"Starting MySQL → Sheets sync for {table_name}...")

    inspector = inspect(engine)

    if not inspector.has_table(table_name):
        print(f"Table {table_name} does not exist in MySQL")
        return

    try:
        with engine.begin() as conn:
            result = conn.execute(
                text(f"SELECT * FROM `{table_name}` ORDER BY `id` ASC")
            )
            rows = result.fetchall()
            columns = result.keys()
    except Exception as e:
        print(f"Error reading from MySQL: {e}")
        return

    if not rows:
        print(f"No data in table {table_name}")
        return

    # prepare data for sheets (exclude 'id' column)
    letter_columns = [col for col in columns if col != "id"]

    sheet_data = []
    for row in rows:
        row_dict = dict(row._mapping)
        sheet_row = []
        for col in letter_columns:
            value = row_dict.get(col, "")
            # Convert None to empty string
            sheet_row.append("" if value is None else str(value))
        sheet_data.append(sheet_row)

    # check if data has changed
    current_db_hash = get_data_hash(sheet_data)
    sync_state = load_sync_state()
    last_state = sync_state.get(table_name, {})

    current_time = time.time()
    last_sync_time = last_state.get("last_sync", 0)
    time_since_last_sync = current_time - last_sync_time

    # race condition prevention
    if last_state.get("direction") == "sheets_to_mysql" and time_since_last_sync < 5:
        print(
            f"Skipping sync - recent sheets_to_mysql sync detected ({time_since_last_sync:.1f}s ago)"
        )
        return

    if last_state.get("db_hash") == current_db_hash:
        print("No changes detected in MySQL data")
        return

    try:
        sh = gc.open_by_key(spreadsheet_id)
        worksheet = sh.get_worksheet(0)
    except Exception as e:
        print(f"❌ Error opening Google Sheet: {e}")
        return

    current_sheet_data = worksheet.get_all_values()
    current_sheet_hash = get_data_hash(current_sheet_data)

    if (
        last_state.get("sheet_hash")
        and last_state.get("sheet_hash") != current_sheet_hash
    ):
        print(
            "⚠️ Sheet was modified externally - proceeding with MySQL data as source of truth"
        )

    try:
        # Clear the entire sheet first
        worksheet.clear()

        if sheet_data:
            # Determine the range (e.g., A1:F10)
            num_rows = len(sheet_data)
            num_cols = len(letter_columns)
            end_col_letter = get_column_letter(num_cols)
            range_notation = f"A1:{end_col_letter}{num_rows}"

            worksheet.update(range_notation, sheet_data)
            print(f"Updated {num_rows} rows and {num_cols} columns to Google Sheets")
        else:
            print("No data to sync")

        # update sync state
        new_sheet_hash = get_data_hash(sheet_data)
        save_sync_state(
            table_name, current_db_hash, new_sheet_hash, current_time, "mysql_to_sheets"
        )

        print(f"MySQL → Sheets sync complete for {table_name}")

    except Exception as e:
        print(f"Error updating Google Sheet: {e}")
