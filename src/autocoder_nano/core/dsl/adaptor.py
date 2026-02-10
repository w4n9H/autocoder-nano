import duckdb
import pandas as pd
from urllib.parse import urlparse
import os

from autocoder_nano.core.dsl.parser.DSLSQLParser import DSLSQLParser
from autocoder_nano.core.dsl.parser.DSLSQLLexer import DSLSQLLexer
from autocoder_nano.core.dsl.parser.DSLSQLListener import DSLSQLListener

from antlr4 import InputStream, CommonTokenStream, ParseTreeWalker


def singleton(class_):
    instances = {}

    def getinstance(*args, **kwargs):
        if class_ not in instances:
            instances[class_] = class_(*args, **kwargs)
        return instances[class_]

    return getinstance


class DslAdaptor:
    @staticmethod
    def clean_str(raw_str):
        if raw_str.startswith("`") or raw_str.startswith("\""):
            raw_str = raw_str.replace("`", "").replace("\"", "")
        if raw_str.startswith("'''"):
            raw_str = raw_str[3: len(raw_str) - 3]
        return raw_str

    @staticmethod
    def get_original_text(ctx):
        _input = ctx.start.getTokenSource()._input
        return _input.getText(ctx.start.start, ctx.stop.stop)


class ConnectAdaptor(DslAdaptor):
    def __init__(self, xql_listener):
        self.xql_listener = xql_listener

    def parse(self, ctx):
        option = dict()
        for i in range(ctx.getChildCount()):
            _type = ctx.getChild(i)
            if isinstance(_type, DSLSQLParser.Format_typeContext):
                option["format"] = _type.getText()
            if isinstance(_type, DSLSQLParser.ExpressionContext):
                option[self.clean_str(
                    _type.identifier().getText())] = self.clean_str(
                    _type.STRING().getText())
            if isinstance(_type, DSLSQLParser.BooleanExpressionContext):
                option[self.clean_str(_type.expression().identifier().getText())] = self.clean_str(
                    _type.expression().STRING().getText())
            if isinstance(_type, DSLSQLParser.DbContext):
                self.xql_listener.set_connect_options(_type.getText(), option)


class CreateAdaptor(DslAdaptor):
    def __init__(self, xql_listener):
        self.xql_listener = xql_listener

    def parse(self, ctx):
        original_text = self.get_original_text(ctx)
        conn = self.xql_listener.get_connection()
        try:
            conn.execute(original_text)
        except duckdb.OperationalError as e:
            raise Exception(f"Error executing Create: {e}")


class DropAdaptor(DslAdaptor):
    def __init__(self, xql_listener):
        self.xql_listener = xql_listener

    def parse(self, ctx):
        original_text = self.get_original_text(ctx)
        conn = self.xql_listener.get_connection()
        try:
            conn.execute(original_text)
        except duckdb.OperationalError as e:
            raise Exception(f"Error executing Drop: {e}")


class InsertAdaptor(DslAdaptor):
    def __init__(self, xql_listener):
        self.xql_listener = xql_listener

    def parse(self, ctx):
        original_text = self.get_original_text(ctx)
        conn = self.xql_listener.get_connection()
        try:
            conn.execute(original_text)
        except duckdb.OperationalError as e:
            raise Exception(f"Error executing Insert: {e}")


