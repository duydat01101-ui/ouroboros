# Ouroboros — common development commands
# Usage: make test, make lint, make health

.PHONY: test test-v test-e2e health clean

test:
	python3 -m pytest ../tests/ -q --tb=short --ignore=../tests/e2e

test-v:
	python3 -m pytest ../tests/ -v --tb=long --ignore=../tests/e2e

health:
	python3 -c "import sys; sys.path.insert(0, '..'); from ouroboros.review import compute_complexity_metrics; \
		import pathlib, json; \
		m = compute_complexity_metrics(pathlib.Path('..')); \
		print(json.dumps(m, indent=2, default=str))"

test-e2e:
	docker build -t ouroboros-e2e -f ../tests/e2e/Dockerfile ..
	docker run --rm --env-file ../.env \
		-e OUROBOROS_MAX_ROUNDS=30 \
		-e OUROBOROS_MODEL=anthropic/claude-sonnet-4 \
		-e GITHUB_TOKEN=dummy \
		-e GITHUB_USER=dummy \
		-e GITHUB_REPO=dummy \
		-e TELEGRAM_BOT_TOKEN=dummy \
		ouroboros-e2e

clean:
	find .. -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find .. -type f -name "*.pyc" -delete 2>/dev/null || true
	find .. -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
