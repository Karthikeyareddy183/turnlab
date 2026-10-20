"""Opt-in, bounded Groq text acceptance case using real tool execution, without audio."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
from time import perf_counter
from uuid import uuid4

from turnlab.memory import ScopedMemory

PROMPT = ('First remember Thursday as my visit day. Correction: remember Friday instead. '
          'Book one visit using request key demo-booking. Then repeat that same booking request with the same key '
          'to check duplicate protection. Use the tools to carry out each step in order.')
SYSTEM = ('You are an isolated booking test agent. Carry out the user requests using tools. '
          'Remember corrections before booking. Never invent tool results. Only synthetic data is available.')
TOOLS = [
    {"type": "function", "function": {"name": "remember_day", "description": "Save or correct the caller visit day.",
        "parameters": {"type": "object", "properties": {"day": {"type": "string", "enum": ["Thursday", "Friday"]}}, "required": ["day"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "book_visit", "description": "Book using the remembered day. The same request key returns the original booking without duplicating it.",
        "parameters": {"type": "object", "properties": {"request_key": {"type": "string", "enum": ["demo-booking"]}}, "required": ["request_key"], "additionalProperties": False}}},
]
CONTRACT = sha256(json.dumps({"version": 1, "prompt": PROMPT, "system": SYSTEM, "tools": TOOLS,
                             "checks": "remember_thursday,correct_friday,repeat_booking,one_booking,booked_friday"}, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class GroqTextRunner:
    key: str = field(repr=False)
    model: str = 'openai/gpt-oss-20b'

    def run(self, *, client=None) -> dict:
        if client is None:
            from openai import OpenAI
            with OpenAI(api_key=self.key, base_url='https://api.groq.com/openai/v1', timeout=15, max_retries=0) as provider:
                return self.run(client=provider)
        run_id = str(uuid4())
        created = datetime.now(timezone.utc).isoformat()
        started = perf_counter()
        memory = ScopedMemory()
        bookings, events, calls = {}, [], []
        messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": PROMPT}]
        stop_reason = 'request_budget_exhausted'
        tokens, requests = 0, 0
        for _ in range(6):
            try:
                requests += 1
                result = client.chat.completions.create(model=self.model, messages=messages, tools=TOOLS,
                    parallel_tool_calls=False, max_completion_tokens=1200,
                    **({"reasoning_effort": "low"} if self.model.startswith('openai/gpt-oss') else {}))
                tokens += getattr(getattr(result, 'usage', None), 'total_tokens', 0) or 0
                message = result.choices[0].message
                tool_calls = message.tool_calls or []
                if not tool_calls:
                    stop_reason = 'model_finished' if result.choices[0].finish_reason == 'stop' else 'output_incomplete'
                    break
                if len(tool_calls) > 12 - len(calls):
                    stop_reason = 'tool_budget_exhausted'
                    break
                messages.append(message.model_dump(exclude_none=True))
                for call in tool_calls:
                    name = call.function.name
                    try:
                        args = json.loads(call.function.arguments)
                        if name == 'remember_day' and isinstance(args, dict) and set(args) == {'day'} and args['day'] in ('Thursday', 'Friday'):
                            entry = memory.put('demo', 'caller', 'day', args['day'])
                            output = {'day': entry.value, 'version': entry.version}
                        elif name == 'book_visit' and args == {'request_key': 'demo-booking'}:
                            remembered = memory.get('demo', 'caller', 'day')
                            if remembered is None:
                                output = {'error': 'missing_day'}
                            else:
                                bookings.setdefault('demo-booking', remembered.value)
                                output = {'day': bookings['demo-booking'], 'booking_count': len(bookings)}
                        else:
                            raise ValueError('invalid tool request')
                    except (ValueError, TypeError):
                        # Never echo unvalidated model-generated arguments into artifacts.
                        args, output = {}, {'error': 'invalid_tool_request'}
                    calls.append({'name': name if name in {'remember_day', 'book_visit'} else 'unknown', 'arguments': args, 'result': output})
                    events.append({'id': f'{run_id}:{len(events)}', 'type': 'tool_result', 'offset_ms': (perf_counter() - started) * 1000,
                                   'tool': calls[-1]['name'], 'data': calls[-1]})
                    messages.append({'role': 'tool', 'tool_call_id': call.id, 'content': json.dumps(output)})
            except Exception:
                stop_reason = 'provider_unavailable'
                break
        expected = [('remember_thursday', any(c['name'] == 'remember_day' and c['arguments'] == {'day': 'Thursday'} for c in calls)),
                    ('correct_friday', memory.get('demo', 'caller', 'day') is not None and memory.get('demo', 'caller', 'day').value == 'Friday'),
                    ('repeat_booking', sum(c['name'] == 'book_visit' and c['result'].get('booking_count') == 1 for c in calls) >= 2),
                    ('one_booking', len(bookings) == 1), ('booked_friday', bookings.get('demo-booking') == 'Friday')]
        checks = [{'id': key, 'kind': 'agent_state', 'passed': value, 'expected': True, 'actual': value, 'event_indexes': list(range(len(events)))} for key, value in expected]
        incomplete = stop_reason != 'model_finished'
        return {'schema_version': 1, 'id': run_id, 'created_at': created, 'scenario_name': 'Groq text · correction and duplicate protection',
                'scenario_id': 'groq-text-v1', 'mode': 'agent_text_execution', 'model': self.model, 'contract_fingerprint': CONTRACT,
                'status': 'incomplete' if incomplete else 'passed' if all(c['passed'] for c in checks) else 'failed',
                'checks': checks, 'events': events, 'stop_reason': stop_reason,
                'usage': {'requests': requests, 'total_tokens': tokens}, 'elapsed_ms': (perf_counter() - started) * 1000,
                'coverage': 'Fresh Groq text tool-calling case with synthetic data and isolated in-memory tools. Maximum six provider requests and twelve tool calls. No speech or LiveKit call; provider errors leave an incomplete report.'}
