"""Opt-in provider smoke check using synthetic prompts/images only. No hidden text is logged."""
import argparse
import json
import sys
import time
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', required=True)
    parser.add_argument('--model-id', default=None)
    args = parser.parse_args()
    from app import llm
    from app.model_profiles import resolve_selection
    from app.attachment_context import build_messages
    from PIL import Image
    image = BytesIO()
    Image.new('RGB', (96, 96), 'red').save(image, 'JPEG')
    cases = [('fast', False), ('deep', False), ('fast', True)]
    failed = False
    for mode, vision in cases:
        try:
            selection = resolve_selection(args.model_id, mode, vision)
        except ValueError:
            print(json.dumps(dict(mode=mode, vision=vision, status='unsupported')), flush=True)
            continue
        prompt = '请只回答这张图片的主要颜色。' if vision else '计算 17 乘 23，只输出结果。'
        messages = build_messages('请简短回答。', prompt, [('测试图片', image.getvalue())] if vision else [])
        started, first = time.perf_counter(), None
        reasoning_seen, content = False, ''
        stream = None
        try:
            stream = llm._client_for_selection(selection).chat.completions.create(
                model=selection.model, messages=messages, stream=True,
                **selection.request_options())
            for event in stream:
                if not event.choices:
                    continue
                delta = event.choices[0].delta
                reasoning_seen |= bool(getattr(delta, 'reasoning', None) or getattr(delta, 'reasoning_content', None))
                if delta.content:
                    if first is None:
                        first = round((time.perf_counter() - started) * 1000)
                    content += delta.content
            matched = ('红' in content or 'red' in content.lower()) if vision else '391' in content
            failed |= not matched
            print(json.dumps(dict(mode=mode, vision=vision, model=selection.model,
                status='passed' if matched else 'unexpected_answer', reasoning_observed=reasoning_seen,
                first_token_ms=first, total_ms=round((time.perf_counter() - started) * 1000))), flush=True)
        except Exception as exc:
            failed = True
            print(json.dumps(dict(mode=mode, vision=vision, status='failed', error_type=type(exc).__name__)), flush=True)
        finally:
            if stream:
                stream.close()
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
