# ─────────────────────────────────────────────────────
# MOSAIC DRISHTI — Makefile
# Run `make help` to see all available commands
# ─────────────────────────────────────────────────────

.PHONY: help install shell test lint clean logs run

# ── Help ─────────────────────────────────────────────
help:
	@echo ""
	@echo "Mosaic Drishti — Available Commands"
	@echo "─────────────────────────────────────"
	@echo "make install   → Install all dependencies"
	@echo "make shell     → Activate Poetry shell"
	@echo "make test      → Run all tests"
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
	poetry run pytest tests/ -v

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