import os
import sys

import oracledb


SAFE = "<SAFE_010>"
INSTANT_CLIENT = r"C:\Users\<USERNAME>\Documents\Codex\oracle-instant-client\instantclient_23_0"
FILING_NUMBERS = [
    "X2588040",
    "X2568708",
    "X2542193",
    "X255755",
    "X2455925",
    "X2441849",
    "T0072504",
    "32014669596",
    "BK6074PG818",
    "32014653252",
    "2421020006",
    "BK6115PG495",
    "BK6090PG136",
]


def rows_to_dicts(cursor, rows):
    columns = [column[0].lower() for column in cursor.description]
    return [dict(zip(columns, row)) for row in rows]


def print_rows(title, cursor, rows, limit=25):
    print(f"\n## {title}: {len(rows)} row(s)")
    for row in rows[:limit]:
        print(row)


def main():
    user = os.environ.get("ORACLE_USER")
    password = os.environ.get("ORACLE_PASSWORD")
    dsn = os.environ.get("ORACLE_DSN")
    if not user or not password or not dsn:
        raise SystemExit("Missing ORACLE_USER, ORACLE_PASSWORD, or ORACLE_DSN")

    if os.path.isdir(INSTANT_CLIENT):
        oracledb.init_oracle_client(lib_dir=INSTANT_CLIENT)

    conn = oracledb.connect(user=user, password=password, dsn=dsn)
    cur = conn.cursor()

    cur.execute("select sys_context('USERENV','CURRENT_SCHEMA') from dual")
    print("ORACLE_OK", cur.fetchone()[0])

    table_patterns = ["%LIEN%", "%SLJ%", "%LEGAL%", "%FILING%", "%UCC%"]
    cur.execute(
        """
        select owner, table_name
        from all_tables
        where owner in ('LOAD_SOURCE_VENDOR_NEG','CORE_DATA','LOAD_CORE','EDITING_API')
          and (
            upper(table_name) like :p1 or upper(table_name) like :p2
            or upper(table_name) like :p3 or upper(table_name) like :p4
            or upper(table_name) like :p5
          )
          and rownum <= 80
        order by owner, table_name
        """,
        table_patterns,
    )
    print_rows("candidate_tables", cur, rows_to_dicts(cur, cur.fetchall()), limit=80)

    cur.execute(
        """
        select column_name, data_type
        from all_tab_columns
        where owner = 'LOAD_SOURCE_VENDOR_NEG'
          and table_name = 'SOURCE_VENDOR_SLJ'
        order by column_id
        """,
    )
    print_rows("source_legal_data.source_lien_judgment_columns", cur, rows_to_dicts(cur, cur.fetchall()), limit=120)

    for owner, table in [
        ("CORE_DATA", "LIEN"),
        ("CORE_DATA", "LIEN_DATAVAULT"),
        ("LOAD_SOURCE_VENDOR_NEG", "LIEN"),
        ("LOAD_SOURCE_VENDOR_NEG", "BACKFEED_LIEN"),
    ]:
        cur.execute(
            """
            select column_name, data_type
            from all_tab_columns
            where owner = :owner
              and table_name = :table_name
            order by column_id
            """,
            {"owner": owner, "table_name": table},
        )
        print_rows(f"{owner}.{table}_columns", cur, rows_to_dicts(cur, cur.fetchall()), limit=80)

    bind_names = ",".join(f":n{i}" for i in range(len(FILING_NUMBERS)))
    params = {f"n{i}": value for i, value in enumerate(FILING_NUMBERS)}
    params["name"] = "%DEEL US LLC%"

    query = f"""
        select *
        from source_legal_data.source_lien_judgment
        where (
              upper(defendant_name) like :name
           or case_number in ({bind_names})
           or alternate_case in ({bind_names})
        )
          and rownum <= 100
    """
    cur.execute(query, params)
    print_rows("source_vendor_slj_deel_or_known_filings", cur, rows_to_dicts(cur, cur.fetchall()), limit=100)

    for owner, table in [
        ("CORE_DATA", "LIEN"),
        ("CORE_DATA", "LIEN_DATAVAULT"),
        ("LOAD_SOURCE_VENDOR_NEG", "LIEN"),
        ("LOAD_SOURCE_VENDOR_NEG", "BACKFEED_LIEN"),
    ]:
        cur.execute(
            """
            select column_name
            from all_tab_columns
            where owner = :owner
              and table_name = :table_name
            """,
            {"owner": owner, "table_name": table},
        )
        columns = {row[0] for row in cur.fetchall()}
        predicates = []
        params2 = {"safe": SAFE, "name": "%DEEL US LLC%"}
        if "SAFE_NUMBER" in columns:
            predicates.append("safe_number = :safe")
        if "DEFENDANT_NAME" in columns:
            predicates.append("upper(defendant_name) like :name")
        if "COMPANY_NAME" in columns:
            predicates.append("upper(company_name) like :name")
        for candidate_column in ["CASE_NUMBER", "FILING_NUMBER", "DOC_NUMBER", "REFERENCE_NUMBER", "ORIGINAL_CASE"]:
            if candidate_column in columns:
                predicates.append(f"{candidate_column.lower()} in ({bind_names})")

        if not predicates:
            continue

        query2 = f"""
            select *
            from {owner}.{table}
            where ({' or '.join(predicates)})
              and rownum <= 50
        """
        cur.execute(query2, params | params2)
        print_rows(f"{owner}.{table}_target_rows", cur, rows_to_dicts(cur, cur.fetchall()), limit=50)

    cur.close()
    conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("ORACLE_ERROR", type(error).__name__, str(error)[:1000])
        sys.exit(1)
