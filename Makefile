IMAGE ?= registry.gitlab.com/abelsonlive/feederss
TAG ?= latest

.PHONY: help install build publish loop start watch docker-build docker-run

help:
	@echo "feederss"
	@echo ""
	@echo "  make install       Install python dependencies"
	@echo "  make build         Render the site into public/"
	@echo "  make publish       Render the site and sync it to object storage"
	@echo "  make loop          Render + publish every REFRESH_INTERVAL_SECONDS"
	@echo "  make start         Serve public/ locally on :3030"
	@echo "  make watch         Rebuild on change (needs entr)"
	@echo ""
	@echo "  make docker-build  Build the container image ($(IMAGE):$(TAG))"
	@echo "  make docker-run    Run the container against your .env"

install:
	pip install --upgrade pip
	pip install -r requirements.txt

build:
	python -m feederss build

publish:
	python -m feederss publish

loop:
	python -m feederss loop

start:
	cd public/ && python -m http.server 3030

watch:
	find ./feederss/ | entr -c make build

docker-build:
	docker build -t $(IMAGE):$(TAG) .

docker-run:
	docker run --rm --env-file .env $(IMAGE):$(TAG)
