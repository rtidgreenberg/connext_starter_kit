#!/bin/bash
# Installation script for Parameter App dependencies
# Installs yaml-cpp library required for YAML parameter file parsing

set -e  # Exit on any error

echo "=== Parameter App Dependencies Setup ==="
echo

# Detect OS
detect_os() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS=$ID
        VERSION=$VERSION_ID
    elif [ "$(uname)" == "Darwin" ]; then
        OS="macos"
    else
        OS="unknown"
    fi
    echo "$OS"
}

OS=$(detect_os)
echo "Detected OS: $OS"
echo

# Check if yaml-cpp is already installed
check_yaml_cpp() {
    if pkg-config --exists yaml-cpp 2>/dev/null; then
        VERSION=$(pkg-config --modversion yaml-cpp 2>/dev/null || echo "unknown")
        echo "✓ yaml-cpp already installed (version: $VERSION)"
        return 0
    fi
    return 1
}

# Install yaml-cpp based on OS
install_yaml_cpp() {
    echo "Installing yaml-cpp..."
    echo
    
    case "$OS" in
        ubuntu|debian|pop)
            echo "Using apt package manager..."
            sudo apt-get update
            sudo apt-get install -y libyaml-cpp-dev pkg-config
            ;;
        fedora)
            echo "Using dnf package manager..."
            sudo dnf install -y yaml-cpp-devel pkgconfig
            ;;
        centos|rhel|rocky|almalinux)
            echo "Using yum/dnf package manager..."
            if command -v dnf &> /dev/null; then
                sudo dnf install -y yaml-cpp-devel pkgconfig
            else
                sudo yum install -y epel-release
                sudo yum install -y yaml-cpp-devel pkgconfig
            fi
            ;;
        arch|manjaro)
            echo "Using pacman package manager..."
            sudo pacman -S --noconfirm yaml-cpp pkgconf
            ;;
        macos)
            echo "Using Homebrew..."
            if ! command -v brew &> /dev/null; then
                echo "ERROR: Homebrew not found. Please install from https://brew.sh"
                exit 1
            fi
            brew install yaml-cpp pkg-config
            ;;
        *)
            echo "ERROR: Unsupported OS: $OS"
            echo
            echo "Please install yaml-cpp manually:"
            echo "  - Ubuntu/Debian: sudo apt-get install libyaml-cpp-dev"
            echo "  - Fedora:        sudo dnf install yaml-cpp-devel"
            echo "  - CentOS/RHEL:   sudo yum install yaml-cpp-devel"
            echo "  - Arch:          sudo pacman -S yaml-cpp"
            echo "  - macOS:         brew install yaml-cpp"
            echo
            exit 1
            ;;
    esac
    
    echo
    echo "✓ yaml-cpp installed successfully"
}

# Main
echo "Checking for yaml-cpp library..."
if check_yaml_cpp; then
    echo
    echo "All dependencies satisfied!"
else
    echo "yaml-cpp not found."
    echo
    
    # Ask for confirmation unless -y flag provided
    if [ "$1" != "-y" ] && [ "$1" != "--yes" ]; then
        read -p "Install yaml-cpp now? [Y/n] " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]] && [[ ! -z $REPLY ]]; then
            echo "Installation cancelled."
            exit 0
        fi
    fi
    
    install_yaml_cpp
    
    # Verify installation
    echo
    echo "Verifying installation..."
    if check_yaml_cpp; then
        echo "✓ Installation verified!"
    else
        echo "WARNING: Installation may have failed. Please check manually."
        exit 1
    fi
fi

echo
echo "=== Setup Complete ==="
echo
echo "You can now build the parameter_app:"
echo "  cd <repo_root>/build"
echo "  cmake .."
echo "  cmake --build ."
echo
