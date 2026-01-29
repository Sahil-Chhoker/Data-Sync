import gspread
from sqlalchemy import create_engine, inspect, text
from config import settings
import time

from sync_utils import save_sync_state, get_data_hash, get_column_letter

engine = create_engine(settings.DATABASE_URL)
gc = gspread.service_account(filename="credentials.json")


def sync_sheets_to_mysql(table_name, spreadsheet_id):
    """
    Sync data from Google Sheets to MySQL

    Args:
        table_name: Name of the MySQL table
        spreadsheet_id: Google Sheets ID

    Returns:
        dict: Status of the sync operation
    """
    print(f"Starting Sheets → MySQL sync for {table_name}...")

    try:
        sh = gc.open_by_key(spreadsheet_id)
        worksheet = sh.get_worksheet(0)
        all_values = worksheet.get_all_values()

        if not all_values:
            print("No data in sheet")
            return {"status": "ignored", "reason": "no_data"}
    except Exception as e:
        print(f"Error reading Google Sheet: {e}")
        return {"status": "error", "message": str(e)}

    max_cols = max(len(row) for row in all_values)
    col_names = [get_column_letter(i + 1) for i in range(max_cols)]

    # Perform the sync
    try:
        _sync_to_mysql_raw(table_name, col_names, all_values)

        # save sync state
        sheet_hash = get_data_hash(all_values)
        save_sync_state(table_name, "", sheet_hash, time.time(), "sheets_to_mysql")

        print(f"Sheets → MySQL sync complete for {table_name}")
        return {"status": "success", "rows": len(all_values)}

    except Exception as e:
        print(f"Error syncing to MySQL: {e}")
        return {"status": "error", "message": str(e)}


def _sync_to_mysql_raw(table_name, col_names, all_values):
    """Internal function to perform the actual MySQL sync"""
    inspector = inspect(engine)

    # create table if it doesn't exist
    if not inspector.has_table(table_name):
        with engine.begin() as conn:
            conn.execute(text(f"CREATE TABLE `{table_name}` (`id` INT PRIMARY KEY)"))
            print(f"Created table {table_name}")

    # remove auto-increment from id column if exists
    with engine.begin() as conn:
        try:
            result = conn.execute(text(f"SHOW CREATE TABLE `{table_name}`"))
            create_statement = result.fetchone()[1]

            if "AUTO_INCREMENT" in create_statement.upper():
                print("🔧 Removing AUTO_INCREMENT from id column...")
                conn.execute(
                    text(f"ALTER TABLE `{table_name}` MODIFY COLUMN `id` INT NOT NULL")
                )
                print("id column is now a regular integer")
        except Exception as e:
            print(f"Could not modify id column: {e}")

    # add missing columns
    existing_cols = [c["name"] for c in inspector.get_columns(table_name)]

    with engine.begin() as conn:
        for col in col_names:
            if col not in existing_cols:
                print(f"Adding column: {col}")
                conn.execute(
                    text(f"ALTER TABLE `{table_name}` ADD COLUMN `{col}` TEXT")
                )

    # delete unused rows (rows beyond sheet data)
    total_sheet_rows = len(all_values)

    with engine.begin() as conn:
        result = conn.execute(
            text(f"DELETE FROM `{table_name}` WHERE `id` > :max_id"),
            {"max_id": total_sheet_rows},
        )
        deleted_count = result.rowcount
        if deleted_count > 0:
            print(f"Deleted {deleted_count} unused rows from database")

    # upsert data - sync all columns for each row
    with engine.begin() as conn:
        for idx, row in enumerate(all_values):
            row_id = idx + 1

            # Pad the row with empty strings if shorter than max columns
            padded_row = row + [""] * (len(col_names) - len(row))

            cols_to_use = ["id"] + col_names

            col_str = ", ".join([f"`{c}`" for c in cols_to_use])
            placeholders = ", ".join([f":{c}" for c in cols_to_use])

            # Update all columns except id on duplicate
            update_str = ", ".join(
                [f"`{c}`=VALUES(`{c}`)" for c in cols_to_use if c != "id"]
            )

            sql = text(f"""
                INSERT INTO `{table_name}` ({col_str}) 
                VALUES ({placeholders}) 
                ON DUPLICATE KEY UPDATE {update_str}
            """)

            # Build parameters - use None for cleared cells
            params = {"id": row_id}
            for i, col in enumerate(col_names):
                value = padded_row[i] if padded_row[i] else None
                params[col] = value

            conn.execute(sql, params)

    print(f"Sync Complete for {table_name}. Total rows: {len(all_values)}")
