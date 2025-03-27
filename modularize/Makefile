TAG ?=

INGEST_PROJECT_DIR := $(TAG)
INGEST_REPO_DIR := $(INGEST_PROJECT_DIR)/$(TAG)-ingest
INGEST_FILES := $(INGEST_PROJECT_DIR)/files-to-import.txt
INGEST_FILES_WITH_RENAMES := $(INGEST_PROJECT_DIR)/__files-to-import-with-renames.txt
INGEST_HISTORICAL_REPO := $(INGEST_PROJECT_DIR)/historical-commits

MONARCH_INGEST_COOKIECUTTER ?= ../../cookiecutter-monarch-ingest
MONARCH_INGEST_REPO ?= ../../monarch-ingest
MONARCH_INGEST_GIT ?= ../../monarch-ingest/.git

all:
	@echo 'run `make import_ingest` to import $(TAG)'

$(INGEST_PROJECT_DIR):
	mkdir -p $@

$(INGEST_REPO_DIR): | $(INGEST_PROJECT_DIR)
	cruft create $(MONARCH_INGEST_COOKIECUTTER) --output-dir $(INGEST_PROJECT_DIR)
	cd $@ && git init && git add -A && git commit -m "Initialize ingest from template"

$(INGEST_FILES): | $(INGEST_PROJECT_DIR)
	uv run find_ingest_files.py $(MONARCH_INGEST_REPO) $(TAG) > $@

$(INGEST_FILES_WITH_RENAMES): $(INGEST_FILES)
	cat $< | xargs -I {} git --git-dir=$(MONARCH_INGEST_GIT) log --pretty=format: --name-only --follow -- '{}' | awk NF | sort | uniq > $@

$(INGEST_HISTORICAL_REPO): $(INGEST_FILES_WITH_RENAMES)
	git clone https://github.com/monarch-initiative/monarch-ingest $@
	cd $@ && git filter-repo --paths-from-file ../../$<


.PHONY: create-history
create-history: $(INGEST_HISTORICAL_REPO)
	@echo 'Found the following files for $(TAG):'
	@echo
	@cat $(INGEST_FILES)
	@echo
	@echo 'Review these in `$(INGEST_FILES)`, add any more files needed, then run `make import_ingest` to continue'

.PHONY: setup-template
setup-template: $(INGEST_REPO_DIR)

.PHONY: import-commits
import-commits: $(INGEST_REPO_DIR) $(INGEST_HISTORICAL_REPO)
	cd $< && git remote add temporary-history ../../$(INGEST_HISTORICAL_REPO)
	cd $< && git fetch temporary-history
	cd $< && git rebase temporary-history/main
	cd $< && git remote remove temporary-history


.PHONY: clean
clean:
	rm -rf $(INGEST_HISTORICAL_REPO)

.PHONY: check-git-filter-repo
check-filter-repo:
	@which git-filter-repo || (echo "\nInstall https://github.com/newren/git-filter-repo before continuing.\n"; exit 1)
