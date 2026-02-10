import typing
from typing import Optional, Union

from autocoder_nano.agent.agentic_edit_tools.base_tool_resolver import BaseToolResolver
from autocoder_nano.agent.agentic_edit_types import QueryDataTool, ToolResult
from autocoder_nano.actypes import AutoCoderArgs
from autocoder_nano.utils.printer_utils import Printer
from autocoder_nano.core import query_data_engine

if typing.TYPE_CHECKING:
    from autocoder_nano.agent.agentic_runtime import AgenticRuntime
    from autocoder_nano.agent.agentic_sub import SubAgents


printer = Printer()


class QueryDataToolResolver(BaseToolResolver):
    def __init__(self, agent: Optional[Union['AgenticRuntime', 'SubAgents']], tool: QueryDataTool,
                 args: AutoCoderArgs):
        super().__init__(agent, tool, args)
        self.tool: QueryDataTool = tool  # For type hinting

    def resolve(self) -> ToolResult:
        query_xql = self.tool.xql

        try:
            data_result = query_data_engine(query_xql)
            return ToolResult(success=True, message="数据查询成功.", content=data_result)
        except Exception as e:
            return ToolResult(success=False,
                              message=f"数据查询失败: {str(e)}")

    def guide(self) -> str:
        doc = """
        ## query_data（从数据库/本地文件json/http接口/查询数据）
        
        描述：
        
        - 用于从数据库，本地json/csv/parquet等格式文件，以及http接口，查询数据
        - 并且可以讲数据存储成不同格式
        
        参数：
        
        - xql（必填）：查询数据需要执行的sql语句
        
        用法说明：
        
        <query_data>
        <xql>select ...... from ...... where ......</xql>
        </query_data>
        
        xql的基本介绍
        
        - xql是在标准sql的基础上，针对大数据领域的多种数据源计算等场景，进行了语法拓展所形成的。
        - 底层使用duckdb作为核心计算引擎，对数据处理进行加速
        
        xql的语法说明
        
        - `load` 语句，加载不同数据源的数据
        - `select` 语句
            - xql `select` 语法与普通sql的略有不同，xql `select` 语法的最后需要加上 `as 临时表名`, 以便后面的语句可以继续使用
            - 同时 xql `select` 还新增了一个 `options` 语法，用于配置一些计算中使用到的参数
        - `save` 语句，可以将数据存储到不同的数据源
        
        用法示例：
        
        场景一：读取本地json文件，存储为本地parquet文件
        
        ```sql
        load json.`/Users/moofs/Code/my-data-warehouse/mydata.json` as raw_json_logs;
        select
          *
        from
          raw_json_logs
        limit
          10 as tmp;
        save overwrite tmp as parquet.`/Users/test.parquet` options COMPRESSION = "zstd";
        ```
        
        场景二：查询mysql数据库，存储为本地json文件
        
        ```sql
        load mysql.`db_name` options host = "192.168.1.1"
        and user = "root"
        and password = "123456"
        and port = "3306" as my_mysql;
        select
          *
        from
          my_mysql.table_name
        limit
          10 as tmp;
        save overwrite tmp as json.`/Users/my_mysql.json`;
        ```
        
        场景三：查询pg数据库，存储为本地json文件
        
        ```sql
        load postgres.`db_name` options host = ""
        and user = ""
        and password = ""
        and port = "" as my_pg;
        select
          *
        from
          my_pg.table_name
        limit
          10 as tmp;
        save overwrite tmp as json.`/Users/my_pg.json`;
        ```
        
        场景四：读取本地excel文件，存储为本地json文件
        
        ```sql
        load excel.`/Users/moofs/Code/my-data-warehouse/233000.xlsx` as raw_excel_data;
        select
          *
        from
          raw_excel_data
        limit
          10 as tmp;
        save overwrite tmp as json.`/Users/my_excel.json`;
        ```
        
        场景五：读取http远程文件数据，存储为本地json文件
        
        ```sql
        load http.`https://raw.githubusercontent.com/duckdb/duckdb/main/data/csv/16857.csv` as raw_http_file;
        select
          *
        from
          raw_http_file
        limit
          10 as tmp;
        save overwrite tmp as json.`/Users/moofs/Code/my-data-warehouse/my_http_file.json`;
        ```
        
        场景六：读取本地parquet文件，存储为本地csv文件
        
        ```sql
        load parquet.`/Users/moofs/Code/my-data-warehouse/test.parquet` as raw_parquet_file;
        select
          *
        from
          raw_parquet_file
        limit
          10 as tmp;
        save overwrite tmp as csv.`/Users/moofs/Code/my-data-warehouse/my_parquet_file.csv`;
        ```
        
        场景六：读取http远程文件数据，在终端中打印数据
        
        ```sql
        load http.`https://raw.githubusercontent.com/duckdb/duckdb/main/data/csv/16857.csv` as raw_http_file;
        select
          *
        from
          raw_http_file
        limit
          10 as tmp;
        save overwrite tmp as console.``;
        ```
        
        注意事项：
        
        - xql需要一次性生成并执行，包含load, select, save, 不要依次执行
        """
        return doc
