import sys

import pytest

# Make importing soundrec.pa fail for the whole run, collection included:
# starting PortAudio loads every ASIO driver on the machine, and these tests
# run on tables, not hardware.
sys.modules["soundrec.pa"] = None


@pytest.fixture(autouse=True)
def takes_folder(tmp_path, monkeypatch):
    """Working copies go to a temp folder, never Matthew's real takes folder."""
    folder = tmp_path / "takes"
    monkeypatch.setenv("SOUNDREC_TAKES", str(folder))
    return folder
