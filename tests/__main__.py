import os
import sys
import subprocess
import unittest

import coverage
import coverage.exceptions as _cov_exceptions


TEST_DIR_NAME = "tests"
TEST_NAME_PATTERN = "test_*.py"
OMITTED_FILES = ["__init__.py", "tests/__main__.py", "*_pb2.py"]
HTML_REPORT_FLAG = "-h"


def _report_coverage(cov: coverage.Coverage, html) -> None:
    if html:
        cov.html_report()
        subprocess.run(["open", "htmlcov/index.html"])
    else:
        try:
            cov.report()
        except _cov_exceptions.NoDataError:
            print("No data from coverage analysis to report.")
        except Exception as e:
            print(f"Problem reporting coverage. {e}")


def _run_tests(show_test_names: bool = True) -> None:
    possible_paths = [os.path.join(TEST_DIR_NAME, path) for path in sys.argv[1:]]
    if not possible_paths:
        _run_all_tests()
    else:
        _run_selected_tests(possible_paths, show_test_names)


def _run_all_tests() -> None:
    suite = unittest.TestSuite()
    suite.addTests(unittest.TestLoader().discover(TEST_DIR_NAME, pattern=TEST_NAME_PATTERN))


def _run_selected_tests(possible_paths: list[str], show_test_names: bool) -> None:
    suite = unittest.TestSuite()
    paths: list[str] = list()
    for path in possible_paths:
        if os.path.exists(path):
            paths.append(path)
        else:
            print(f"Path '{path}' does not exist. Skipping.")
    for path in paths:
        if os.path.isfile(path) and path.endswith(".py"):
            pattern, directory = os.path.basename(path), os.path.dirname(path)
        else:
            pattern, directory = "test_*.py", path
        suite.addTests(unittest.TestLoader().discover(directory, pattern=pattern))
    verbosity = 2 if show_test_names else 1
    unittest.TextTestRunner(verbosity=verbosity, buffer=True).run(suite)


if __name__ == "__main__":
    html = False
    if "-h" in sys.argv:
        html = True
        sys.argv.remove("-h")
    cov = coverage.Coverage(branch=True, omit=OMITTED_FILES)
    cov.start()
    _run_tests()
    cov.stop()
    cov.save()
    _report_coverage(cov, html)