class LoadAdaptor(DslAdaptor):
    def __init__(self, xql_listener):
        self.xql_listener = xql_listener

    def parse(self, ctx):
        option = dict()
        format_type, path, table_name = "", "", ""
        for i in range(ctx.getChildCount()):
            _type = ctx.getChild(i)
            # Format Get
            if isinstance(_type, DSLSQLParser.Format_typeContext):
                format_type = _type.getText()

            if isinstance(_type, DSLSQLParser.PathContext):
                path = self.clean_str(_type.getText())
                path = path.format(**self.xql_listener.get_env())

            if isinstance(_type, DSLSQLParser.TableNameContext):
                table_name = _type.getText()

            if isinstance(_type, DSLSQLParser.ExpressionContext):
                option[_type.identifier().getText()] = self.clean_str(_type.STRING().getText())
            if isinstance(_type, DSLSQLParser.BooleanExpressionContext):
                option[_type.expression().identifier().getText()] = self.clean_str(
                    _type.expression().STRING().getText())

        conn: duckdb.DuckDBPyConnection = self.xql_listener.get_connection()
        fmt_lower = format_type.lower()
        # --- 处理需要扩展的数据源 ---
        if fmt_lower in ['http', 'https', 's3']:
            conn.install_extension("httpfs")
            conn.load_extension("httpfs")
            # http/https
            sql_to_execute = self._load_http(path, table_name, option)
        elif fmt_lower in ['mysql', 'postgres']:
            ext_name = fmt_lower if fmt_lower != 'mysql' else 'mysql_scanner'  # DuckDB中使用mysql_scanner
            conn.install_extension(ext_name)
            conn.load_extension(ext_name)
            sql_to_execute = self._attach_sql_db(fmt_lower, path, table_name, option)
        elif fmt_lower in ['json', 'csv', 'parquet', 'excel']:
            if fmt_lower == "excel":
                conn.install_extension('spatial')
                conn.load_extension('spatial')
            sql_to_execute = self._load_file(fmt_lower, path, table_name, option)
        elif fmt_lower == 'sqlite':
            sql_to_execute = self._attach_sqlite(path, table_name)
        else:
            raise ValueError(f"Unsupported source type: '{format_type}'")

        try:
            conn.execute(sql_to_execute)
        except duckdb.OperationalError as e:
            raise Exception(f"Error executing Load: {e}")

    @staticmethod
    def _load_file(fmt: str, path: str, table_name: str, options: dict) -> str:
        """ 加载本地/远程文件（json, csv, parquet等）"""
        options_str = ""
        if options:
            param_parts = [f"{k}='{v}'" for k, v in options.items()]
            options_str = ", " + ", ".join(param_parts)

        read_function = f"read_{fmt}_auto"  # 优先使用auto
        # 如果用户提供了可能绕过auto的关键选项（如delim, header），则使用非auto函数
        if fmt == 'excel':  # excel 是独立函数
            read_function = f"st_read"
        if fmt == 'parquet':    # parquet 不支持 auto模式
            read_function = f"read_parquet"
        if fmt == 'csv' and any(k in options for k in ['delim', 'quote', 'escape', 'header']):
            read_function = f"read_{fmt}"

        sql_to_execute = f"CREATE OR REPLACE VIEW {table_name} AS SELECT * FROM {read_function}('{path}'{options_str})"
        return sql_to_execute

    @staticmethod
    def _load_http(url: str, table_name: str, options: dict) -> str:
        """ 加载HTTP/HTTPS资源 """
        # httpfs扩展会直接在read_*函数中支持URL
        # 选项可以作为URL参数或read_函数的参数传递
        headers_str = ""
        if 'headers_json' in options:
            headers_str = f", headers={options['headers_json']}"

        # 自动检测文件类型，也可以强制指定
        # e.g., read_json_auto(url) or read_csv_auto(url)
        parsed_url = urlparse(url)
        _, suffix = os.path.splitext(os.path.basename(parsed_url.path))
        if not suffix:
            suffix = 'json'
        read_function = f"read_{suffix.strip('.')}_auto"

        sql_to_execute = f"CREATE OR REPLACE VIEW {table_name} AS SELECT * FROM {read_function}('{url}'{headers_str})"
        return sql_to_execute

    @staticmethod
    def _attach_sql_db(db_type: str, path: str, temp_table_name: str, options: dict) -> str:
        """ ATTACH MySQL/PostgreSQL数据库 """
        host = options.get('host', 'localhost')
        user = options.get('user', 'root')
        password = options.get('password', '')
        port = options.get('port', '3306')
        database = path.split('.')[0]
        if db_type == 'mysql':
            source_str = f"host={host} user={user} passwd={password} port={port} db={database}"
        elif db_type == 'postgres':
            source_str = f"host={host} user={user} password={password} port={port} dbname={database}"
        else:
            raise ValueError(f"DB type {db_type} not supported for ATTACH.")

        sql_to_execute = f"ATTACH '{source_str}' AS {temp_table_name} (TYPE {db_type.lower()});"
        return sql_to_execute

    @staticmethod
    def _attach_sqlite(db_path, table_name) -> str:
        """ ATTACH SQLite数据库 """
        # SQLite ATTACH最简单
        sql_to_execute = f"ATTACH '{db_path}' AS {table_name} (TYPE SQLITE)"
        return sql_to_execute


