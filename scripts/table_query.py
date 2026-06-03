#!/usr/bin/env python3
"""table_query.py — Natural language → SQL generation + pagination + data extraction.

Pipeline:
  1. User asks natural language question about a table
  2. Load table schema + match relevant SQL function categories
  3. Build prompt → LLM generates SQL → execute → return results

Usage (via wiki.py):
    wiki ledger ask <table> "<question>" [--page N] [--page-size N]
    wiki ledger schema <table>
    wiki ledger sql "<sql>"
    wiki ledger query <table> --sql "<sql>" [--page N] [--page-size N]
    wiki ledger traverse <table> [--batch-size N] [--offset N]

Safety: Only SELECT statements are permitted. DML/DDL is rejected.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import get_wiki_dir  # noqa: E402

WIKI_DIR = get_wiki_dir()
LEDGER_DB = WIKI_DIR / "ledger" / "ledger.duckdb"


def _get_conn() -> duckdb.DuckDBPyConnection:
    """Connect to ledger DuckDB (read-only for safety)."""
    if not LEDGER_DB.exists():
        raise FileNotFoundError("No ledger database found. Create a table first.")
    return duckdb.connect(str(LEDGER_DB), read_only=True)


def _sanitize_error(e: Exception) -> str:
    """Return a user-safe error message without internal SQL details."""
    msg = str(e)
    if len(msg) > 200:
        msg = msg[:200] + "..."
    return msg


def _q(name: str) -> str:
    """Safely quote a SQL identifier by escaping embedded double-quotes."""
    return '"' + name.replace('"', '""') + '"'


def _resolve_table(user_input: str, conn: duckdb.DuckDBPyConnection) -> str | None:
    """Look up actual_name from display_name or actual_name."""
    row = conn.execute("SELECT actual_name FROM _registry WHERE actual_name = ?", [user_input]).fetchone()
    if row:
        return row[0]
    row = conn.execute("SELECT actual_name FROM _registry WHERE display_name = ?", [user_input]).fetchone()
    if row:
        return row[0]
    row = conn.execute(
        "SELECT actual_name FROM _registry WHERE LOWER(display_name) = LOWER(?)", [user_input]
    ).fetchone()
    return row[0] if row else None


def _is_readonly(sql: str) -> bool:
    """Check SQL is read-only. Defense-in-depth — real safety comes from read_only=True."""
    stripped = sql.strip().upper()
    # Reject multi-statement SQL
    if ";" in stripped.rstrip(";"):
        return False
    # Reject DML/DDL keywords anywhere in the statement
    forbidden = ("INSERT ", "UPDATE ", "DELETE ", "DROP ", "CREATE ", "ALTER ",
                 "TRUNCATE ", "GRANT ", "REVOKE ", "PRAGMA ")
    for kw in forbidden:
        if kw in stripped:
            return False
    # Handle CTEs and subqueries
    while stripped.startswith(("(", "WITH")):
        idx = stripped.find("SELECT")
        if idx >= 0:
            stripped = stripped[idx:]
        else:
            break
    return stripped.startswith(("SELECT", "DESCRIBE", "SHOW", "EXPLAIN"))


def get_table_schema(table_name: str) -> dict:
    """Return table schema: columns, types, row count, sample rows."""
    conn = None
    try:
        conn = _get_conn()
        actual = _resolve_table(table_name, conn)
        if actual is None:
            return {"success": False, "error": f"Table '{table_name}' not found."}

        # Registry info
        reg = conn.execute(
            "SELECT display_name, description, fields_json, unique_key, auto_increment, "
            "record_count, created_at, updated_at FROM _registry WHERE actual_name = ?",
            [actual],
        ).fetchone()
        if reg is None:
            return {"success": False, "error": f"Registry entry missing for '{actual}'."}

        # Column info from information_schema
        cols = conn.execute(
            "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
            "WHERE table_name = ? ORDER BY ordinal_position",
            [actual],
        ).fetchall()

        columns = [{"name": c[0], "type": c[1], "nullable": c[2] == "YES"} for c in cols]
        fields = json.loads(reg[2])
        unique_key = json.loads(reg[3])

        # Sample rows
        sample_rows = conn.execute(f'SELECT * FROM {_q(actual)} LIMIT 3').fetchall()
        sample_cols = [c[0] for c in cols]
        sample = [dict(zip(sample_cols, r)) for r in sample_rows]
    except Exception as e:
        return {"success": False, "error": f"Schema query failed: {_sanitize_error(e)}"}
    finally:
        if conn:
            conn.close()

    return {
        "success": True,
        "table": {
            "display_name": reg[0],
            "actual_name": actual,
            "description": reg[1] or "",
            "fields": fields,
            "unique_key": unique_key,
            "auto_increment": reg[4],
            "record_count": reg[5],
            "created_at": reg[6].isoformat() if reg[6] else "",
            "updated_at": reg[7].isoformat() if reg[7] else "",
        },
        "columns": columns,
        "row_count": reg[5],
        "sample": sample,
    }


def execute_sql(sql: str) -> dict:
    """Execute a SELECT SQL statement against the ledger DuckDB."""
    if not _is_readonly(sql):
        return {"success": False, "error": "Only SELECT statements are permitted."}

    conn = _get_conn()
    try:
        result = conn.execute(sql)
        col_names = [desc[0] for desc in result.description]
        rows = result.fetchall()
        conn.close()
        return {
            "success": True,
            "columns": col_names,
            "row_count": len(rows),
            "rows": [dict(zip(col_names, r)) for r in rows],
        }
    except duckdb.Error as e:
        conn.close()
        return {"success": False, "error": _sanitize_error(e)}


def query_table(table_name: str, sql: str, page: int = 1, page_size: int = 20) -> dict:
    """Execute a paginated SQL query against a table.

    Automatically wraps the SQL with COUNT(*) for total count and
    applies LIMIT/OFFSET for pagination.
    """
    conn = _get_conn()
    actual = _resolve_table(table_name, conn)
    if actual is None:
        conn.close()
        return {"success": False, "error": f"Table '{table_name}' not found."}

    # Safety check
    clean_sql = sql.strip()
    if not _is_readonly(clean_sql):
        conn.close()
        return {"success": False, "error": "Only SELECT statements are permitted."}

    # Inject table name if SQL uses FROM without explicit table
    # Support both: "SELECT *" and "SELECT * FROM table"
    clean_upper = clean_sql.upper()
    if "FROM" not in clean_upper:
        clean_sql = clean_sql.rstrip(";") + f' FROM "{actual}"'

    # Get total count (wrap query in COUNT)
    count_sql = f"SELECT COUNT(*) AS total FROM ({clean_sql}) AS _sub"
    try:
        total = conn.execute(count_sql).fetchone()[0]
    except duckdb.Error as e:
        conn.close()
        return {"success": False, "error": f"Count query failed: {e}"}

    # Apply pagination
    offset = (page - 1) * page_size
    paginated_sql = clean_sql.rstrip(";") + f" LIMIT {page_size} OFFSET {offset}"

    try:
        result = conn.execute(paginated_sql)
        col_names = [desc[0] for desc in result.description]
        rows = result.fetchall()
    except duckdb.Error as e:
        conn.close()
        return {"success": False, "error": f"Query failed: {e}"}

    conn.close()

    has_more = offset + len(rows) < total
    total_pages = (total + page_size - 1) // page_size if total > 0 else 1

    return {
        "success": True,
        "table": actual,
        "sql": paginated_sql,
        "columns": col_names,
        "rows": [dict(zip(col_names, r)) for r in rows],
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_rows": total,
            "total_pages": total_pages,
            "returned_rows": len(rows),
            "has_more": has_more,
        },
    }


def traverse_table(table_name: str, batch_size: int = 100, offset: int = 0) -> dict:
    """Traverse through all rows of a table in batches.

    Returns the next batch of rows and the offset for the next batch.
    """
    conn = _get_conn()
    actual = _resolve_table(table_name, conn)
    if actual is None:
        conn.close()
        return {"success": False, "error": f"Table '{table_name}' not found."}

    # Get total count and row count
    try:
        total = conn.execute(f'SELECT COUNT(*) FROM "{actual}"').fetchone()[0]
        rows = conn.execute(
            f'SELECT * FROM "{actual}" LIMIT {batch_size} OFFSET {offset}'
        ).fetchall()
        col_names = [desc[0] for desc in conn.description]
    except duckdb.Error as e:
        conn.close()
        return {"success": False, "error": _sanitize_error(e)}

    conn.close()

    next_offset = offset + len(rows)
    has_more = next_offset < total

    return {
        "success": True,
        "table": actual,
        "columns": col_names,
        "rows": [dict(zip(col_names, r)) for r in rows],
        "traversal": {
            "offset": offset,
            "batch_size": batch_size,
            "total_rows": total,
            "returned_rows": len(rows),
            "next_offset": next_offset if has_more else None,
            "has_more": has_more,
            "progress_pct": round(next_offset / total * 100, 1) if total > 0 else 100.0,
        },
    }


# ═══════════════════════════════════════════════════════════════════════
# Function category matching + SQL generation
# ═══════════════════════════════════════════════════════════════════════

# Paths
REF_DIR = Path(__file__).resolve().parent.parent / "references"
SQL_FUNCTIONS_FILE = REF_DIR / "sql-functions.md"

# Keyword → function category mapping
FUNCTION_CATEGORIES: dict[str, list[str]] = {
    "聚合函数": ["统计", "汇总", "总共", "平均", "求和", "计数", "最大", "最小", "总和", "合计",
                 "avg", "sum", "count", "max", "min", "total", "group by"],
    "统计聚合函数": ["相关", "协方差", "熵", "标准差", "方差", "corr", "stddev", "variance"],
    "窗口函数": ["排名", "前N", "后N", "第几", "排序", "排行", "rank", "row_number", "dense_rank",
                 "over", "partition", "lag", "lead", "顺序", "名次"],
    "数值函数": ["比例", "占比", "百分比", "四舍五入", "绝对值", "取整", "平方根", "ceil", "floor",
                 "round", "abs", "sqrt", "mod", "取余", "取模"],
    "文本/字符串函数": ["包含", "开头", "拼接", "截取", "替换", "长度", "大小写", "like", "substring",
                       "replace", "concat", "trim", "upper", "lower", "包含文字", "模糊"],
    "日期函数": ["今年", "本月", "上周", "去年", "明年", "季度", "星期", "year", "month", "day",
                 "date", "日期", "时间范围", "年月日"],
    "时间函数": ["时间", "时分秒", "几点", "hour", "minute", "second", "time"],
    "时间戳函数": ["时间戳", "timestamp", "now", "current_date", "current_time"],
    "列表函数": ["列表", "数组", "展开", "list", "array", "unnest", "flatten"],
    "日期格式函数": ["格式化", "strftime", "strptime", "日期格式", "format"],
}


def _match_functions(question: str) -> dict[str, str]:
    """Analyze question and return matching function categories with their content.

    Returns dict of {category_name: content_section}.
    Always includes '聚合函数' as default.
    """
    matched: set[str] = {"聚合函数"}  # Always include aggregation basics

    q = question.lower()
    for category, keywords in FUNCTION_CATEGORIES.items():
        for kw in keywords:
            if kw.lower() in q:
                matched.add(category)
                break

    # Load matched sections from reference file
    if not SQL_FUNCTIONS_FILE.exists():
        return {}

    content = SQL_FUNCTIONS_FILE.read_text(encoding="utf-8")
    sections: dict[str, str] = {}

    for cat in matched:
        # Find section by ## heading
        escaped = re.escape(cat)
        pattern = rf"## {escaped}\n(.*?)(?=\n## |\Z)"
        m = re.search(pattern, content, re.DOTALL)
        if m:
            sections[cat] = m.group(1).strip()

    return sections


def _build_sql_prompt(
    question: str, schema: dict, function_sections: dict[str, str]
) -> tuple[str, str]:
    """Build system + user prompts for SQL generation."""
    # Build schema summary
    cols = schema.get("columns", [])
    col_desc = "\n".join(
        f"  - \"{c['name']}\" ({c['type']})" for c in cols
    )
    actual_name = schema.get("table", {}).get("actual_name", "")
    display_name = schema.get("table", {}).get("display_name", "")

    schema_block = f"""Table: {display_name} (actual: \"{actual_name}\")
Columns ({len(cols)}):
{col_desc}

Row count: {schema.get('row_count', 0)}
Sample rows:
{json.dumps(schema.get('sample', []), ensure_ascii=False, indent=2)}
"""

    funcs_block = ""
    for cat_name, cat_content in function_sections.items():
        # Extract only the function table rows (skip descriptions)
        funcs_block += f"\n### {cat_name}\n{cat_content[:3000]}\n"

    system_prompt = f"""You are a DuckDB SQL expert. Generate ONLY a valid SQL SELECT statement.

Rules:
1. Output ONLY the SQL, no explanation, no markdown code fences.
2. Table name MUST be double-quoted: "{actual_name}"
3. Column names with non-ASCII chars MUST be double-quoted.
4. Use DuckDB-specific functions when appropriate.
5. For Chinese text matching, use LIKE or = with exact strings.
6. Always end with a semicolon.
7. For ranking, use RANK() or ROW_NUMBER() OVER (ORDER BY ...).
8. For pagination hints, the caller will add LIMIT/OFFSET — do NOT add them.

{schema_block}

Relevant DuckDB SQL functions:
{funcs_block}
"""

    user_prompt = f"Question: {question}\n\nGenerate the SQL:"

    return system_prompt, user_prompt


def _call_llm(system_prompt: str, user_prompt: str) -> str:
    """Call LLM using project config. Returns raw response text."""
    import requests

    try:
        from config import get_llm_config, get_api_url
    except ImportError:
        raise RuntimeError("Config module not available.")

    llm_config = get_llm_config()
    provider = llm_config.get("provider", "deepseek")

    if provider == "ollama":
        api_url = f"{llm_config['base_url'].rstrip('/')}/api/chat"
        payload = {
            "model": llm_config.get("model", "llama3.2"),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "options": {"temperature": 0.1, "num_ctx": 32768},
        }
        headers = {"Content-Type": "application/json"}
    elif provider == "custom":
        api_url = get_api_url()
        payload = {
            "model": llm_config.get("model", ""),
            "temperature": 0.1,
            "max_tokens": 2000,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {llm_config.get('api_key', '')}",
        }
    else:
        api_url = get_api_url()
        api_key = llm_config.get("api_key", "")
        if not api_key:
            raise RuntimeError("LLM API key not configured.")
        payload = {
            "model": llm_config.get("model", "deepseek-v4-flash"),
            "temperature": 0.1,
            "max_tokens": 2000,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if provider == "deepseek":
            payload["thinking"] = {"type": "disabled"}
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

    resp = requests.post(api_url, json=payload, headers=headers, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    if provider == "ollama":
        return (data.get("message", {}).get("content", "") or "").strip()
    else:
        return (data["choices"][0]["message"].get("content") or "").strip()


def _clean_sql(raw: str) -> str:
    """Extract SQL from LLM response. Strips markdown fences and explanations."""
    text = raw.strip()
    # Remove markdown code fences
    for fence in ("```sql", "```"):
        if text.startswith(fence):
            text = text[len(fence):].strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    # Remove leading non-SQL text (find SELECT)
    upper = text.upper()
    for keyword in ("SELECT", "WITH", "DESCRIBE", "EXPLAIN"):
        idx = upper.find(keyword)
        if idx >= 0:
            text = text[idx:]
            break
    return text.strip()


def ask_table(table_name: str, question: str, page: int = 1, page_size: int = 20) -> dict:
    """Natural language → SQL generation → execution pipeline.

    1. Load table schema
    2. Match relevant SQL functions
    3. Build prompt → LLM generates SQL
    4. Execute SQL with pagination
    5. Return formatted results
    """
    # 1. Load schema
    schema = get_table_schema(table_name)
    if not schema.get("success"):
        return schema

    # 2. Match functions
    func_sections = _match_functions(question)

    # 3. Build prompt and generate SQL
    system_prompt, user_prompt = _build_sql_prompt(question, schema, func_sections)
    try:
        raw_sql = _call_llm(system_prompt, user_prompt)
    except Exception as e:
        return {
            "success": False,
            "error": f"LLM call failed: {e}",
            "schema": schema,
            "matched_functions": list(func_sections.keys()),
        }

    sql = _clean_sql(raw_sql)

    # 4. Execute with pagination
    result = query_table(table_name, sql, page=page, page_size=page_size)

    # 5. Include metadata
    result["generated_sql"] = sql
    result["raw_llm_response"] = raw_sql
    result["matched_functions"] = list(func_sections.keys())
    result["schema_summary"] = {
        "display_name": schema["table"]["display_name"],
        "actual_name": schema["table"]["actual_name"],
        "columns": [(c["name"], c["type"]) for c in schema["columns"]],
    }

    return result


def prepare_context(table_name: str, question: str) -> dict:
    """Prepare context for Claude-mediated SQL generation.

    Returns schema + matched function sections without calling LLM.
    Used when Claude wants to generate SQL itself with full context.
    """
    schema = get_table_schema(table_name)
    if not schema.get("success"):
        return schema

    func_sections = _match_functions(question)
    system_prompt, user_prompt = _build_sql_prompt(question, schema, func_sections)

    return {
        "success": True,
        "table_name": table_name,
        "schema": schema,
        "matched_functions": list(func_sections.keys()),
        "function_reference": func_sections,
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
    }


# ═══════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Table query and traversal for ledger tables")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # ask — natural language → SQL → results
    ask_parser = subparsers.add_parser("ask", help="Natural language question → SQL → results")
    ask_parser.add_argument("table", help="Table name")
    ask_parser.add_argument("question", help="Natural language question")
    ask_parser.add_argument("--page", type=int, default=1, help="Page number (1-based)")
    ask_parser.add_argument("--page-size", type=int, default=20, help="Rows per page")

    # context — prepare schema + functions for Claude-mediated SQL generation
    ctx_parser = subparsers.add_parser("context", help="Prepare context for SQL generation")
    ctx_parser.add_argument("table", help="Table name")
    ctx_parser.add_argument("question", help="Natural language question")

    # schema
    schema_parser = subparsers.add_parser("schema", help="Show table schema for SQL generation")
    schema_parser.add_argument("table", help="Table name")

    # sql
    sql_parser = subparsers.add_parser("sql", help="Execute raw SQL (SELECT only)")
    sql_parser.add_argument("sql", help="SQL SELECT statement")

    # query (paginated)
    query_parser = subparsers.add_parser("query", help="Paginated SQL query")
    query_parser.add_argument("table", help="Table name")
    query_parser.add_argument("--sql", required=True, help="SQL SELECT statement")
    query_parser.add_argument("--page", type=int, default=1, help="Page number (1-based)")
    query_parser.add_argument("--page-size", type=int, default=20, help="Rows per page")

    # traverse
    traverse_parser = subparsers.add_parser("traverse", help="Batch traversal through all rows")
    traverse_parser.add_argument("table", help="Table name")
    traverse_parser.add_argument("--batch-size", type=int, default=100, help="Rows per batch")
    traverse_parser.add_argument("--offset", type=int, default=0, help="Starting offset")

    args = parser.parse_args()

    if args.command == "ask":
        result = ask_table(args.table, args.question, page=args.page, page_size=args.page_size)
    elif args.command == "context":
        result = prepare_context(args.table, args.question)
    elif args.command == "schema":
        result = get_table_schema(args.table)
    elif args.command == "sql":
        result = execute_sql(args.sql)
    elif args.command == "query":
        result = query_table(args.table, args.sql, page=args.page, page_size=args.page_size)
    elif args.command == "traverse":
        result = traverse_table(args.table, batch_size=args.batch_size, offset=args.offset)
    else:
        result = {"success": False, "error": f"Unknown command: {args.command}"}

    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
