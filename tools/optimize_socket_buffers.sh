# !/bin/bash
# This script optimizes the socket buffer sizes for better network performance
# Simply run with: sudo ./tools/optimize_socket_buffers.sh

sudo sysctl -w net.core.rmem_default="65536"
sudo sysctl -w net.core.wmem_default="65536"
sudo sysctl -w net.core.rmem_max="10485760"
sudo sysctl -w net.core.wmem_max="10485760"