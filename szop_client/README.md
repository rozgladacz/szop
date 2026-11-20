# `szop-client`

`szop-client` is the local Python client seam for the SZOP monorepo. Version
`0.1.0` supports Python 3.13 and is installed from the repository root:

```powershell
python -m pip install -e .\szop_client
```

This is deliberately an **editable monorepo install**, not a standalone
distribution. The editable mapping adds the current repository checkout to the
environment so `szop_client` can reuse the existing `app` action, state and
event codecs as their single source of truth. It neither copies those modules
nor declares the server as part of a publishable client artifact. Moving or
removing the checkout breaks the editable installation; reinstall after moving
it.

The distribution is named `szop-client`; the import remains:

```python
from szop_client import HttpClient, HttpClientError

client = HttpClient("http://127.0.0.1:8000", token="local-token")
```

Constructing `HttpClient` performs no HTTP or database I/O. Top-level
`import szop_client` keeps all public exports lazy and does not load the ORM,
database configuration or FastAPI. `LocalClient` remains the lazy, in-process
monorepo implementation and keeps its existing public API.

Runtime dependencies reflect the shared checkout import graph:
`pydantic>=2,<3`, `PyYAML>=6,<7` and `SQLAlchemy>=2,<3`. The standard library
provides the HTTP transport.

Building or publishing a wheel/sdist, bundling `app`, and uploading to a package
index are outside this contract. A future publishable HTTP-only distribution
needs a separate architecture decision about the shared codecs.

The optional leaf `szop_client.bot_proposals` connects one existing `priority`
decision to a pending public v1 proposal, with owner approval kept separate.
It loads the existing local bot explicitly; top-level imports remain lazy.
Usage, supported states/actions, one-shot instance deduplication and restart/
timeout reconciliation are in [D6.2](../docs/boty-connect.md).