class SaveAdaptor(DslAdaptor):
    def __init__(self, xql_listener):
        self.xql_listener = xql_listener

    def parse(self, ctx):
        option = dict()
        mode, final_path, format_type, table_name = "", "", "", ""
        partition_by_col = []
        for i in range(ctx.getChildCount()):
            _type = ctx.getChild(i)

            if isinstance(_type, DSLSQLParser.Format_typeContext):
                format_type = _type.getText()

            if isinstance(_type, DSLSQLParser.PathContext):
                final_path = self.clean_str(_type.getText())
                final_path = final_path.format(**self.xql_listener.get_env())

            if isinstance(_type, DSLSQLParser.TableNameContext):
                table_name = _type.getText()

            if isinstance(_type, DSLSQLParser.OverwriteContext):
                mode = _type.getText()
            if isinstance(_type, DSLSQLParser.AppendContext):
                mode = _type.getText()
            if isinstance(_type, DSLSQLParser.ErrorIfExistsContext):
                mode = _type.getText()
            if isinstance(_type, DSLSQLParser.IgnoreContext):
                mode = _type.getText()

            if isinstance(_type, DSLSQLParser.ColContext):
                partition_by_col = _type.getText().split(",")

            if isinstance(_type, DSLSQLParser.ExpressionContext):
                option[self.clean_str(_type.identifier().getText())] = self.clean_str(_type.STRING().getText())
            if isinstance(_type, DSLSQLParser.BooleanExpressionContext):
                option[self.clean_str(_type.expression().identifier().getText())] = self.clean_str(
                    _type.expression().STRING().getText())

        conn = self.xql_listener.get_connection()
        if format_type == "console":
            max_rows = option.get('max_rows', 20)
            max_columns = option.get('max_columns', 10)
            sql_to_execute = f"SELECT * FROM {table_name} LIMIT {max_rows};"
            df: pd.DataFrame = conn.execute(sql_to_execute).fetchdf()
            # 打印表格
            pd.set_option('display.max_rows', int(max_rows))
            pd.set_option('display.max_columns', int(max_columns))
            pd.set_option('display.width', None)
            print(df.to_string(index=False))
        else:
            # 构建 COPY 命令的选项
            copy_options = [f"FORMAT {format_type.upper()}"]
            if mode:
                mode_map = {
                    "overwrite": "OVERWRITE",
                    "append": "APPEND",
                    "errorIfExists": "",  # DuckDB 默认行为
                    "ignore": ""  # DuckDB 默认行为
                }
                if mode_map.get(mode):
                    if format_type.upper() == 'JSON':  # json 不支持OVERWRITE
                        pass
                    else:
                        copy_options.append(mode_map[mode])

            if partition_by_col:
                copy_options.append(f"PARTITION_BY ({','.join(partition_by_col)})")

            # 将 option 字典转换为 COPY 选项, 例如: {"compression": "gzip"} -> ", COMPRESSION 'gzip'"
            if option:
                for key, value in option.items():
                    copy_options.append(f"{key.upper()} '{value}'")

            options_str = ""
            if copy_options:
                options_str = f" ({', '.join(copy_options)})"

            sql_to_execute = f"COPY {table_name} TO '{final_path}'{options_str}"
            try:
                conn.execute(sql_to_execute)
            except duckdb.OperationalError as e:
                raise Exception(f"Error executing SAVE: {e}")


class SelectAdaptor(DslAdaptor):
    def __init__(self, xql_listener):
        self.xql_listener = xql_listener

    def parse(self, ctx):
        original_text = self.get_original_text(ctx)

        chunks = original_text.split(" ")
        origin_table_name = chunks[-1].replace(";", "")
        xql = original_text.replace("as {}".format(origin_table_name), "")

        # 在 DuckDB 中创建一个视图，这样后续的 XQL 语句就可以引用这个表了
        sql_to_execute = f"CREATE OR REPLACE VIEW {origin_table_name} AS {xql}"

        try:
            conn = self.xql_listener.get_connection()
            conn.execute(sql_to_execute)
        except duckdb.OperationalError as e:
            raise Exception(f"Error executing SELECT: {e}")

        self.xql_listener.set_last_select_table(origin_table_name)


class SetAdaptor(DslAdaptor):
    def __init__(self, xql_listener):
        self.xql_listener = xql_listener

    def parse(self, ctx):
        option = dict()
        set_key, set_value = "", ""
        for i in range(ctx.getChildCount()):
            _type = ctx.getChild(i)
            if isinstance(_type, DSLSQLParser.SetKeyContext):
                set_key = _type.getText()
            if isinstance(_type, DSLSQLParser.SetValueContext):
                set_value = self.clean_str(_type.getText())
            if isinstance(_type, DSLSQLParser.ExpressionContext):
                option[self.clean_str(
                    _type.identifier().getText())] = self.clean_str(
                        _type.STRING().getText())
            if isinstance(_type, DSLSQLParser.BooleanExpressionContext):
                option[self.clean_str(_type.expression().identifier().
                                      getText())] = self.clean_str(
                                          _type.expression().STRING().getText())
        self.xql_listener.add_env(set_key, set_value)
        self.xql_listener.set_last_select_table(None)


class XQLExec:
    @classmethod
    def parse_xql(cls, input_xql, listener):
        lexer = DSLSQLLexer(InputStream(input_xql))
        tokens = CommonTokenStream(lexer)
        parse = DSLSQLParser(tokens)
        tree = parse.statement()
        ParseTreeWalker().walk(listener, tree)


