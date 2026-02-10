import io
from contextlib import redirect_stdout

from autocoder_nano.core.dsl.adaptor import run_xql


def query_data_engine(sql: str):
    output_buffer = io.StringIO()

    with redirect_stdout(output_buffer):
        run_xql(sql)

    captured_output = output_buffer.getvalue()
    return captured_output


__all__ = ["query_data_engine"]