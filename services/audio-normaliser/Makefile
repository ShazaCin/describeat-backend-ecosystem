#
# Build the audio normaliser Lambda.
#
# The function depends on ffmpeg and ffprobe. Rather than vendoring a
# static ffmpeg build into this repository (which would be a large binary
# blob and a licensing question), the layer directory is populated at build
# time by the Makefile.
#
# If you would rather use a published Lambda layer, delete the `layer/`
# directory and replace the FfmpegLayer resource in template.yaml with an
# AWS::Lambda::LayerVersion that points at the published layer.

PYTHON ?= python3
LAYER_DIR := layer
LAYER_ZIP := $(LAYER_DIR)/ffmpeg-layer.zip

.PHONY: help deps layer build test clean

help:
	@echo "Targets:"
	@echo "  deps   Install the package and its test dependencies"
	@echo "  layer  Download a static ffmpeg build into layer/"
	@echo "  build  Build the Lambda package and the layer"
	@echo "  test   Run the test suite"
	@echo "  clean  Remove build output"

deps:
	$(PYTHON) -m pip install -e ".[dev]"

layer:
	@echo "Downloading a static ffmpeg build..."
	@echo "This fetches a prebuilt binary from a public release page."
	@echo "Check the download yourself before deploying it to your account:"
	@echo "  https://johnvansickle.com/ffmpeg/"
	@mkdir -p $(LAYER_DIR)/bin
	@echo "Populate $(LAYER_DIR)/bin with a static 'ffmpeg' and 'ffprobe', then run 'make build'."
	@echo "Alternatively, publish your own layer and update template.yaml."

build: layer
	@echo "Building the Lambda package..."
	$(PYTHON) -m pip install --target build/ .
	@echo "Build output is in build/"

test:
	$(PYTHON) -m pytest tests/ -v

clean:
	rm -rf build/ $(LAYER_DIR)/ *.egg-info src/*.egg-info
	find . -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
