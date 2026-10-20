from types import SimpleNamespace
import unittest

from turnlab.text_agent import GroqTextRunner
from turnlab.regression import compare_runs


def response(name=None, arguments='{}', finish='stop'):
    calls = [SimpleNamespace(id='call', function=SimpleNamespace(name=name, arguments=arguments))] if name else []
    message = SimpleNamespace(tool_calls=calls, model_dump=lambda **_: {'role': 'assistant', 'tool_calls': [
        {'id': 'call', 'type': 'function', 'function': {'name': name, 'arguments': arguments}}]})
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish)], usage=SimpleNamespace(total_tokens=10))


class TextAgentTests(unittest.TestCase):
    def client(self, responses):
        iterator = iter(responses)
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: next(iterator))))

    def test_real_tool_execution_and_idempotency_with_mocked_model(self):
        client = self.client([response('remember_day', '{"day":"Thursday"}'), response('remember_day', '{"day":"Friday"}'),
                              response('book_visit', '{"request_key":"demo-booking"}'), response('book_visit', '{"request_key":"demo-booking"}'), response()])
        report = GroqTextRunner('dummy').run(client=client)
        self.assertEqual(report['status'], 'passed')
        self.assertEqual(report['usage']['requests'], 5)
        self.assertEqual(report['events'][-1]['data']['result']['booking_count'], 1)
        self.assertEqual(compare_runs(report, report)['remaining_failures'], 0)

    def test_provider_failure_budget_and_unvalidated_arguments(self):
        failed = GroqTextRunner('dummy').run(client=self.client([]))
        self.assertEqual(failed['status'], 'incomplete')
        self.assertEqual(failed['stop_reason'], 'provider_unavailable')
        with self.assertRaises(ValueError):
            compare_runs(failed, failed)
        responses = [response('remember_day', '{"day":"private-invalid-value"}')] * 6
        limited = GroqTextRunner('dummy').run(client=self.client(responses))
        self.assertEqual(limited['stop_reason'], 'request_budget_exhausted')
        self.assertEqual(limited['usage']['requests'], 6)
        self.assertNotIn('private-invalid-value', str(limited))

    def test_model_omission_and_output_truncation_are_not_passing_runs(self):
        omitted = GroqTextRunner('dummy').run(client=self.client([response()]))
        self.assertEqual(omitted['status'], 'failed')
        truncated = GroqTextRunner('dummy').run(client=self.client([response(finish='length')]))
        self.assertEqual(truncated['status'], 'incomplete')
