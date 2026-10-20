"""Reference-transcript scoring and explicit opt-in recorded WAV transcription."""

from datetime import datetime, timezone
import json
from pathlib import Path
import unicodedata
from urllib.request import Request, urlopen
from uuid import uuid4
import wave


def words(text: str) -> list[str]:
    if not isinstance(text, str) or len(text) > 20000:
        raise ValueError("Transcript must be text with at most 20000 characters")
    normalized = unicodedata.normalize("NFKC", text).casefold()
    tokens = ''.join(c if c.isalnum() or c.isspace() else ' ' for c in normalized).split()
    if len(tokens) > 2000:
        raise ValueError("Transcript must contain at most 2000 words")
    return tokens


def score_transcript(reference: str, hypothesis: str, *, language: str = "en") -> dict:
    if language != "en":
        raise ValueError("Only English normalization is validated in this release")
    expected, actual = words(reference), words(hypothesis)
    if not expected:
        raise ValueError("Reference must contain at least one word")
    # Each DP cell tracks edits, substitutions, deletions, insertions. Stable tie breaking.
    row = [(i, 0, 0, i) for i in range(len(actual) + 1)]
    for i, left in enumerate(expected, 1):
        next_row = [(i, 0, i, 0)]
        for j, right in enumerate(actual, 1):
            if left == right:
                next_row.append(row[j - 1])
            else:
                e, s, d, ins = row[j - 1]
                substitution = (e + 1, s + 1, d, ins)
                e, s, d, ins = row[j]
                deletion = (e + 1, s, d + 1, ins)
                e, s, d, ins = next_row[j - 1]
                insertion = (e + 1, s, d, ins + 1)
                next_row.append(min((substitution, deletion, insertion), key=lambda cell: cell[0]))
        row = next_row
    edits, substitutions, deletions, insertions = row[-1]
    return {"schema_version": 1, "id": str(uuid4()), "created_at": datetime.now(timezone.utc).isoformat(),
            "mode": "transcript_scoring", "scenario_name": "English transcript accuracy", "status": "completed",
            "events": [], "checks": [], "reference": reference, "hypothesis": hypothesis,
            "normalization": "en-nfkc-casefold-alphanumeric-v1", "reference_words": len(expected),
            "substitutions": substitutions, "deletions": deletions, "insertions": insertions,
            "metrics": {"wer": {"status": "measured", "value": edits / len(expected)}},
            "coverage": "Word error rate against a supplied reference. No automatic quality pass threshold; no TTS, turn latency, interruption, or semantic quality measurement."}


def transcribe_wav(path: Path, key: str) -> str:
    # Validate before transmitting. No arbitrary URL, no automatic directory upload.
    if not key.strip() or path.stat().st_size > 10 * 1024 * 1024:
        raise ValueError("A Deepgram key and a WAV file under 10 MiB are required")
    try:
        with wave.open(str(path), 'rb') as audio:
            duration = audio.getnframes() / audio.getframerate()
            if audio.getcomptype() != 'NONE' or audio.getnchannels() not in (1, 2) or not 0 < duration <= 120:
                raise ValueError("Use an uncompressed mono/stereo WAV up to 120 seconds")
    except (wave.Error, EOFError):
        raise ValueError("Input must be a valid uncompressed WAV") from None
    request = Request('https://api.deepgram.com/v1/listen?model=nova-3&language=en&smart_format=true',
                      data=path.read_bytes(), method='POST', headers={'Authorization': f'Token {key}', 'Content-Type': 'audio/wav'})
    try:
        with urlopen(request, timeout=45) as response:
            result = json.loads(response.read())
        return result['results']['channels'][0]['alternatives'][0]['transcript']
    except Exception:
        raise ValueError("Deepgram transcription failed; no provider body or credentials are logged") from None
