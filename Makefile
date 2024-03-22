install:
	pip install --upgrade pip
	pip install -r requirements.txt

build:
	python -m feederss

start:
	cd public/ && python -m http.server 3030

watch:
	find ./feederss/ | entr -c make build