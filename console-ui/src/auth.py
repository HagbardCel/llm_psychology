"""
Authentication module for console client.

Handles user registration and login flows.
"""

import getpass
import json
import logging
from typing import Optional, Tuple

import httpx
import trio

logger = logging.getLogger(__name__)


class AuthenticationError(Exception):
    """Exception raised when authentication fails."""

    pass


async def authenticate(api_url: str) -> Tuple[str, str, str]:
    """
    Authenticate user and return access token and user info.

    Returns:
        Tuple of (access_token, user_id, username)

    Raises:
        AuthenticationError: If authentication fails
    """
    print("\n" + "=" * 60)
    print("🔐 AUTHENTICATION REQUIRED")
    print("=" * 60)
    print()
    print("Please login or create a new account")
    print("Type 'register' to create a new account, or enter your username to login")
    print()

    async with httpx.AsyncClient() as client:
        while True:
            # Get username
            username = await trio.to_thread.run_sync(
                input, "Username (or 'register'): ", cancellable=True
            )
            username = username.strip()

            if not username:
                print("❌ Username cannot be empty")
                continue

            # Check if user wants to register
            if username.lower() == "register":
                token, user_id, username = await _register_user(client, api_url)
                if token:
                    return token, user_id, username
                # If registration failed, loop back
                continue

            # Attempt login
            token, user_id = await _login_user(client, api_url, username)
            if token:
                return token, user_id, username

            # Login failed, ask if they want to try again or register
            print()
            retry = await trio.to_thread.run_sync(
                input,
                "Press Enter to try again, or type 'register' to create an account: ",
                cancellable=True,
            )

            if retry.strip().lower() == "register":
                token, user_id, username = await _register_user(client, api_url)
                if token:
                    return token, user_id, username


async def _register_user(
    client: httpx.AsyncClient, api_url: str
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Register a new user.

    Returns:
        Tuple of (access_token, user_id, username) or (None, None, None) if failed
    """
    print("\n" + "-" * 60)
    print("📝 NEW USER REGISTRATION")
    print("-" * 60)

    try:
        # Get username
        while True:
            username = await trio.to_thread.run_sync(
                input, "Choose a username (3-50 characters): ", cancellable=True
            )
            username = username.strip()

            if len(username) < 3:
                print("❌ Username must be at least 3 characters")
                continue
            if len(username) > 50:
                print("❌ Username must be at most 50 characters")
                continue
            break

        # Get full name
        name = await trio.to_thread.run_sync(
            input, "Your full name: ", cancellable=True
        )
        name = name.strip()

        if not name:
            print("❌ Name cannot be empty")
            return None, None, None

        # Get password
        while True:
            password = await trio.to_thread.run_sync(
                getpass.getpass,
                "Choose a password (min 8 characters): ",
                cancellable=True,
            )

            if len(password) < 8:
                print("❌ Password must be at least 8 characters")
                continue

            password_confirm = await trio.to_thread.run_sync(
                getpass.getpass, "Confirm password: ", cancellable=True
            )

            if password != password_confirm:
                print("❌ Passwords do not match, please try again")
                continue

            break

        # Send registration request
        print("\n⏳ Creating your account...")

        response = await client.post(
            f"{api_url}/api/auth/register",
            json={"username": username, "password": password, "name": name},
            timeout=10.0,
        )

        if response.status_code == 201:
            data = response.json()
            access_token = data.get("access_token")

            # Decode JWT to get user_id (simple base64 decode without verification)
            import base64

            payload_part = access_token.split(".")[1]
            # Add padding if needed
            padding = len(payload_part) % 4
            if padding:
                payload_part += "=" * (4 - padding)

            payload = json.loads(base64.urlsafe_b64decode(payload_part))
            user_id = payload.get("user_id")

            print(f"✅ Account created successfully!")
            print(f"   Welcome, {name}!")
            print()

            return access_token, user_id, username

        elif response.status_code == 400:
            error_data = response.json()
            error_msg = error_data.get("error", "Registration failed")
            print(f"❌ Registration failed: {error_msg}")

            if "already exists" in error_msg.lower():
                print(
                    "   That username is already taken. Please choose a different one."
                )

            return None, None, None

        else:
            print(f"❌ Registration failed with status {response.status_code}")
            return None, None, None

    except httpx.TimeoutException:
        print("❌ Request timed out. Please check your connection and try again.")
        return None, None, None
    except Exception as e:
        logger.error(f"Registration error: {e}", exc_info=True)
        print(f"❌ An error occurred during registration: {e}")
        return None, None, None


async def _login_user(
    client: httpx.AsyncClient, api_url: str, username: str
) -> Tuple[Optional[str], Optional[str]]:
    """
    Login an existing user.

    Returns:
        Tuple of (access_token, user_id) or (None, None) if failed
    """
    try:
        # Get password
        password = await trio.to_thread.run_sync(
            getpass.getpass, "Password: ", cancellable=True
        )

        # Send login request
        print("\n⏳ Authenticating...")

        response = await client.post(
            f"{api_url}/api/auth/login",
            json={"username": username, "password": password},
            timeout=10.0,
        )

        if response.status_code == 200:
            data = response.json()
            access_token = data.get("access_token")

            # Decode JWT to get user_id
            import base64

            payload_part = access_token.split(".")[1]
            # Add padding if needed
            padding = len(payload_part) % 4
            if padding:
                payload_part += "=" * (4 - padding)

            payload = json.loads(base64.urlsafe_b64decode(payload_part))
            user_id = payload.get("user_id")

            print(f"✅ Login successful! Welcome back, {username}")
            print()

            return access_token, user_id

        elif response.status_code == 401:
            print("❌ Invalid username or password")
            return None, None

        else:
            print(f"❌ Login failed with status {response.status_code}")
            return None, None

    except httpx.TimeoutException:
        print("❌ Request timed out. Please check your connection and try again.")
        return None, None
    except Exception as e:
        logger.error(f"Login error: {e}", exc_info=True)
        print(f"❌ An error occurred during login: {e}")
        return None, None
