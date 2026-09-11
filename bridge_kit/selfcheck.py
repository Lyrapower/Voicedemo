"""selfcheck — 数用例不数日志行(MONEY_BUG 案 4)。任何失败 exit 1。"""
import sys
import unittest


def main():
    suite = unittest.defaultTestLoader.discover("bridge_kit/tests", top_level_dir=".")
    res = unittest.TextTestRunner(verbosity=1, stream=sys.stderr).run(suite)
    passed = res.testsRun - len(res.failures) - len(res.errors) - len(res.skipped)
    print("bridge_kit selfcheck: %d passed / %d failed / %d errors / %d run"
          % (passed, len(res.failures), len(res.errors), res.testsRun))
    sys.exit(0 if res.wasSuccessful() and res.testsRun > 0 else 1)


if __name__ == "__main__":
    main()
