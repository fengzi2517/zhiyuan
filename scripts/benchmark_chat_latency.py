"""Explicit live LLM diagnostic: sends only greetings; no credentials/content logged."""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', type=int, default=1)
    args = parser.parse_args()
    if not 1 <= args.runs <= 5:
        parser.error('--runs must be between 1 and 5')
    from app import llm
    from app.main import chat_service
    for run in range(args.runs):
        question = '你好'
        started = time.perf_counter()
        first = None
        for token in llm.chat_stream([{'role': 'user', 'content': question}]):
            if token and first is None:
                first = round((time.perf_counter() - started) * 1000)
        print(json.dumps({'run': run+1, 'case': 'direct', 'first_token_ms': first,
                          'total_ms': round((time.perf_counter()-started)*1000)}), flush=True)
        started = time.perf_counter()
        for event in chat_service.run_stream(question, history=[], memory=None, web_enabled=False):
            if event['event'] == 'error':
                raise RuntimeError(event['data']['code'])
            if event['event'] == 'done':
                generation = next(step for step in event['data']['trace'] if step['stage'] == 'generate')
                print(json.dumps({'run': run+1, 'case': 'workflow',
                                  'first_token_ms': generation.get('first_token_ms'),
                                  'total_ms': round((time.perf_counter()-started)*1000)}), flush=True)


if __name__ == '__main__':
    main()
