PYTHON := $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

.PHONY: setup test unit rtl exhaustive benchmark test_matadd test_matmul inputs all

setup:
	python3 -m venv .venv
	.venv/bin/python -m pip install -r requirements.txt

unit:
	$(PYTHON) -m pytest -q tests

rtl:
	$(PYTHON) scripts/run_sim.py test

test: unit rtl

exhaustive:
	$(PYTHON) scripts/run_sim.py exhaustive

benchmark:
	$(PYTHON) scripts/run_sim.py benchmark
	$(PYTHON) scripts/report_results.py

test_matadd:
	$(PYTHON) scripts/run_sim.py matadd

test_matmul:
	$(PYTHON) scripts/run_sim.py matmul

inputs:
	$(PYTHON) scripts/generate_inputs.py

all: test_matadd test_matmul test benchmark
