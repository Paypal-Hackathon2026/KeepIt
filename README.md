# KeepIt

<p align="center">
  <img src="app/static/img/coin.svg" width="96" alt="KeepIt logo">
</p>

## How to run tests

Create and activate a virtual environment, then install the development dependencies:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

On macOS or Linux, activate the environment with `source .venv/bin/activate`.
Tests use dummy service credentials from `tests/conftest.py`; database and payment
operations are mocked, so the test suite does not require a `.env` file or external
service credentials.
