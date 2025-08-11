import os
import platform
import subprocess
import sys

import psutil


def get_windows_parent_process_name():
    """
    获取当前进程的父进程名（仅在Windows系统下有意义）。

    适用场景：
    - 判断命令是否由PowerShell或cmd.exe启动，以便调整命令格式。
    - 在Windows平台上进行父进程分析。

    参数：
    - 无

    返回：
    - str|None: 父进程名（小写字符串，如"powershell.exe"或"cmd.exe"），如果无法获取则为None。

    异常：
    - 捕获所有异常，返回None。
    """
    try:
        current_process = psutil.Process()
        while True:
            parent = current_process.parent()
            if parent is None:
                break
            parent_name = parent.name().lower()
            if parent_name in ["powershell.exe", "cmd.exe"]:
                return parent_name
            current_process = parent
        return None
    except Exception:
        return None


def run_cmd_subprocess(command, verbose=False, cwd=None, encoding=sys.stdout.encoding):
    if verbose:
        print("Using run_cmd_subprocess:", command)

    try:
        shell = os.environ.get("SHELL", "/bin/sh")
        parent_process = None

        # Determine the appropriate shell
        if platform.system() == "Windows":
            parent_process = get_windows_parent_process_name()
            if parent_process == "powershell.exe":
                command = f"powershell -Command {command}"

        if verbose:
            print("Running command:", command)
            print("SHELL:", shell)
            if platform.system() == "Windows":
                print("Parent process:", parent_process)

        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            shell=True,
            encoding=encoding,
            errors="replace",
            bufsize=0,  # Set bufsize to 0 for unbuffered output
            universal_newlines=True,
            cwd=cwd,
        )

        output = []
        while True:
            chunk = process.stdout.read(1)
            if not chunk:
                break
            # print(chunk, end="", flush=True)  # Print the chunk in real-time
            output.append(chunk)  # Store the chunk for later use

        process.wait()
        return process.returncode, "".join(output)
    except Exception as e:
        return 1, str(e)