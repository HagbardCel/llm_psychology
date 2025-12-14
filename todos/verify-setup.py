#!/usr/bin/env python3
"""
Verify that the web interface setup is correctly configured.
"""

import os
import sys
import yaml
import json
from pathlib import Path


def check_file_exists(filepath, description):
    """Check if a file exists and is readable."""
    if os.path.isfile(filepath):
        print(f"✅ {description}: {filepath}")
        return True
    else:
        print(f"❌ {description}: {filepath} - NOT FOUND")
        return False


def check_docker_compose_file(filepath):
    """Validate docker-compose file syntax."""
    try:
        with open(filepath, "r") as f:
            data = yaml.safe_load(f)

        # Check required sections
        if "services" not in data:
            print(f"❌ {filepath}: Missing 'services' section")
            return False

        services = data["services"]
        required_services = (
            ["backend", "websocket", "frontend"]
            if "web.yml" in filepath
            else ["backend", "websocket", "frontend-dev"]
        )

        for service in required_services:
            if service not in services:
                print(f"❌ {filepath}: Missing service '{service}'")
                return False

        print(f"✅ {filepath}: Valid docker-compose file")
        return True

    except Exception as e:
        print(f"❌ {filepath}: Invalid YAML - {e}")
        return False


def check_package_json():
    """Check frontend package.json."""
    package_json_path = "/app/frontend/package.json"
    try:
        with open(package_json_path, "r") as f:
            data = json.load(f)

        # Check required scripts
        scripts = data.get("scripts", {})
        required_scripts = ["dev", "build"]

        for script in required_scripts:
            if script not in scripts:
                print(f"❌ package.json: Missing script '{script}'")
                return False

        print(f"✅ Frontend package.json: Valid configuration")
        return True

    except Exception as e:
        print(f"❌ Frontend package.json: {e}")
        return False


def main():
    """Main verification function."""
    print("🔍 Verifying Web Interface Setup")
    print("================================")

    all_good = True

    # Check core files
    files_to_check = [
        ("/app/frontend/Dockerfile", "Frontend Production Dockerfile"),
        ("/app/frontend/Dockerfile.dev", "Frontend Development Dockerfile"),
        ("/app/frontend/nginx.conf", "Nginx Configuration"),
        ("/app/frontend/vite.config.ts", "Vite Configuration"),
        ("/app/todos/docker-compose.web.yml", "Production Docker Compose"),
        ("/app/todos/docker-compose.web-dev.yml", "Development Docker Compose"),
        ("/app/todos/start-web-production.sh", "Production Start Script"),
        ("/app/todos/start-web-development.sh", "Development Start Script"),
        ("/app/todos/stop-web.sh", "Stop Script"),
        ("/app/todos/Makefile.web", "Web Makefile"),
        ("/app/.env", "Environment File"),
    ]

    for filepath, description in files_to_check:
        if not check_file_exists(filepath, description):
            all_good = False

    print("\n" + "=" * 50)

    # Check Docker Compose files
    compose_files = [
        "/app/todos/docker-compose.web.yml",
        "/app/todos/docker-compose.web-dev.yml",
    ]

    for compose_file in compose_files:
        if os.path.isfile(compose_file):
            if not check_docker_compose_file(compose_file):
                all_good = False

    # Check package.json
    if not check_package_json():
        all_good = False

    print("\n" + "=" * 50)

    if all_good:
        print("🎉 Setup verification PASSED!")
        print("\n📋 Next steps:")
        print("1. Ensure Docker is installed and running")
        print("2. Run: ./todos/start-web-development.sh")
        print("3. Visit: http://localhost:5173")
        return 0
    else:
        print("❌ Setup verification FAILED!")
        print("\n🔧 Please fix the issues above before proceeding.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
