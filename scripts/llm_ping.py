#!/usr/bin/env python3
"""Plan or make one explicitly enabled Gemini request."""
import argparse
import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from bugzilla_qa.llm.provider import GeminiProvider, ROOT, read_config

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--config', type=Path, default=ROOT / 'configs/llm.yaml')
parser.add_argument('--role', choices=['generator', 'aux'], default='aux')
parser.add_argument('--model', help='Explicit model override for this invocation')
parser.add_argument('--list-models', action='store_true', help='List one page of available generation model IDs using one budgeted API call')
mode = parser.add_mutually_exclusive_group()
mode.add_argument('--enable-llm', action='store_true')
mode.add_argument('--dry-run', action='store_true')
parser.add_argument('--max-requests', type=int, default=1, choices=[1])
args = parser.parse_args()
provider = GeminiProvider(read_config(args.config), args.role, enable_llm=args.enable_llm, max_requests=args.max_requests)
if args.model:
    import re
    if not re.fullmatch(r'[A-Za-z0-9._/-]+', args.model): parser.error('Invalid model ID')
    provider.model = dict(provider.model, id=args.model.removeprefix('models/'))
try:
    result = provider.list_models() if args.list_models else provider.generate_json(
        'Return the requested acknowledgement.', {'type': 'object', 'properties': {'ok': {'type': 'boolean'}},
        'required': ['ok'], 'additionalProperties': False},
        prompt_version='ping-' + datetime.datetime.now(datetime.timezone.utc).isoformat(), purpose='ping')
except RuntimeError as error:
    parser.exit(1, str(error) + '\n')
summary = {k: result.get(k) for k in ('state', 'model', 'latency_ms', 'input_tokens', 'output_tokens')}
if args.list_models and 'value' in result: summary.update(result['value'])
print(json.dumps(summary))
