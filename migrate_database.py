"""
Full Database Migration Script
Migrates EVERYTHING from source PostgreSQL database to target PostgreSQL database.
Includes: extensions, custom types (enums), tables, data, sequences, indexes, constraints.

Usage:
    python migrate_database.py

Configure source/target credentials via environment variables or edit directly below.
"""

import os
import sys
import subprocess
import shutil
import tempfile
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the backend directory
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)


# ─── SOURCE DATABASE (your current Render DB) ───────────────────────────────
SOURCE_DB = {
    "host": os.getenv("DB_HOST"),
    "port": os.getenv("DB_PORT", "5432"),
    "name": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USERNAME"),
    "password": os.getenv("DB_PASSWORD"),
    "sslmode": os.getenv("DB_SSLMODE", "require"),
}

# ─── TARGET DATABASE (where you want to migrate to) ─────────────────────────
# Set these env vars or edit the defaults directly
TARGET_DB = {
    "host": os.getenv("TARGET_DB_HOST", ""),
    "port": os.getenv("TARGET_DB_PORT", "5432"),
    "name": os.getenv("TARGET_DB_NAME", ""),
    "user": os.getenv("TARGET_DB_USERNAME", ""),
    "password": os.getenv("TARGET_DB_PASSWORD", ""),
    "sslmode": os.getenv("TARGET_DB_SSLMODE", "require"),
}


def build_connection_url(db: dict) -> str:
    return (
        f"postgresql://{db['user']}:{db['password']}"
        f"@{db['host']}:{db['port']}/{db['name']}"
        f"?sslmode={db['sslmode']}"
    )


def validate_config():
    """Ensure all required credentials are set."""
    missing_source = [k for k, v in SOURCE_DB.items() if not v]
    missing_target = [k for k, v in TARGET_DB.items() if not v and k != "sslmode"]

    if missing_source:
        print(f"[ERROR] Missing SOURCE database config: {missing_source}")
        print("Make sure your .env file has DB_HOST, DB_PORT, DB_NAME, DB_USERNAME, DB_PASSWORD")
        sys.exit(1)

    if missing_target:
        print(f"[ERROR] Missing TARGET database config: {missing_target}")
        print("Set these environment variables in .env or as shell env vars:")
        print("  TARGET_DB_HOST, TARGET_DB_PORT, TARGET_DB_NAME, TARGET_DB_USERNAME, TARGET_DB_PASSWORD")
        print("\nOr edit the TARGET_DB dict directly in this script.")
        sys.exit(1)


def find_pg_tool(tool_name: str) -> str | None:
    """Find pg_dump or psql in PATH or common install locations."""
    # Check PATH first
    found = shutil.which(tool_name)
    if found:
        return found

    # Common Windows PostgreSQL install paths
    common_paths = [
        rf"C:\Program Files\PostgreSQL\{v}\bin\{tool_name}.exe"
        for v in range(17, 11, -1)  # Check versions 17 down to 12
    ]
    # Also check Program Files (x86)
    common_paths += [
        rf"C:\Program Files (x86)\PostgreSQL\{v}\bin\{tool_name}.exe"
        for v in range(17, 11, -1)
    ]

    for path in common_paths:
        if os.path.exists(path):
            return path

    return None


