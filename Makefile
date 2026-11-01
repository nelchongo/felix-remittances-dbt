# Optional thin wrapper: every target just calls run.py (the single entry point).
PY ?= python

.PHONY: setup all load replay build snapshot reset-data compile-metrics answers dashboard test lint edge-cases

setup:           ; $(PY) run.py setup
all:             ; $(PY) run.py all
load:            ; $(PY) run.py load
replay:          ; $(PY) run.py replay
build:           ; $(PY) run.py build
snapshot:        ; $(PY) run.py snapshot
reset-data:      ; $(PY) run.py reset-data
compile-metrics: ; $(PY) run.py compile-metrics
answers:         ; $(PY) run.py answers
dashboard:       ; $(PY) run.py dashboard
test:            ; $(PY) run.py test
lint:            ; $(PY) run.py lint
edge-cases:      ; $(PY) scripts/check_edge_cases.py && $(PY) run.py reset-data
