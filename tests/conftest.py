import sys

# Make importing soundrec.pa fail for the whole run, collection included:
# starting PortAudio loads every ASIO driver on the machine, and these tests
# run on tables, not hardware.
sys.modules["soundrec.pa"] = None
