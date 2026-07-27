from services.review_signals import check_test_coverage, scan_for_secrets

_DIFF_WITH_SECRET = """diff --git a/config.py b/config.py
index abc..def 100644
--- a/config.py
+++ b/config.py
@@ -1,2 +1,4 @@
 import os
+api_key = "sk-abcdefghij1234567890"
+DEBUG = True
 x = 1
"""

_DIFF_WITHOUT_SECRET = """diff --git a/config.py b/config.py
index abc..def 100644
--- a/config.py
+++ b/config.py
@@ -1,2 +1,3 @@
 import os
+DEBUG = True
 x = 1
"""


def test_scan_for_secrets_flags_api_key_shaped_string():
    findings = scan_for_secrets(_DIFF_WITH_SECRET)

    assert len(findings) == 1
    assert findings[0].category == "security"
    assert findings[0].severity == "high"
    assert findings[0].file_path == "config.py"
    assert findings[0].line == 2


def test_scan_for_secrets_ignores_unrelated_additions():
    assert scan_for_secrets(_DIFF_WITHOUT_SECRET) == []


def test_check_test_coverage_flags_file_with_no_matching_test(tmp_path):
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "foo.py").touch()

    findings = check_test_coverage(str(tmp_path), ["backend/foo.py"])

    assert len(findings) == 1
    assert findings[0].category == "test_coverage"
    assert findings[0].file_path == "backend/foo.py"


def test_check_test_coverage_finds_test_in_sibling_tests_dir(tmp_path):
    (tmp_path / "backend" / "tests").mkdir(parents=True)
    (tmp_path / "backend" / "foo.py").touch()
    (tmp_path / "backend" / "tests" / "test_foo.py").touch()

    assert check_test_coverage(str(tmp_path), ["backend/foo.py"]) == []


def test_check_test_coverage_skips_test_files_themselves(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_foo.py").touch()

    assert check_test_coverage(str(tmp_path), ["tests/test_foo.py"]) == []
