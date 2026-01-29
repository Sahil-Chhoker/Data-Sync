import gspread
from fastapi import FastAPI, Request
from sqlalchemy import create_engine, MetaData, Table, inspect, text
from config import settings

app = FastAPI()

engine = create_engine(settings.DATABASE_URL)
metadata = MetaData()
gc = gspread.service_account(filename='credentials.json')

def get_column_letter(n):
    result = ""
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        result = chr(65 + remainder) + result
    return result

@app.post("/webhooks/sheets")
async def receive_sheet_update(request: Request):
    try:
        sh = gc.open_by_key(settings.SPREADSHEET_ID)
        worksheet = sh.get_worksheet(0)
        all_values = worksheet.get_all_values()
        
        if not all_values:
            return {"status": "ignored"}

        # Determine column letters based on the widest row
        max_cols = max(len(row) for row in all_values)
        col_names = [get_column_letter(i+1) for i in range(max_cols)]

        sync_to_mysql_raw("Sync7", col_names, all_values)
        
        return {"status": "success"}
    except Exception as e:
        print(f"Sync Error: {e}")
        return {"status": "error", "message": str(e)}

def sync_to_mysql_raw(table_name, col_names, all_values):
    inspector = inspect(engine)
    
    # create table if it doesn't exist
    if not inspector.has_table(table_name):
        with engine.begin() as conn:
            conn.execute(text(f"CREATE TABLE `{table_name}` (`id` INT PRIMARY KEY)"))
            print(f"Created table {table_name}")
    
    # remove AUTO_INCREMENT from id column if exists
    with engine.begin() as conn:
        try:
            result = conn.execute(text(f"SHOW CREATE TABLE `{table_name}`"))
            create_statement = result.fetchone()[1]
            
            if "AUTO_INCREMENT" in create_statement.upper():
                print(f"Removing AUTO_INCREMENT from id column...")
                conn.execute(text(f"ALTER TABLE `{table_name}` MODIFY COLUMN `id` INT NOT NULL"))
                print(f"id column is now a regular integer")
        except Exception as e:
            print(f"Could not modify id column: {e}")
    
    # add missing columns
    existing_cols = [c['name'] for c in inspector.get_columns(table_name)]
    
    with engine.begin() as conn:
        for col in col_names:
            if col not in existing_cols:
                print(f"Adding column: {col}")
                conn.execute(text(f"ALTER TABLE `{table_name}` ADD COLUMN `{col}` TEXT"))

    # delete unused rows
    total_sheet_rows = len(all_values)
    
    with engine.begin() as conn:
        # Delete all rows where id > number of rows in sheet
        result = conn.execute(
            text(f"DELETE FROM `{table_name}` WHERE `id` > :max_id"),
            {"max_id": total_sheet_rows}
        )
        deleted_count = result.rowcount
        if deleted_count > 0:
            print(f"Deleted {deleted_count} unused rows from database")

    # upsert data - sync all columns for each row (including empty ones)
    with engine.begin() as conn:
        for idx, row in enumerate(all_values):
            row_id = idx + 1
            
            # Pad the row with empty strings if it's shorter than max columns
            padded_row = row + [''] * (len(col_names) - len(row))
            
            cols_to_use = ["id"] + col_names
            
            col_str = ", ".join([f"`{c}`" for c in cols_to_use])
            placeholders = ", ".join([f":{c}" for c in cols_to_use])
            
            # Update all columns except id on duplicate
            update_str = ", ".join([f"`{c}`=VALUES(`{c}`)" for c in cols_to_use if c != "id"])

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