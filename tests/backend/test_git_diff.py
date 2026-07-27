import subprocess

import pytest

from services.git_diff import GitDiffError, get_changed_files, get_diff


def _run(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(repo, "init", "-q")
    _run(repo, "config", "user.email", "test@test.com")
    _run(repo, "config", "user.name", "Test")
    (repo / "file.py").write_text("line1\n")
    _run(repo, "add", "file.py")
    _run(repo, "commit", "-q", "-m", "initial")
    base_branch = subprocess.run(
        ["git", "branch", "--show-current"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()

    _run(repo, "checkout", "-q", "-b", "feature")
    (repo / "file.py").write_text("line1\nline2 added\n")
    _run(repo, "add", "file.py")
    _run(repo, "commit", "-q", "-m", "add line2")
    _run(repo, "checkout", "-q", base_branch)

    return repo


def test_get_changed_files_lists_modified_files(git_repo):
    files = get_changed_files(str(git_repo), "HEAD", "feature")

    assert files == ["file.py"]


def test_get_diff_shows_added_line(git_repo):
    diff_text = get_diff(str(git_repo), "HEAD", "feature")

    assert "+line2 added" in diff_text
    assert "file.py" in diff_text


def test_get_diff_raises_clear_error_for_unknown_ref(git_repo):
    with pytest.raises(GitDiffError, match="no-such-ref"):
        get_diff(str(git_repo), "HEAD", "no-such-ref")
