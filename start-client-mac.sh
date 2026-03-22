#!/bin/bash
# Делегирует в start-client-mac.command (там поиск порта, WHISPER_SERVER_IP, server_url.txt).
cd "$(dirname "$0")"
exec bash ./start-client-mac.command "$@"
