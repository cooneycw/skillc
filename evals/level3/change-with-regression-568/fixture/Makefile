.PHONY: test verify
test:
	python3 -c 'import unittest,sys; suite=unittest.defaultTestLoader.discover("tests"); result=unittest.TextTestRunner(verbosity=2).run(suite); sys.exit(0 if result.wasSuccessful() and result.testsRun > len(result.skipped) else 1)'
verify: test
