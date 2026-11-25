PYTHON ?= .venv/bin/python

.PHONY: help install install-dev run run-core run-candidate run-focused run-verifier-shadow demo extension shortcut test clean

help:
	@echo "make demo         Start/open the account-backed app with installation checks"
	@echo "make extension    Package the browser extension (local ZIP)"
	@echo "make shortcut     Install the Linux application shortcut for this user"
	@echo "make install      Install application dependencies"
	@echo "make install-dev  Install test and collection dependencies"
	@echo "make run          Run the local web application"
	@echo "make run-core     Run the account-free research runtime"
	@echo "make run-candidate Run the experimental v6.1 application"
	@echo "make run-focused Run the experimental core-verdict application"
	@echo "make run-verifier-shadow Run focused with an advisory verifier (extra AI call, verdict unchanged)"
	@echo "make test         Run the offline test suite"
	@echo "make clean        Remove generated caches (keeps models, data and results)"

install:
	$(PYTHON) -m pip install -r requirements.txt

install-dev:
	$(PYTHON) -m pip install -r requirements/dev.txt

run:
	$(PYTHON) run.py

demo:
	$(PYTHON) launch.py

extension:
	$(PYTHON) scripts/maintenance/package_extension.py --force

shortcut:
	$(PYTHON) scripts/maintenance/install_shortcut.py

run-core:
	PHISHLENS_ACCOUNTS=0 $(PYTHON) run.py

run-candidate:
	PHISHLENS_PROFILE=candidate $(PYTHON) run.py

run-focused:
	PHISHLENS_PROFILE=focused $(PYTHON) run.py

run-verifier-shadow:
	PHISHLENS_PROFILE=verifier-shadow $(PYTHON) run.py

test:
	$(PYTHON) -B -m pytest -p no:cacheprovider -q

clean:
	$(PYTHON) -B scripts/maintenance/clean.py --apply
