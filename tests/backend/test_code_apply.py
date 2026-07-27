import subprocess

import pytest

from services.code_apply import ApplyError, FileChange, apply_changes


def _run(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(repo, "init", "-q")
    _run(repo, "config", "user.email", "test@test.com")
    _run(repo, "config", "user.name", "Test")
    (repo / "file.py").write_text("original content\n")
    _run(repo, "add", "file.py")
    _run(repo, "commit", "-q", "-m", "initial")
    return repo


def test_apply_changes_creates_branch_and_writes_files(git_repo):
    summary = apply_changes(
        str(git_repo), [FileChange(file_path="file.py", new_content="new content\n")], branch_name="allease/test"
    )

    assert summary.branch == "allease/test"
    assert summary.files_written == ["file.py"]
    assert (git_repo / "file.py").read_text() == "new content\n"

    current_branch = subprocess.run(
        ["git", "branch", "--show-current"], cwd=git_repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    assert current_branch == "allease/test"

    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=git_repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    assert "M file.py" in status


def test_apply_changes_rejects_dirty_working_tree(git_repo):
    (git_repo / "file.py").write_text("uncommitted edit\n")

    with pytest.raises(ApplyError, match="not clean"):
        apply_changes(str(git_repo), [FileChange(file_path="file.py", new_content="x")], branch_name="allease/test")


def test_apply_changes_rejects_existing_branch_name(git_repo):
    _run(git_repo, "branch", "allease/taken")

    with pytest.raises(ApplyError, match="already exists"):
        apply_changes(str(git_repo), [FileChange(file_path="file.py", new_content="x")], branch_name="allease/taken")


def test_apply_changes_rejects_path_traversal(git_repo):
    with pytest.raises(ApplyError, match="outside the repository"):
        apply_changes(
            str(git_repo), [FileChange(file_path="../../etc/passwd", new_content="x")], branch_name="allease/evil"
        )


def test_apply_changes_rejects_nonexistent_file(git_repo):
    with pytest.raises(ApplyError, match="does not exist"):
        apply_changes(
            str(git_repo), [FileChange(file_path="new_file.py", new_content="x")], branch_name="allease/new-file"
        )


def test_apply_changes_rejects_non_local_or_non_git_directory(tmp_path):
    plain_dir = tmp_path / "not-a-repo"
    plain_dir.mkdir()

    with pytest.raises(ApplyError, match="does not look like a git repository"):
        apply_changes(str(plain_dir), [FileChange(file_path="x", new_content="x")], branch_name="allease/x")


def test_apply_changes_rejects_missing_directory():
    with pytest.raises(ApplyError, match="not an existing local directory"):
        apply_changes("/no/such/path", [FileChange(file_path="x", new_content="x")], branch_name="allease/x")
