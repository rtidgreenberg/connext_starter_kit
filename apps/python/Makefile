# Makefile for Connext DDS Python Application
# Provides easy commands for codegen, installation, and running

.PHONY: help codegen install install-dev run clean test lint format

help:
	@echo "Available commands:"
	@echo "  install-rti-api - Install RTI Connext Python API (requires NDDSHOME)"
	@echo "  codegen     - Run CMake codegen to generate Python DDS bindings"
	@echo "  install     - Install the package in development mode (includes RTI API)"
	@echo "  install-dev - Install with development dependencies (includes RTI API)"
	@echo "  run         - Show how to run the example_io_app application"
	@echo "  clean       - Clean build artifacts and generated code"
	@echo "  test        - Run tests (if any)"
	@echo "  lint        - Run code linting"
	@echo "  format      - Format code with black"
	@echo "  check-env   - Check RTI environment variables"

# Generate Python DDS bindings from IDL files
codegen:
	@echo "Generating Python DDS bindings..."
	cd ../../dds/python && mkdir -p build && cd build && cmake .. && make -j4
	@echo "Code generation completed."

# Install RTI Python API from NDDSHOME
install-rti-api: check-env
	@echo "Installing RTI Connext Python API..."
	pip install rti.connext==7.3.0
	@echo "RTI Python API installation completed."

# Install package in development mode
install: install-rti-api codegen
	@echo "Installing package in development mode..."
	pip install -e .

# Install with development dependencies
install-dev: install-rti-api codegen
	@echo "Installing package with development dependencies..."
	pip install -e .[dev]

# Run the example_io_app application
run:
	@echo "Running example_io_app application..."
	cd example_io_app && python example_io_app.py --help
	@echo ""
	@echo "To run the application:"
	@echo "  cd example_io_app && python example_io_app.py --domain_id 1 --verbosity 2"

# Clean build artifacts and generated code
clean:
	@echo "Cleaning build artifacts..."
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf __pycache__/
	rm -rf .pytest_cache/
	find . -name "*.pyc" -delete
	find . -name "*.pyo" -delete
	@echo "Cleaning DDS Python codegen..."
	cd ../../dds/python && rm -rf build/ && rm -rf codegen/*.py codegen/__pycache__/
	@echo "Clean completed."

# Run tests
test:
	@echo "Running tests..."
	pytest

# Run code linting
lint:
	@echo "Running flake8 linting..."
	flake8 example_io_app/example_io_app.py build_hooks.py
	@echo "Running mypy type checking..."
	mypy example_io_app/example_io_app.py build_hooks.py

# Format code with black
format:
	@echo "Formatting code with black..."
	black example_io_app/example_io_app.py build_hooks.py

# Check RTI environment
check-env:
	@echo "Checking RTI Connext DDS environment..."
	@if [ -z "$$NDDSHOME" ]; then \
		echo "ERROR: NDDSHOME environment variable not set"; \
		echo "Please set NDDSHOME to your RTI Connext DDS installation directory"; \
		exit 1; \
	else \
		echo "NDDSHOME: $$NDDSHOME"; \
	fi
	@echo "RTI environment check passed."

# Show package information
info:
	@echo "Package Information:"
	@echo "  Name: connext-dds-python-apps"
	@echo "  Version: 1.0.0"
	@echo "  Python: $$(python3 --version)"
	@echo "  RTI Connext: Requires 7.3.0+"
	@echo ""
	@echo "Generated bindings location: ../../dds/python/codegen/"
	@echo "Available applications:"
	@echo "  - example_io_app/example_io_app.py"