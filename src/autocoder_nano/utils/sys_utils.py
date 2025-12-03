import os
import subprocess
import sys

from autocoder_nano.actypes import EnvInfo

default_exclude_dirs = [
    ".git",
    ".svn",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
    ".auto-coder",
    "actions",
    ".vscode",
    ".idea",
    ".hg"
]


default_exclude_files = [
    ".DS_Store",  # 针对 osx 系统过滤
    "output.txt",
    ".gitignore"
]


def detect_env() -> EnvInfo:
    os_name = sys.platform
    os_version = ""
    if os_name == "win32":
        os_version = sys.getwindowsversion().major
    elif os_name == "darwin":
        os_version = (
            subprocess.check_output(["sw_vers", "-productVersion"]).decode("utf-8").strip()
        )
    elif os_name == "linux":
        os_version = subprocess.check_output(["uname", "-r"]).decode("utf-8").strip()

    python_version = (
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    )

    conda_env = os.environ.get("CONDA_DEFAULT_ENV")
    virtualenv = os.environ.get("VIRTUAL_ENV")

    # Get default shell
    if os_name == "win32":
        default_shell = os.environ.get("COMSPEC", "cmd.exe")
    else:
        default_shell = os.environ.get("SHELL", "/bin/sh")

    # Get home directory
    home_dir = os.path.expanduser("~")

    # Get current working directory
    cwd = os.getcwd()

    has_bash = True
    try:
        subprocess.check_output(["bash", "--version"])
    except:
        has_bash = False

    return EnvInfo(
        os_name=os_name,
        os_version=str(os_version),
        python_version=python_version,
        conda_env=conda_env,
        virtualenv=virtualenv,
        has_bash=has_bash,
        default_shell=default_shell,
        home_dir=home_dir,
        cwd=cwd,
    )
