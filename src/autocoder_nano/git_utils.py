import os

from git import Repo, GitCommandError
from loguru import logger

from autocoder_nano.llm_types import CommitResult


def repo_init(repo_path: str) -> bool:
    if not os.path.exists(repo_path):
        os.makedirs(repo_path)

    if os.path.exists(os.path.join(repo_path, ".git")):
        logger.warning(f"目录 {repo_path} 已是一个 Git 仓库，跳过初始化操作。")
        return False
    try:
        Repo.init(repo_path)
        logger.info(f"已在 {repo_path} 初始化新的 Git 仓库")
        return True
    except GitCommandError as e:
        logger.error(f"Git 初始化过程中发生错误: {e}")
        return False


def get_repo(repo_path: str) -> Repo:
    repo = Repo(repo_path)
    return repo


def commit_changes(repo_path: str, message: str) -> CommitResult:
    repo = get_repo(repo_path)
    if repo is None:
        return CommitResult(
            success=False, error_message="Repository is not initialized."
        )

    try:
        repo.git.add(all=True)
        if repo.is_dirty():
            commit = repo.index.commit(message)
            result = CommitResult(
                success=True,
                commit_message=message,
                commit_hash=commit.hexsha,
                changed_files=[],
                diffs={},
            )
            if commit.parents:
                changed_files = repo.git.diff(
                    commit.parents[0].hexsha, commit.hexsha, name_only=True
                ).split("\n")
                result.changed_files = [file for file in changed_files if file.strip()]

                for file in result.changed_files:
                    diff = repo.git.diff(
                        commit.parents[0].hexsha, commit.hexsha, "--", file
                    )
                    result.diffs[file] = diff
            else:
                result.error_message = (
                    "This is the initial commit, no parent to compare against."
                )

            return result
        else:
            return CommitResult(success=False, error_message="No changes to commit.")
    except GitCommandError as e:
        return CommitResult(success=False, error_message=str(e))


def revert_changes(repo_path: str, message: str) -> bool:
    repo = get_repo(repo_path)
    if repo is None:
        logger.error("仓库未初始化。")
        return False

    try:
        # 检查当前工作目录是否有未提交的更改
        if repo.is_dirty():
            logger.warning("工作目录有未提交的更改，请在回退前提交或暂存您的修改。")
            return False

        # 通过message定位到commit_hash
        commit = repo.git.log("--all", f"--grep={message}", "--format=%H", "-n", "1")
        if not commit:
            logger.warning(f"未找到提交信息包含 '{message}' 的提交记录。")
            return False

        commit_hash = commit

        # 获取从指定commit到HEAD的所有提交
        commits = list(repo.iter_commits(f"{commit_hash}..HEAD"))

        if not commits:
            repo.git.revert(commit, no_edit=True)
            logger.info(f"已回退单条提交记录: {commit}")
        else:
            # 从最新的提交开始，逐个回滚
            for commit in reversed(commits):
                try:
                    repo.git.revert(commit.hexsha, no_commit=True)
                    logger.info(f"已回退提交 {commit.hexsha} 的更改")
                except GitCommandError as e:
                    logger.error(f"回退提交 {commit.hexsha} 时发生错误: {e}")
                    repo.git.revert("--abort")
                    return False
            # 提交所有的回滚更改
            repo.git.commit(message=f"Reverted all changes up to {commit_hash}")
        logger.info(f"已成功回退到提交 {commit_hash} 的状态")
        # this is a mark, chat_auto_coder.py need this
        print(f"Successfully reverted changes", flush=True)
        return True
    except GitCommandError as e:
        logger.error(f"回退操作过程中发生错误: {e}")
        return False