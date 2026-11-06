PYTHON ?= .venv/bin/python

.PHONY: help install install-dev run test clean

help:
	@echo "make install      Install application dependencies"
	@echo "make install-dev  Install test and collection dependencies"
	@echo "make run          Run the local web application"
	@echo "make test         Run the offline test suite"
	@echo "make clean        Remove generated caches (keeps models, data and results)"

install:
	$(PYTHON) -m pip install -r requirements.txt

install-dev:
	$(PYTHON) -m pip install -r requirements/dev.txt

run:
	$(PYTHON) run.py

test:
	$(PYTHON) -B -m pytest -p no:cacheprovider -q

clean:
	$(PYTHON) -B scripts/maintenance/clean.py --apply