def migrate_with_pg_dump():
    """
    Primary method: Use pg_dump + psql for a complete migration.
    This captures EVERYTHING: extensions, custom types, sequences, tables,
    data, indexes, constraints, triggers, functions.
    """
    pg_dump = find_pg_tool("pg_dump")
    psql = find_pg_tool("psql")

    if not pg_dump or not psql:
        return False

    print(f"[OK] Found pg_dump: {pg_dump}")
    print(f"[OK] Found psql:    {psql}")

    # Create a temporary file for the dump
    dump_file = tempfile.NamedTemporaryFile(
        suffix=".sql", delete=False, mode="w", encoding="utf-8"
    )
    dump_path = dump_file.name
    dump_file.close()

    try:
        # ── Step 1: Dump source database ─────────────────────────────────
        print("\n[1/3] Dumping source database (this may take a while)...")

        dump_env = os.environ.copy()
        dump_env["PGPASSWORD"] = SOURCE_DB["password"]

        dump_cmd = [
            pg_dump,
            "-h", SOURCE_DB["host"],
            "-p", SOURCE_DB["port"],
            "-U", SOURCE_DB["user"],
            "-d", SOURCE_DB["name"],
            "--no-owner",          # Don't set ownership (target may have different user)
            "--no-privileges",     # Don't dump GRANT/REVOKE
            "--clean",             # Drop objects before recreating
            "--if-exists",         # Use IF EXISTS with DROP
            "--create",            # Include CREATE DATABASE
            "-f", dump_path,
        ]

        result = subprocess.run(
            dump_cmd, env=dump_env, capture_output=True, text=True, timeout=600
        )

        if result.returncode != 0:
            print(f"[ERROR] pg_dump failed:\n{result.stderr}")
            return False

        dump_size = os.path.getsize(dump_path)
        print(f"[OK] Dump complete: {dump_size / 1024 / 1024:.1f} MB")

        # ── Step 2: Restore to target database ───────────────────────────
        print("\n[2/3] Restoring to target database...")

        restore_env = os.environ.copy()
        restore_env["PGPASSWORD"] = TARGET_DB["password"]

        restore_cmd = [
            psql,
            "-h", TARGET_DB["host"],
            "-p", TARGET_DB["port"],
            "-U", TARGET_DB["user"],
            "-d", TARGET_DB["name"],
            "-f", dump_path,
            "--set", "ON_ERROR_STOP=off",  # Continue on non-fatal errors
        ]

        result = subprocess.run(
            restore_cmd, env=restore_env, capture_output=True, text=True, timeout=600
        )

        # psql may report some non-fatal errors (e.g., "database already exists")
        if result.returncode != 0 and "fatal" in result.stderr.lower():
            print(f"[ERROR] Restore failed:\n{result.stderr}")
            return False

        if result.stderr:
            # Filter out noise
            errors = [
                line for line in result.stderr.splitlines()
                if "ERROR" in line and "already exists" not in line
            ]
            if errors:
                print(f"[WARN] Some non-fatal errors during restore:")
                for e in errors[:10]:
                    print(f"  {e}")

        # ── Step 3: Verify ───────────────────────────────────────────────
        print("\n[3/3] Verifying migration...")
        verify_migration()

        print("\n[SUCCESS] Database migration complete!")
        return True

    finally:
        # Clean up dump file
        try:
            os.unlink(dump_path)
        except OSError:
            pass


