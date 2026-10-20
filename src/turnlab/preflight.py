"""Readiness checks without printing secrets or contacting inference providers."""

import os
import socket
from urllib.parse import urlparse

from turnlab.settings import VoiceSettings


def check_voice_environment() -> dict:
    from dotenv import load_dotenv

    load_dotenv()
    settings = VoiceSettings.from_env(os.environ)
    try:
        settings.validate_credentials()
        credentials_ready = True
        configuration_issue = None
    except ValueError as exc:
        credentials_ready = False
        configuration_issue = str(exc)
    parsed = urlparse(settings.livekit_url)
    try:
        with socket.create_connection((parsed.hostname, parsed.port or 7880), timeout=2):
            server_reachable = True
    except OSError:
        server_reachable = False
    return {"local_server_reachable": server_reachable, "provider_credentials_present": credentials_ready,
            "configuration_issue": configuration_issue, "provider_authentication_tested": False,
            "ready_for_voice_test": server_reachable and credentials_ready}
