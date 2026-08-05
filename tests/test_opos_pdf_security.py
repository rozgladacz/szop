from pathlib import Path

import pytest

from app.routers.export import (
    _browser_pdf_executable,
    _render_pdf_with_browser,
    _safe_asset_fetcher,
)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/font.ttf",
        "http://127.0.0.1/private",
        Path(__file__).resolve().as_uri(),
    ],
)
def test_pdf_fetcher_rejects_network_and_files_outside_static(url: str) -> None:
    with pytest.raises(ValueError):
        _safe_asset_fetcher(url)


@pytest.mark.skipif(
    _browser_pdf_executable() is None,
    reason="Brak lokalnej przeglądarki obsługującej headless PDF",
)
def test_browser_fallback_generates_real_pdf() -> None:
    html = """<!doctype html><meta charset=\"utf-8\"><style>@page { size: A4 landscape }</style><h1>OPOS</h1>"""

    pdf = _render_pdf_with_browser(html)

    assert pdf.startswith(b"%PDF-")
    assert len(pdf) > 1_000
