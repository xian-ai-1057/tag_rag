#!/usr/bin/env bash
set -euo pipefail
pytest tests/unit -q
pytest tests/integration -q -m "not requires_ollama"
# 若 Ollama 啟動再跑：
# pytest tests/integration -q -m requires_ollama
