"""Explicit local voice settings; credentials are never included in repr."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse


@dataclass(frozen=True)
class VoiceSettings:
    livekit_url: str = "ws://127.0.0.1:7880"
    livekit_api_key: str = field(default="devkey", repr=False)
    livekit_api_secret: str = field(default="secret", repr=False)
    groq_api_key: str = field(default="", repr=False)
    deepgram_api_key: str = field(default="", repr=False)
    llm_model: str = "openai/gpt-oss-20b"
    stt_model: str = "nova-3"
    stt_language: str = "en"
    tts_model: str = "aura-2-thalia-en"
    demo_faults: bool = False
    artifact_dir: Path = Path(".turnlab/runs")
    slow_reply_ms: float = 2000
    # Optional OTLP/HTTP traces URL (Langfuse, SigNoz, Phoenix, Grafana Tempo...). Headers come
    # from the standard OTEL_EXPORTER_OTLP_HEADERS variable, read by the exporter itself.
    otel_endpoint: str = ""
    otel_include_conversation: bool = False

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "VoiceSettings":
        url = env.get("TURNLAB_LIVEKIT_URL", "ws://127.0.0.1:7880").strip()
        parsed = urlparse(url)
        if parsed.scheme not in {"ws", "wss"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("TURNLAB_LIVEKIT_URL must point to a loopback LiveKit server")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("TURNLAB_LIVEKIT_URL must not contain credentials, query, or fragment")
        flag = env.get("TURNLAB_DEMO_FAULTS", "false").strip().lower()
        if flag not in {"true", "false"}:
            raise ValueError("TURNLAB_DEMO_FAULTS must be true or false")
        conversation = env.get("TURNLAB_OTEL_INCLUDE_CONVERSATION", "false").strip().lower()
        if conversation not in {"true", "false"}:
            raise ValueError("TURNLAB_OTEL_INCLUDE_CONVERSATION must be true or false")
        otel_endpoint = env.get("TURNLAB_OTEL_ENDPOINT", "").strip()
        if otel_endpoint:
            target = urlparse(otel_endpoint)
            if target.scheme not in {"http", "https"} or not target.hostname or target.username or target.password:
                raise ValueError("TURNLAB_OTEL_ENDPOINT must be an http(s) URL without credentials; put keys in OTEL_EXPORTER_OTLP_HEADERS")
        try:
            slow_reply_ms = float(env.get("TURNLAB_SLOW_REPLY_MS", "2000"))
        except ValueError as exc:
            raise ValueError("TURNLAB_SLOW_REPLY_MS must be a number of milliseconds") from exc
        if not 0 < slow_reply_ms < 600000:
            raise ValueError("TURNLAB_SLOW_REPLY_MS must be between 0 and 600000")
        names = {
            "livekit_api_key": ("TURNLAB_LIVEKIT_API_KEY", "devkey"),
            "livekit_api_secret": ("TURNLAB_LIVEKIT_API_SECRET", "secret"),
            "groq_api_key": ("GROQ_API_KEY", ""),
            "deepgram_api_key": ("DEEPGRAM_API_KEY", ""),
            "llm_model": ("TURNLAB_LLM_MODEL", "openai/gpt-oss-20b"),
            "stt_model": ("TURNLAB_STT_MODEL", "nova-3"),
            "stt_language": ("TURNLAB_STT_LANGUAGE", "en"),
            "tts_model": ("TURNLAB_TTS_MODEL", "aura-2-thalia-en"),
        }
        values = {key: env.get(name, default).strip() for key, (name, default) in names.items()}
        for name in ("livekit_api_key", "livekit_api_secret", "llm_model", "stt_model", "stt_language", "tts_model"):
            if not values[name]:
                raise ValueError(f"{names[name][0]} must be nonempty")
        return cls(livekit_url=url, demo_faults=flag == "true", slow_reply_ms=slow_reply_ms,
                   otel_endpoint=otel_endpoint, otel_include_conversation=conversation == "true", **values)

    def validate_credentials(self) -> None:
        missing = [name for name, value in (("GROQ_API_KEY", self.groq_api_key),
                                           ("DEEPGRAM_API_KEY", self.deepgram_api_key))
                   if not value or value.lower().startswith(("your_", "replace_", "your-"))]
        if missing:
            raise ValueError("Missing configuration: " + ", ".join(missing) + ". Add these to .env locally.")
