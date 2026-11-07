# ─────────────────────────────────────────────────────
# MOSAIC DRISHTI — Makefile
# Run `make help` to see all available commands
# ─────────────────────────────────────────────────────

.PHONY: help install shell test test-integration lint clean logs run

# ── Help ─────────────────────────────────────────────
help:
	@echo ""
	@echo "Mosaic Drishti — Available Commands"
	@echo "─────────────────────────────────────"
	@echo "make install   → Install all dependencies"
	@echo "make shell     → Activate Poetry shell"
	@echo "make test      → Run unit tests (fast, no network, no database)"
	@echo "make test-integration → Run integration tests (local Postgres test DB)"
	@echo "make lint      → Check code quality"
	@echo "make clean     → Remove cache files"
	@echo "make logs      → Tail live log file"
	@echo "make run       → Start Streamlit dashboard"
	@echo ""

# ── Dependencies ─────────────────────────────────────
install:
	poetry install

# ── Development Shell ────────────────────────────────
shell:
	poetry shell

# ── Testing ──────────────────────────────────────────
test:
	poetry run pytest --cov=data/ingestion --cov-report=term-missing

# Uses mosaic_drishti_test (rebuilt from migrations); sockets allowed to localhost only
test-integration:
	poetry run pytest -m integration --allow-hosts=127.0.0.1,localhost,::1 \
		--cov=data/ingestion --cov-report=term-missing

# ── Code Quality ─────────────────────────────────────
lint:
	poetry run ruff check .

# ── Cleanup ──────────────────────────────────────────
clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete

# ── Logs ─────────────────────────────────────────────
logs:
	tail -f logs/mosaic_drishti.log

# ── Application ──────────────────────────────────────
run:
	poetry run streamlit run frontend/streamlit_app.py