@singleton
class XQLExecListener(DSLSQLListener):
    def __init__(self):
        self._env = dict()
        self._last_select_table = None
        self._tmp_tables = set()
        self._connect_options = dict()
        self._conn = None  # 用于持有 DuckDB 连接
        self.AdaptorDict = {
            "load": LoadAdaptor(self),
            "connect": ConnectAdaptor(self),
            "select": SelectAdaptor(self),
            "save": SaveAdaptor(self),
            "create": CreateAdaptor(self),
            "insert": InsertAdaptor(self),
            "drop": DropAdaptor(self),
            "set": SetAdaptor(self)
        }

    def get_connection(self) -> duckdb.DuckDBPyConnection:
        """ 获取或创建 DuckDB 连接,懒加载需要时创建 """
        if self._conn is None:
            self._conn = duckdb.connect()
        return self._conn

    def close_connection(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def execute_to_df(self, input_xql) -> pd.DataFrame:
        conn = self.get_connection()
        return conn.execute(input_xql).fetchdf()

    def to_df(self, table_name: str) -> pd.DataFrame:
        """ 将 DuckDB 中的表或视图安全地转换为 Pandas DataFrame """
        if not self._conn:
            raise Exception("Engine not initialized. Please parse an XQL script first.")
        try:
            return self._conn.execute(f"SELECT * FROM {table_name}").fetchdf()
        except duckdb.OperationalError as e:
            raise ValueError(f"Table or view '{table_name}' not found or is invalid. Original error: {e}")

    def set_last_select_table(self, table_name):
        self._last_select_table = table_name

    def get_last_select_table(self):
        return self._last_select_table

    def set_connect_options(self, k, v):
        self._connect_options[k] = v

    def get_connect_options(self):
        return self._connect_options

    def get_tmp_tables(self):
        return self._tmp_tables

    def add_tmp_tables(self, table_name):
        self._tmp_tables.add(table_name)

    def add_env(self, key, value):
        self._env[key] = value
        return self

    def get_env(self):
        return self._env

    def exitSql(self, ctx):
        self.AdaptorDict.get(ctx.getChild(0).getText().lower()).parse(ctx)


def run_xql(sql: str):
    lister = XQLExecListener()
    p = XQLExec()
    p.parse_xql(sql, lister)


def main():
    xql_json_script = """
    load json.`/Users/moofs/Code/my-data-warehouse/mydata.json` as raw_json_logs;
    select * from raw_json_logs limit 10 as tmp;
    save overwrite tmp as parquet.`/Users/test.parquet` options COMPRESSION="zstd";
    """

    xql_mysql_script = """
    load mysql.`db_name` options host="" and user="" and password="" and port="" as my_mysql;
    select * from my_mysql.table_name limit 10 as tmp;
    save overwrite tmp as json.`/Users/my_mysql.json`;
    """

    xql_pg_script = """
    load postgres.`db_name` options host="" and user="" and password="" and port="" as my_pg;
    select * from my_pg.table_name limit 10 as tmp;
    save overwrite tmp as json.`/Users/my_pg.json`;
    """

    xql_excel_script = """
    load excel.`/Users/moofs/Code/my-data-warehouse/233000.xlsx` as raw_excel_data;
    select * from raw_excel_data limit 10 as tmp;
    save overwrite tmp as json.`/Users/my_excel.json`;
    """

    xql_http_json_api = """
    load http.`https://api.github.com/repos/duckdb/duckdb/releases` as raw_http_json; 
    select * from raw_http_json limit 10 as tmp;
    save overwrite tmp as json.`/Users/moofs/Code/my-data-warehouse/my_http_json.json`;
    """

    xql_http_file_script = """
    load http.`https://raw.githubusercontent.com/duckdb/duckdb/main/data/csv/16857.csv` as raw_http_file;
    select * from raw_http_file limit 10 as tmp;
    save overwrite tmp as json.`/Users/moofs/Code/my-data-warehouse/my_http_file.json`;
    """

    xql_parquet_script = """
    load parquet.`/Users/moofs/Code/my-data-warehouse/test.parquet` as raw_parquet_file;
    select * from raw_parquet_file limit 10 as tmp;
    save overwrite tmp as csv.`/Users/moofs/Code/my-data-warehouse/my_parquet_file.csv`;
    """

    xql_show_script = """
    load http.`https://raw.githubusercontent.com/duckdb/duckdb/main/data/csv/16857.csv` as raw_http_file;
    select * from raw_http_file limit 10 as tmp;
    save overwrite tmp as console.``;
    """
    run_xql(xql_show_script)


if __name__ == '__main__':
    main()

