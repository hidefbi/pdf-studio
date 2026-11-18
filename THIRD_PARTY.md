# Third-party software

PDF Studio is built on the open-source packages below. Each one keeps its own license, and the license texts come with the packages themselves.

| Package | License | What it does here |
|---|---|---|
| [PyMuPDF](https://pymupdf.readthedocs.io/) | AGPL-3.0, or a commercial license from Artifex | Reads, changes, and writes PDF files. This is the reason PDF Studio is released under AGPL-3.0. |
| [FastAPI](https://fastapi.tiangolo.com/) | MIT | Web API between the browser and the Python code |
| [Uvicorn](https://www.uvicorn.org/) | BSD-3-Clause | Runs the web server |
| [Pydantic](https://docs.pydantic.dev/) | MIT | Checks the data sent by the browser |
| [python-multipart](https://github.com/Kludex/python-multipart) | Apache-2.0 | Handles file uploads |
| [pdf2docx](https://github.com/dothinking/pdf2docx) | MIT | Optional. Converts PDF pages to Word files. |
| [RapidOCR (rapidocr-onnxruntime)](https://github.com/RapidAI/RapidOCR) | Apache-2.0 | Optional. Recognizes text on scanned pages. |
| PP-OCR models (inside RapidOCR) | Apache-2.0 (from PaddleOCR) | Text detection and recognition models used by the OCR feature |
| [Playwright](https://playwright.dev/python/) | Apache-2.0 | Browser tests only |
| [pytest](https://pytest.org/) | MIT | Test runner |
| [HTTPX](https://www.python-httpx.org/) | BSD-3-Clause | Test client |
| [DejaVu Sans](https://dejavu-fonts.github.io/) | DejaVu Fonts License (permits redistribution) | Font used inside one of the test PDFs in `tests/fixtures` |

The browser code uses no outside libraries. The icons and layout are written by hand.

If you find a license listed wrong here, please open an issue.