def migrate_with_psycopg2():
    """
    Fallback method: Use psycopg2 directly to copy everything.
    Handles: extensions, enums, tables, data, sequences, indexes, constraints.
    """
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError:
        print("[ERROR] psycopg2 is not installed. Install it with:")
        print("  pip install psycopg2-binary")
        sys.exit(1)

    source_url = build_connection_url(SOURCE_DB)
    target_url = build_connection_url(TARGET_DB)

    print("[INFO] Using psycopg2 fallback method...")

    source_conn = psycopg2.connect(source_url)
    target_conn = psycopg2.connect(target_url)
    source_conn.autocommit = False
    target_conn.autocommit = False

    source_cur = source_conn.cursor()
    target_cur = target_conn.cursor()

    try:
        # ── Step 1: Create extensions ────────────────────────────────────
        print("\n[1/7] Creating extensions...")
        source_cur.execute("""
            SELECT extname FROM pg_extension WHERE extname != 'plpgsql'
        """)
        for (ext,) in source_cur.fetchall():
            try:
                target_cur.execute(f'CREATE EXTENSION IF NOT EXISTS "{ext}"')
                print(f"  [OK] Extension: {ext}")
            except Exception as e:
                print(f"  [WARN] Extension {ext}: {e}")
                target_conn.rollback()
        target_conn.commit()

        # ── Step 2: Create custom enum types ─────────────────────────────
        print("\n[2/7] Creating custom enum types...")
        source_cur.execute("""
            SELECT t.typname, array_agg(e.enumlabel ORDER BY e.enumsortorder)
            FROM pg_type t
            JOIN pg_enum e ON t.oid = e.enumtypid
            JOIN pg_namespace n ON t.typnamespace = n.oid
            WHERE n.nspname = 'public'
            GROUP BY t.typname
        """)
        for type_name, labels in source_cur.fetchall():
            try:
                labels_sql = ", ".join(f"'{l}'" for l in labels)
                target_cur.execute(f"""
                    DO $$ BEGIN
                        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = '{type_name}') THEN
                            CREATE TYPE "{type_name}" AS ENUM ({labels_sql});
                        END IF;
                    END$$;
                """)
                print(f"  [OK] Enum: {type_name} ({len(labels)} values)")
            except Exception as e:
                print(f"  [WARN] Enum {type_name}: {e}")
                target_conn.rollback()
        target_conn.commit()

        # ── Step 3: Get table creation order (respecting foreign keys) ───
        print("\n[3/7] Analyzing table dependencies...")
        source_cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """)
        all_tables = [row[0] for row in source_cur.fetchall()]

        # Build dependency graph
        source_cur.execute("""
            SELECT DISTINCT
                tc.table_name,
                ccu.table_name AS referenced_table
            FROM information_schema.table_constraints tc
            JOIN information_schema.constraint_column_usage ccu
                ON tc.constraint_name = ccu.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY'
                AND tc.table_schema = 'public'
                AND tc.table_name != ccu.table_name
        """)
        deps = {}
        for table, ref in source_cur.fetchall():
            deps.setdefault(table, set()).add(ref)

        # Topological sort
        ordered_tables = topological_sort(all_tables, deps)
        print(f"  [OK] Found {len(ordered_tables)} tables")

        # ── Step 4: Drop existing tables in target (reverse order) ───────
        print("\n[4/7] Preparing target database (dropping existing tables)...")
        for table in reversed(ordered_tables):
            try:
                target_cur.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')
            except Exception as e:
                print(f"  [WARN] Drop {table}: {e}")
                target_conn.rollback()
        target_conn.commit()

        # ── Step 5: Recreate schema from source ─────────────────────────
        print("\n[5/7] Recreating schema...")
        for table in ordered_tables:
            try:
                # Get the full CREATE TABLE statement
                ddl = get_create_table_sql(source_cur, table)
                target_cur.execute(ddl)
                target_conn.commit()
                print(f"  [OK] Created: {table}")
            except Exception as e:
                print(f"  [ERROR] Table {table}: {e}")
                target_conn.rollback()

        # ── Step 6: Copy data using COPY (fastest method) ────────────────
        print("\n[6/7] Copying data...")
        total_rows = 0
        for table in ordered_tables:
            try:
                # Count rows in source
                source_cur.execute(f'SELECT COUNT(*) FROM "{table}"')
                count = source_cur.fetchone()[0]

                if count == 0:
                    print(f"  [--] {table}: 0 rows (empty)")
                    continue

                # Use COPY TO / COPY FROM via StringIO for speed
                import io
                buf = io.StringIO()

                # Disable triggers/constraints during load
                target_cur.execute(f'ALTER TABLE "{table}" DISABLE TRIGGER ALL')

                copy_sql_out = f'COPY "{table}" TO STDOUT WITH (FORMAT csv, HEADER, NULL \'\\N\')'
                source_cur.copy_expert(copy_sql_out, buf)

                buf.seek(0)

                copy_sql_in = f'COPY "{table}" FROM STDIN WITH (FORMAT csv, HEADER, NULL \'\\N\')'
                target_cur.copy_expert(copy_sql_in, buf)

                # Re-enable triggers
                target_cur.execute(f'ALTER TABLE "{table}" ENABLE TRIGGER ALL')

                target_conn.commit()
                total_rows += count
                print(f"  [OK] {table}: {count:,} rows")
            except Exception as e:
                print(f"  [ERROR] {table}: {e}")
                target_conn.rollback()
                # Re-enable triggers on failure
                try:
                    target_cur.execute(f'ALTER TABLE "{table}" ENABLE TRIGGER ALL')
                    target_conn.commit()
                except Exception:
                    target_conn.rollback()

        print(f"\n  Total rows copied: {total_rows:,}")

        # ── Step 7: Reset sequences, recreate indexes & constraints ──────
        print("\n[7/7] Resetting sequences and recreating indexes...")

        # Reset sequences to match current data
        source_cur.execute("""
            SELECT sequence_name FROM information_schema.sequences
            WHERE sequence_schema = 'public'
        """)
        for (seq_name,) in source_cur.fetchall():
            try:
                source_cur.execute(f"SELECT last_value, is_called FROM \"{seq_name}\"")
                last_val, is_called = source_cur.fetchone()
                if is_called:
                    target_cur.execute(f"SELECT setval('\"{seq_name}\"', {last_val}, true)")
                else:
                    target_cur.execute(f"SELECT setval('\"{seq_name}\"', {last_val}, false)")
                target_conn.commit()
            except Exception as e:
                print(f"  [WARN] Sequence {seq_name}: {e}")
                target_conn.rollback()

        # Recreate indexes
        source_cur.execute("""
            SELECT indexdef FROM pg_indexes
            WHERE schemaname = 'public'
            AND indexname NOT LIKE '%_pkey'
        """)
        for (indexdef,) in source_cur.fetchall():
            try:
                # Add IF NOT EXISTS isn't standard for CREATE INDEX, use exception handling
                target_cur.execute(indexdef)
                target_conn.commit()
            except Exception as e:
                if "already exists" not in str(e):
                    print(f"  [WARN] Index: {e}")
                target_conn.rollback()

        # Recreate foreign key constraints
        source_cur.execute("""
            SELECT
                tc.table_name,
                tc.constraint_name,
                kcu.column_name,
                ccu.table_name AS ref_table,
                ccu.column_name AS ref_column
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
            JOIN information_schema.constraint_column_usage ccu
                ON tc.constraint_name = ccu.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY'
                AND tc.table_schema = 'public'
        """)
        for table, constraint, col, ref_table, ref_col in source_cur.fetchall():
            try:
                target_cur.execute(f"""
                    DO $$ BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.table_constraints
                            WHERE constraint_name = '{constraint}'
                        ) THEN
                            ALTER TABLE "{table}"
                            ADD CONSTRAINT "{constraint}"
                            FOREIGN KEY ("{col}") REFERENCES "{ref_table}"("{ref_col}");
                        END IF;
                    END$$;
                """)
                target_conn.commit()
            except Exception as e:
                if "already exists" not in str(e):
                    print(f"  [WARN] FK {constraint}: {e}")
                target_conn.rollback()

        print("\n[SUCCESS] Database migration complete!")

        # Verify
        verify_migration_psycopg2(source_cur, target_cur)

    except Exception as e:
        print(f"\n[FATAL] Migration failed: {e}")
        target_conn.rollback()
        raise
    finally:
        source_cur.close()
        target_cur.close()
        source_conn.close()
        target_conn.close()


def get_create_table_sql(cursor, table_name: str) -> str:
    """Generate CREATE TABLE SQL from information_schema."""
    cursor.execute("""
        SELECT
            column_name,
            data_type,
            udt_name,
            character_maximum_length,
            column_default,
            is_nullable,
            numeric_precision,
            numeric_scale
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        ORDER BY ordinal_position
    """, (table_name,))

    columns = cursor.fetchall()
    col_defs = []

    for col_name, data_type, udt_name, max_len, default, nullable, num_prec, num_scale in columns:
        # Map data types
        if data_type == 'USER-DEFINED':
            col_type = f'"{udt_name}"'
        elif data_type == 'character varying':
            col_type = f"VARCHAR({max_len})" if max_len else "VARCHAR"
        elif data_type == 'character':
            col_type = f"CHAR({max_len})" if max_len else "CHAR"
        elif data_type == 'numeric':
            if num_prec and num_scale:
                col_type = f"NUMERIC({num_prec},{num_scale})"
            else:
                col_type = "NUMERIC"
        elif data_type == 'ARRAY':
            # Get the element type from udt_name (prefixed with _)
            element_type = udt_name.lstrip('_').upper()
            col_type = f"{element_type}[]"
        elif data_type == 'timestamp without time zone':
            col_type = 'TIMESTAMP'
        elif data_type == 'timestamp with time zone':
            col_type = 'TIMESTAMPTZ'
        elif data_type == 'double precision':
            col_type = 'DOUBLE PRECISION'
        elif data_type == 'boolean':
            col_type = 'BOOLEAN'
        elif data_type == 'integer':
            col_type = 'INTEGER'
        elif data_type == 'bigint':
            col_type = 'BIGINT'
        elif data_type == 'smallint':
            col_type = 'SMALLINT'
        elif data_type == 'text':
            col_type = 'TEXT'
        elif data_type == 'uuid':
            col_type = 'UUID'
        elif data_type == 'jsonb':
            col_type = 'JSONB'
        elif data_type == 'json':
            col_type = 'JSON'
        elif data_type == 'bytea':
            col_type = 'BYTEA'
        elif data_type == 'date':
            col_type = 'DATE'
        elif data_type == 'time without time zone':
            col_type = 'TIME'
        elif data_type == 'real':
            col_type = 'REAL'
        else:
            col_type = data_type.upper()

        parts = [f'"{col_name}"', col_type]

        if nullable == 'NO':
            parts.append("NOT NULL")

        if default is not None:
            parts.append(f"DEFAULT {default}")

        col_defs.append(" ".join(parts))

    # Get primary key
    cursor.execute("""
        SELECT kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
            ON tc.constraint_name = kcu.constraint_name
        WHERE tc.constraint_type = 'PRIMARY KEY'
            AND tc.table_schema = 'public'
            AND tc.table_name = %s
        ORDER BY kcu.ordinal_position
    """, (table_name,))
    pk_cols = [row[0] for row in cursor.fetchall()]

    if pk_cols:
        pk_str = ", ".join(f'"{c}"' for c in pk_cols)
        col_defs.append(f"PRIMARY KEY ({pk_str})")

    # Get unique constraints
    cursor.execute("""
        SELECT tc.constraint_name, array_agg(kcu.column_name ORDER BY kcu.ordinal_position)
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
            ON tc.constraint_name = kcu.constraint_name
        WHERE tc.constraint_type = 'UNIQUE'
            AND tc.table_schema = 'public'
            AND tc.table_name = %s
        GROUP BY tc.constraint_name
    """, (table_name,))
    for constraint_name, unique_cols in cursor.fetchall():
        cols_str = ", ".join(f'"{c}"' for c in unique_cols)
        col_defs.append(f'CONSTRAINT "{constraint_name}" UNIQUE ({cols_str})')

    columns_sql = ",\n    ".join(col_defs)
    return f'CREATE TABLE "{table_name}" (\n    {columns_sql}\n)'


def topological_sort(tables: list, deps: dict) -> list:
    """Sort tables respecting foreign key dependencies."""
    result = []
    visited = set()
    visiting = set()

    def visit(table):
        if table in visited:
            return
        if table in visiting:
            # Circular dependency - just add it
            return
        visiting.add(table)
        for dep in deps.get(table, []):
            if dep in tables:
                visit(dep)
        visiting.discard(table)
        visited.add(table)
        result.append(table)

    for table in tables:
        visit(table)

    return result


def verify_migration():
    """Verify migration using psql."""
    psql = find_pg_tool("psql")
    if not psql:
        return

    env = os.environ.copy()
    env["PGPASSWORD"] = TARGET_DB["password"]

    result = subprocess.run(
        [
            psql,
            "-h", TARGET_DB["host"],
            "-p", TARGET_DB["port"],
            "-U", TARGET_DB["user"],
            "-d", TARGET_DB["name"],
            "-t", "-A",
            "-c", """
                SELECT table_name, (
                    SELECT COUNT(*) FROM information_schema.columns c
                    WHERE c.table_name = t.table_name AND c.table_schema = 'public'
                ) as col_count
                FROM information_schema.tables t
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                ORDER BY table_name
            """,
        ],
        env=env, capture_output=True, text=True, timeout=30,
    )

    if result.returncode == 0 and result.stdout.strip():
        lines = [l for l in result.stdout.strip().splitlines() if l.strip()]
        print(f"\n  Target database has {len(lines)} tables:")
        for line in lines[:10]:
            parts = line.split("|")
            if len(parts) >= 2:
                print(f"    {parts[0]}: {parts[1]} columns")
        if len(lines) > 10:
            print(f"    ... and {len(lines) - 10} more")


def verify_migration_psycopg2(source_cur, target_cur):
    """Compare table row counts between source and target."""
    print("\n  Verification - Row count comparison:")

    source_cur.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        ORDER BY table_name
    """)
    tables = [row[0] for row in source_cur.fetchall()]

    mismatches = 0
    for table in tables:
        try:
            source_cur.execute(f'SELECT COUNT(*) FROM "{table}"')
            src_count = source_cur.fetchone()[0]

            target_cur.execute(f'SELECT COUNT(*) FROM "{table}"')
            tgt_count = target_cur.fetchone()[0]

            status = "OK" if src_count == tgt_count else "MISMATCH"
            if status == "MISMATCH":
                mismatches += 1
                print(f"    [MISMATCH] {table}: source={src_count:,} target={tgt_count:,}")
            elif src_count > 0:
                print(f"    [OK] {table}: {src_count:,} rows")
        except Exception as e:
            print(f"    [ERROR] {table}: {e}")
            mismatches += 1

    if mismatches == 0:
        print(f"\n  All {len(tables)} tables verified successfully!")
    else:
        print(f"\n  {mismatches} table(s) had mismatches - review above.")


def main():
    print("=" * 60)
    print("  Shopivell Full Database Migration")
    print("=" * 60)

    validate_config()

    print(f"\n  Source: {SOURCE_DB['host']}/{SOURCE_DB['name']}")
    print(f"  Target: {TARGET_DB['host']}/{TARGET_DB['name']}")

    # Safety confirmation
    confirm = input("\n  This will OVERWRITE the target database. Continue? [y/N]: ")
    if confirm.lower() != "y":
        print("  Aborted.")
        sys.exit(0)

    # Try pg_dump first (most complete), fall back to psycopg2
    pg_dump = find_pg_tool("pg_dump")
    psql = find_pg_tool("psql")

    if pg_dump and psql:
        print("\n[INFO] Using pg_dump/psql method (recommended, most complete)")
        success = migrate_with_pg_dump()
        if not success:
            print("\n[INFO] pg_dump failed, falling back to psycopg2 method...")
            migrate_with_psycopg2()
    else:
        if not pg_dump:
            print("\n[INFO] pg_dump not found in PATH")
        if not psql:
            print("\n[INFO] psql not found in PATH")
        print("[INFO] Using psycopg2 direct method")
        migrate_with_psycopg2()


if __name__ == "__main__":
    main()
