import threading

from soundrec import com


def on_a_new_thread(fn):
    result = {}

    def run():
        try:
            result["value"] = fn()
        except BaseException as e:
            result["error"] = e

    thread = threading.Thread(target=run)
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]
    return result["value"]


def test_a_new_thread_sets_up_its_own_sta():
    def body():
        before = com.current()
        with com.apartment("sta") as mine:
            inside = com.current()
            with com.apartment("mta") as nested:  # too late: stays an STA, no error
                still = com.current()
        return before, mine, inside, nested, still, com.current()

    before, mine, inside, nested, still, after = on_a_new_thread(body)
    assert before in (None, "implicit mta")
    stas = ("sta", "main sta")  # the process's first STA is its "main" one
    assert mine is True and inside in stas
    assert nested is False and still == inside
    assert after == before


def test_a_new_thread_sets_up_its_own_mta():
    def body():
        with com.apartment("mta") as mine:
            return mine, com.current()

    assert on_a_new_thread(body) == (True, "mta")
