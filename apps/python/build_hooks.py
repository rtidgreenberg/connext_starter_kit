"""
Build hooks for running CMake codegen before package build.

This module provides custom build commands that automatically run
the CMake-based code generation from dds/python before building
the Python package.
"""

import os
import subprocess
import sys
from pathlib import Path
from setuptools.command.build_py import build_py


class BuildPyWithCodegen(build_py):
    """Custom build_py command that runs CMake codegen first."""

    def run(self):
        """Run CMake codegen, then proceed with normal build_py."""
        self.check_rti_python_api()
        self.run_cmake_codegen()
        super().run()

    def check_rti_python_api(self):
        """Check if RTI Python API is available."""
        try:
            import rti.connextdds

            print("RTI Connext Python API found")
        except ImportError:
            print("WARNING: RTI Connext Python API not found!")
            print("Please install it using:")
            print("  pip install rti.connext==7.3.0")
            print("Or run: make install-rti-api")
            # Don't fail the build, just warn
            pass

    def run_cmake_codegen(self):
        """Run the CMake codegen process from dds/python."""
        print("Running CMake codegen for DDS Python bindings...")

        # Get the path to the dds/python directory
        current_dir = Path(__file__).parent
        dds_python_dir = current_dir / ".." / ".." / "dds" / "python"
        dds_python_dir = dds_python_dir.resolve()

        if not dds_python_dir.exists():
            raise FileNotFoundError(f"DDS Python directory not found: {dds_python_dir}")

        # Create build directory
        build_dir = dds_python_dir / "build"
        build_dir.mkdir(exist_ok=True)

        print(f"DDS Python directory: {dds_python_dir}")
        print(f"Build directory: {build_dir}")

        try:
            # Run CMake configuration
            print("Running CMake configuration...")
            cmake_config_cmd = ["cmake", ".."]
            result = subprocess.run(
                cmake_config_cmd,
                cwd=build_dir,
                check=True,
                capture_output=True,
                text=True,
            )
            print("CMake configuration completed successfully")

            # Run CMake build
            print("Running CMake build...")
            cmake_build_cmd = ["make", "-j4"]
            result = subprocess.run(
                cmake_build_cmd,
                cwd=build_dir,
                check=True,
                capture_output=True,
                text=True,
            )
            print("CMake build completed successfully")

            # Verify codegen output exists
            codegen_dir = dds_python_dir / "codegen"
            expected_files = ["PointCloud.py", "Pose.py", "Topics.py", "__init__.py"]

            for file_name in expected_files:
                file_path = codegen_dir / file_name
                if not file_path.exists():
                    raise FileNotFoundError(
                        f"Expected codegen file not found: {file_path}"
                    )

            print(f"All expected codegen files found in: {codegen_dir}")

        except subprocess.CalledProcessError as e:
            print(f"CMake command failed with return code {e.returncode}")
            print("STDOUT:", e.stdout)
            print("STDERR:", e.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"Error running CMake codegen: {e}")
            sys.exit(1)
