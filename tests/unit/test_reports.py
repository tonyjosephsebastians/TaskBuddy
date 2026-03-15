from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT_DIR / "scripts" / "export_test_results.py"
SPEC = importlib.util.spec_from_file_location("taskbuddy_export_test_results", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_normalize_coverage_label_strips_bonus_prefix():
    assert MODULE.normalize_coverage_label("Bonus: Streaming") == "Streaming"
    assert MODULE.normalize_coverage_label(" bonus: Retry logic ") == "Retry logic"


def test_parse_junit_normalizes_coverage_labels(tmp_path: Path):
    report_path = tmp_path / "sample-junit.xml"
    report_path.write_text(
        """
        <testsuite tests="1">
          <testcase classname="tests.unit.test_sample" name="test_case" time="0.1" />
        </testsuite>
        """,
        encoding="utf-8",
    )
    metadata = {
        "tests.unit.test_sample::test_case": {
            "description": "Sample coverage mapping.",
            "coverage": ["Bonus: Streaming", "Execution trace"],
        }
    }

    rows = MODULE.parse_junit(report_path, "backend", metadata)

    assert rows[0]["coverage"] == ["Streaming", "Execution trace"]


def test_build_dashboard_omits_bonus_prefix_from_rendered_html():
    html_output = MODULE.build_dashboard(
        [
            {
                "suite": "backend",
                "key": "tests.unit.test_sample::test_case",
                "classname": "tests.unit.test_sample",
                "name": "test_case",
                "description": "Sample coverage mapping.",
                "coverage": ["Streaming", "Execution trace"],
                "status": "passed",
                "time": "0.1",
                "details": "",
            }
        ]
    )

    assert "Bonus:" not in html_output
    assert "&bull;" in html_output
