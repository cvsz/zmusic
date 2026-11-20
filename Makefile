SHELL := /bin/sh

.PHONY: help validate-template setup install format lint test build security ci

help:
	@printf '%s\n' 'Targets:' \
		'  make validate-template - Run repository structure and link validation' \
		'  make setup             - Initialize a new repo from ztemplate (dry-run, env vars)' \
		'  make install - Initialize a new repo from ztemplate (interactive)' \
		'  make test              - Run python unit tests' \
		'  make lint              - Run python syntax and structure checks' \
		'  make build             - Run compilation check on scripts' \
		'  make security          - Run security and validation checks' \
		'  make ci                - Run full CI validation suite'

install:
	@echo 'Ztemplate interactive installer'
	@echo ''
	@read -p 'Project name (letters, digits, hyphen, underscore): ' PROJECT_NAME && \
	read -p 'Owner (user or org name): ' OWNER && \
	read -p 'Codeowner (username or org/team): ' CODEOWNER && \
	read -p 'Description (max 500 chars, one line): ' DESCRIPTION && \
	echo '' && \
	echo "Running bootstrap with: name=$${PROJECT_NAME} owner=$${OWNER} codeowner=$${CODEOWNER} description=$${DESCRIPTION}" && \
	python3 scripts/bootstrap.py --name "$$PROJECT_NAME" --owner "$$OWNER" --codeowner "$$CODEOWNER" --description "$$DESCRIPTION" --apply || true

setup:
	@python3 scripts/bootstrap.py --name "$(PROJECT_NAME)" --owner "$(OWNER)" --codeowner "$(CODEOWNER)" --description "$(DESCRIPTION)" || true

validate-template:
	python3 scripts/validate_repo.py
	python3 -m unittest discover -s tests -v

format:
	python3 -m py_compile scripts/*.py tests/*.py

lint:
	python3 -m py_compile scripts/*.py tests/*.py
	python3 scripts/validate_repo.py

test:
	python3 -m unittest discover -s tests -v

build:
	python3 -m py_compile scripts/*.py

security:
	python3 scripts/validate_repo.py

ci: validate-template lint test build security
