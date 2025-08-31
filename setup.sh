#!/bin/bash

echo "Creating uv virtual environment..."
uv venv

echo "Activating virtual environment..."
source .venv/bin/activate

echo "Installing dependencies from requirements.txt..."
uv pip install -r requirements.txt

echo "Setup complete."
