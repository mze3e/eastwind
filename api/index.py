"""Vercel entrypoint for the isolated synthetic administration demo."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qsl, urlencode

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

# The Python function builder may bundle the src tree without installing the
# project itself. Third-party dependencies come from the root pyproject.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from eastwind.admin import create_app

if os.environ.get('EASTWIND_PUBLIC_DEMO') != '1':
    raise RuntimeError('The Vercel entrypoint requires EASTWIND_PUBLIC_DEMO=1')

# The public function never selects a remote model, even if its environment
# contains provider settings from a different deployment.
os.environ['EASTWIND_LLM_PROVIDER'] = 'mock'
root = Path(tempfile.mkdtemp(prefix='eastwind-public-', dir='/tmp'))
admin = create_app(root, public_demo=True, prefix='/admin')
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.state.demo_root = root
app.state.admin = admin


@app.middleware('http')
async def rewrite_function_path(request: Request, call_next):
    if len(request.scope['query_string']) > 4096:
        return PlainTextResponse('Query too large', status_code=414)
    length = request.headers.get('content-length')
    if length is not None:
        if not length.isascii() or not length.isdigit():
            return PlainTextResponse('Invalid content length', status_code=400)
        if int(length) > 16384:
            return PlainTextResponse('Request too large', status_code=413)
    # Vercel can supply either the original URL or the rewrite destination.
    # The destination carries the remaining admin path in a reserved query key.
    if request.scope['path'] in {'/api', '/api/index'}:
        query = parse_qsl(request.scope['query_string'].decode('ascii'), keep_blank_values=True)
        targets = [value for key, value in query if key == '__ew_path']
        if len(targets) > 1:
            return PlainTextResponse('Invalid route', status_code=400)
        target = targets[0] if targets else ''
        if any(part in {'.', '..'} for part in target.split('/')) or '\\' in target or target.startswith('/'):
            return PlainTextResponse('Invalid route', status_code=400)
        request.scope['path'] = '/admin/' + target
        request.scope['raw_path'] = request.scope['path'].encode('utf-8')
        request.scope['query_string'] = urlencode([(key, value) for key, value in query if key != '__ew_path']).encode()
    return await call_next(request)


app.mount('/admin', admin)
