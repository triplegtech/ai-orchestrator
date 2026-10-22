"""Isolated workspaces backed by git worktrees, one branch per task."""

from __future__ import annotations

import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from ai_orchestrator.orchestration.policies import path_matches


class GitError(RuntimeError):
    pass


def git(cwd: str | Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} falhou: {proc.stderr.strip()}")
    return proc.stdout


@dataclass
class Workspace:
    repo_path: str
    task_dir: str
    path: str
    branch: str
    base_sha: str

    def to_dict(self) -> dict:
        return asdict(self)


class GitWorkspaceManager:
    def __init__(self, root: Path, ignored_paths: list[str] | None = None):
        self.root = Path(root)
        # Build/test artifacts: never reported as changes, never committed.
        self.ignored_paths = ignored_paths or []

    def _exclude_pathspecs(self) -> list[str]:
        return ["--", ".", *(f":(exclude,glob){p}" for p in self.ignored_paths)]

    def resolve_repo(self, repo_path: str) -> str:
        return git(repo_path, "rev-parse", "--show-toplevel").strip()

    def resolve_ref(self, repo_path: str, ref: str) -> str:
        return git(repo_path, "rev-parse", "--verify", f"{ref}^{{commit}}").strip()

    def has_uncommitted_changes(self, repo_path: str) -> bool:
        return bool(git(repo_path, "status", "--porcelain").strip())

    def tracked_files(self, repo_path: str, sha: str) -> list[str]:
        return git(repo_path, "ls-tree", "-r", "--name-only", sha).splitlines()

    def create(self, repo_path: str, task_id: str, base_sha: str) -> Workspace:
        task_dir = self.root / task_id
        path = task_dir / "worktree"
        branch = f"agents/{task_id.lower()}"
        task_dir.mkdir(parents=True, exist_ok=True)
        git(repo_path, "worktree", "add", "-b", branch, str(path), base_sha)
        return Workspace(repo_path, str(task_dir), str(path), branch, base_sha)

    def changed_files(self, ws: Workspace) -> list[str]:
        """Files differing from the base commit: committed, staged, unstaged and untracked."""
        tracked = git(ws.path, "diff", "--name-only", "--no-renames", ws.base_sha).splitlines()
        untracked = git(ws.path, "ls-files", "--others", "--exclude-standard").splitlines()
        paths = {p.strip() for p in tracked + untracked if p.strip()}
        return sorted(p for p in paths if not path_matches(p, self.ignored_paths))

    def diff(self, ws: Workspace, max_chars: int = 80_000) -> str:
        git(ws.path, "add", "--intent-to-add", "--all", *self._exclude_pathspecs())
        text = git(ws.path, "diff", "--stat", "--patch", ws.base_sha, *self._exclude_pathspecs())
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n\n[diff truncado em {max_chars} caracteres]"
        return text

    def commit(self, ws: Workspace, message: str) -> str | None:
        git(ws.path, "add", "--all", *self._exclude_pathspecs())
        if not git(ws.path, "diff", "--cached", "--name-only").strip():
            return None
        git(
            ws.path,
            "-c", "user.name=ai-orchestrator",
            "-c", "user.email=ai-orchestrator@localhost",
            "commit", "--no-verify", "-m", message,
        )
        return git(ws.path, "rev-parse", "HEAD").strip()
