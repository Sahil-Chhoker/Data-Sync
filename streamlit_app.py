import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, inspect, text
from config import settings
import time


st.set_page_config(
    page_title="MySQL Data Manager",
    layout="wide"
)

@st.cache_resource
def get_engine():
    return create_engine(settings.DATABASE_URL)

engine = get_engine()


st.title("MySQL Data Manager")


@st.cache_data(ttl=5)
def get_tables():
    inspector = inspect(engine)
    return inspector.get_table_names()

@st.cache_data(ttl=30)
def get_table_columns(table_name):
    inspector = inspect(engine)
    return inspector.get_columns(table_name)

@st.cache_data(ttl=5)
def get_table_data(table_name):
    with engine.begin() as conn:
        result = conn.execute(text(f"SELECT * FROM `{table_name}` ORDER BY id ASC"))
        rows = result.fetchall()
        if not rows:
            return None
        return pd.DataFrame(rows, columns=result.keys())


tables = get_tables()

if not tables:
    st.warning("No tables found")
    st.stop()

sync_tables = [t for t in tables if t.startswith("Sync7")]
selected_table = sync_tables[0]

auto_refresh = st.sidebar.checkbox("Auto-refresh (10s)", value=True)

if st.sidebar.button("🔄 Refresh Now"):
    st.cache_data.clear()
    st.rerun()


st.sidebar.divider()
st.sidebar.subheader("Add New Column")

with st.sidebar.form("add_column_form"):
    new_col_name = st.text_input("Column Name")
    new_col_type = st.selectbox(
        "Column Type",
        ["VARCHAR(255)", "INT", "FLOAT", "BOOLEAN", "TEXT", "DATETIME"]
    )
    add_col = st.form_submit_button("Add Column")

    if add_col:
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        f"ALTER TABLE `{selected_table}` "
                        f"ADD COLUMN `{new_col_name}` {new_col_type}"
                    )
                )
            st.success("Column added")
            st.cache_data.clear()
            st.rerun()
        except Exception as e:
            st.error(e)


st.sidebar.divider()
st.sidebar.subheader("Insert Row")

columns_info = get_table_columns(selected_table)

with st.sidebar.form("insert_form"):
    insert_values = {}

    for col in columns_info:
        col_name = col["name"]
        insert_values[col_name] = st.text_input(col_name)

    insert = st.form_submit_button("Insert")

    if insert:
        try:
            cols = ", ".join(f"`{c}`" for c in insert_values.keys())
            placeholders = ", ".join(f":{c}" for c in insert_values.keys())

            with engine.begin() as conn:
                conn.execute(
                    text(
                        f"INSERT INTO `{selected_table}` ({cols}) "
                        f"VALUES ({placeholders})"
                    ),
                    insert_values
                )

            st.success("Row inserted")
            st.cache_data.clear()
            st.rerun()

        except Exception as e:
            st.error(e)


st.sidebar.divider()
st.sidebar.subheader("🗑 Delete Row")

delete_id = st.sidebar.text_input("ID to delete")

if st.sidebar.button("Delete", key="delete_row"):
    try:
        with engine.begin() as conn:
            conn.execute(
                text(f"DELETE FROM `{selected_table}` WHERE id = :id"),
                {"id": delete_id}
            )
        st.success("Row deleted")
        st.cache_data.clear()
        st.rerun()
    except Exception as e:
        st.error(e)

st.sidebar.divider()

st.sidebar.subheader("🗑 Delete Column")
delete_column = st.sidebar.text_input("Column Name to delete")
if st.sidebar.button("Delete", key="delete_column"):
    try:
        with engine.begin() as conn:
            conn.execute(
                text(f"ALTER TABLE `{selected_table}` DROP COLUMN `{delete_column}`")
            )
        st.success("Column deleted")
        st.cache_data.clear()
        st.rerun()
    except Exception as e:
        st.error(e)


st.subheader(f"Table: `{selected_table}`")

df = get_table_data(selected_table)

if df is not None:
    col1, col2, col3 = st.columns(3)
    col1.metric("Rows", len(df))
    col2.metric("Columns", len(df.columns))
    col3.metric("Last Updated", time.strftime("%H:%M:%S"))

    st.divider()

    st.dataframe(df, height=600)

    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "📥 Download CSV",
        csv,
        file_name=f"{selected_table}.csv",
        mime="text/csv"
    )
else:
    st.info("Table is empty")


if auto_refresh:
    time.sleep(10)
    st.rerun()

st.divider()
st.caption("Live MySQL manager with schema control")
