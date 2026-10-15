PYTHON ?= python3

.DEFAULT_GOAL := help

.PHONY: help all clean ch01-replay ch02-baseline ch03-readiness calibration calibration-verify ch05-change-gate ch05-change-gate-verify ch06-guard ch06-k8s-mechanism ch06-figures ch06 ch07-governed-agent ch08-incident-replay ch09-retrieval-eval ch10-human-boundary ch11-readiness test

help: ## List targets
	@grep -E '^[a-zA-Z0-9_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-26s %s\n", $$1, $$2}'

all: ch01-replay ch02-baseline ch03-readiness calibration ch05-change-gate ch06 ch07-governed-agent ch08-incident-replay ch09-retrieval-eval ch10-human-boundary ch11-readiness ## Regenerate every artifact under generated/

ch01-replay: ## Chapter 1: assemble the cited brief from constructed evidence
	$(PYTHON) scripts/ch01_context_replay.py

ch02-baseline: ## Chapter 2: constructed incident ledger, summary, and duration-band figure
	$(PYTHON) scripts/ch02_constructed_ledger.py

ch03-readiness: ## Chapter 3: validate the fourteen-layer worksheet and write gap reports
	$(PYTHON) scripts/ch03_readiness_report.py

calibration: ## Chapter 4: CAL-01 bins, finite-sample intervals, reliability figure
	$(PYTHON) scripts/ch04_calibration_lab.py --write

calibration-verify: ## Chapter 4: fail if the pinned input or any committed output drifts
	$(PYTHON) scripts/ch04_calibration_lab.py --verify

ch05-change-gate: ## Chapter 5: evaluate the constructed change cases and publish Figures 5.1-5.2
	$(PYTHON) scripts/ch05_change_gate.py --write

ch05-change-gate-verify: ## Chapter 5: fail if any committed Chapter 5 artifact drifts
	$(PYTHON) scripts/ch05_change_gate.py --verify

ch06-guard: ## Chapter 6: constructed blast-radius guard and decision ledger
	$(PYTHON) scripts/ch06_guard.py

ch06-k8s-mechanism: ## Chapter 6: verify the pinned K8S-01 record and regenerate Table 6.4 / Figure 6.6
	$(PYTHON) scripts/ch06_k8s_mechanism.py

ch06-figures: ## Chapter 6: validate accessible SVG sources and publish Figures 6.1-6.5
	$(PYTHON) scripts/ch06_figures.py

ch06: ch06-guard ch06-k8s-mechanism ch06-figures ## Chapter 6: all three targets

ch07-governed-agent: ## Chapter 7: nineteen governed-agent boundary cases and Figures 7.1-7.3
	$(PYTHON) scripts/ch07_governed_agent.py

ch08-incident-replay: ## Chapter 8: constructed incident-lifecycle replay with Late Arrival briefs
	$(PYTHON) scripts/ch08_incident_replay.py

ch09-retrieval-eval: ## Chapter 9: constructed retrieval evaluation, then verify the committed outputs
	$(PYTHON) scripts/ch09_retrieval_eval.py --write
	$(PYTHON) scripts/ch09_retrieval_eval.py --verify

ch10-human-boundary: ## Chapter 10: classify the seven human-boundary cases
	$(PYTHON) scripts/ch10_human_boundary.py --verify

ch11-readiness: ## Chapter 11: Phase 0 gate ledger, recommendation, starter plan, Figures 11.1-11.2
	$(PYTHON) scripts/ch11_readiness.py
	$(PYTHON) scripts/ch11_figures.py

test: ch05-change-gate ch06-figures ch07-governed-agent ch11-readiness ## Run the unit and adversarial test suite (publishes figures first so the suite is self-contained)
	$(PYTHON) -m unittest discover -s tests -p 'test_*.py'

clean: ## Remove bytecode caches
	find . -name __pycache__ -type d -exec rm -rf {} +
