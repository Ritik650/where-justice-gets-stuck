"""Publish site/ to the gh-pages branch, which GitHub Pages serves.

    python -I pipeline/build_site.py
    python -I pipeline/publish_site.py           commit the built site to gh-pages locally
    python -I pipeline/publish_site.py --push    ...and push it

It works in a temporary git worktree, so the current branch and working tree are never touched. The commit uses the
repository's own git identity (git config user.name and user.email), and the branch holds only the built files.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
BRANCH = "gh-pages"


def git(*args: str, cwd: Path = ROOT, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, check=check, capture_output=True, text=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--push", action="store_true", help="push gh-pages to origin after committing")
    a = ap.parse_args()
    if not (SITE / "index.html").exists():
        sys.exit("no site/ yet: run python -I pipeline/build_site.py first")
    source = git("rev-parse", "--short", "HEAD").stdout.strip()
    tmp = Path(tempfile.mkdtemp(prefix="wjgs-pages-"))
    worktree = tmp / "pages"
    try:
        git("fetch", "origin", BRANCH, check=False)
        if git("rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{BRANCH}", check=False).returncode == 0:
            git("worktree", "add", "-B", BRANCH, str(worktree), f"origin/{BRANCH}")
        elif git("rev-parse", "--verify", "--quiet", f"refs/heads/{BRANCH}", check=False).returncode == 0:
            git("worktree", "add", str(worktree), BRANCH)
        else:
            git("worktree", "add", "--orphan", "-b", BRANCH, str(worktree))
        for item in worktree.iterdir():
            if item.name != ".git":
                shutil.rmtree(item) if item.is_dir() else item.unlink()
        shutil.copytree(SITE, worktree, dirs_exist_ok=True)
        git("add", "-A", cwd=worktree)
        if git("diff", "--cached", "--quiet", cwd=worktree, check=False).returncode == 0:
            print("gh-pages already matches site/; nothing to commit", flush=True)
        else:
            git("commit", "-q", "-m", f"Publish the static dashboard built from {source}", cwd=worktree)
            print(f"committed site/ to {BRANCH} ({git('rev-parse', '--short', 'HEAD', cwd=worktree).stdout.strip()})", flush=True)
        if a.push:
            out = git("push", "origin", f"{BRANCH}:{BRANCH}", cwd=worktree)
            print((out.stdout + out.stderr).strip(), flush=True)
    finally:
        git("worktree", "remove", "--force", str(worktree), check=False)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
