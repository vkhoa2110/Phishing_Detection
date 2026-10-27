PYTHON ?= .venv/bin/python

.PHONY: help install install-dev run test report

help:
	@echo "make install      Install application dependencies"
	@echo "make install-dev  Install test and collection dependencies"
	@echo "make run          Run the local web application"
	@echo "make test         Run the offline test suite"
	@echo "make report       Build a report copy under artifacts/report-builds/"

install:
	$(PYTHON) -m pip install -r requirements.txt

install-dev:
	$(PYTHON) -m pip install -r requirements/dev.txt

run:
	$(PYTHON) run.py

test:
	$(PYTHON) -m pytest -q

report:
	$(PYTHON) scripts/reporting/build_report.py
