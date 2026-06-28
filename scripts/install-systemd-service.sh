#!/bin/bash
set -e

# Installation script for Developer Agents Workflow API systemd service

echo "=== Developer Agents API Systemd Service Installer ==="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "ERROR: This script must be run as root (use sudo)"
    exit 1
fi

# Determine the project directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "Project directory: $PROJECT_DIR"

# Check if .env file exists
if [ ! -f "$PROJECT_DIR/.env" ]; then
    echo "ERROR: .env file not found at $PROJECT_DIR/.env"
    echo "Please create a .env file with required environment variables"
    exit 1
fi

# Check if venv exists
if [ ! -d "$PROJECT_DIR/venv" ]; then
    echo "ERROR: Virtual environment not found at $PROJECT_DIR/venv"
    echo "Please create a virtual environment first: python3 -m venv venv"
    exit 1
fi

# Update service file with actual project path
SERVICE_FILE="$PROJECT_DIR/systemd/developer-agents-api.service"
TEMP_SERVICE_FILE="/tmp/developer-agents-api.service"

if [ ! -f "$SERVICE_FILE" ]; then
    echo "ERROR: Service file not found at $SERVICE_FILE"
    exit 1
fi

# Replace placeholder path with actual project directory
sed "s|/root/projects/ai-developers-agents-workflow|$PROJECT_DIR|g" "$SERVICE_FILE" > "$TEMP_SERVICE_FILE"

# Copy service file to systemd directory
echo "Installing service file..."
cp "$TEMP_SERVICE_FILE" /etc/systemd/system/developer-agents-api.service
rm "$TEMP_SERVICE_FILE"

# Reload systemd
echo "Reloading systemd daemon..."
systemctl daemon-reload

# Enable service
echo "Enabling service to start on boot..."
systemctl enable developer-agents-api.service

echo ""
echo "=== Installation Complete ==="
echo ""
echo "Service management commands:"
echo "  Start:   systemctl start developer-agents-api"
echo "  Stop:    systemctl stop developer-agents-api"
echo "  Restart: systemctl restart developer-agents-api"
echo "  Status:  systemctl status developer-agents-api"
echo "  Logs:    journalctl -u developer-agents-api -f"
echo ""
echo "To start the service now, run:"
echo "  systemctl start developer-agents-api"
