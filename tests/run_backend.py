"""Run the backend tests.

    runtime\\python.exe -B tests\\run_backend.py                      all tests
    runtime\\python.exe -B tests\\run_backend.py test_server test_launcher   chosen modules

The backend modules live in backend/ and import each other by name, and some
tests import shared fixtures from other test modules, so both folders go on
the import path first. Use the bundled runtime: it has requirements.txt installed.
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
TESTS = HERE / 'backend'
for folder in (TESTS, ROOT / 'backend'):
    sys.path.insert(0, str(folder))

if __name__ == '__main__':
    names = [arg for arg in sys.argv[1:] if not arg.startswith('-')]
    options = [arg for arg in sys.argv[1:] if arg.startswith('-')]
    if names:
        unittest.main(module=None, argv=[sys.argv[0], *options, *names])
    else:
        unittest.main(module=None, argv=[sys.argv[0], 'discover', '-s', str(TESTS), '-t', str(TESTS),
                                         '-p', 'test_*.py', *options])
