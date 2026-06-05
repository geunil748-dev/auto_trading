from tools import preflight_check


class FakeSocket:
    def __enter__(self) -> "FakeSocket":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def settimeout(self, timeout: int) -> None:
        self.timeout = timeout

    def connect_ex(self, address: tuple[str, int]) -> int:
        self.address = address
        return 0


def test_port_check_is_read_only_pass_by_default(monkeypatch) -> None:
    monkeypatch.setattr(preflight_check.socket, "socket", lambda *_: FakeSocket())

    check = preflight_check._check_port("port_4174", "127.0.0.1", 4174)

    assert check["status"] == "PASS"
    assert check["in_use"] is True


def test_port_check_can_fail_when_port_is_used(monkeypatch) -> None:
    monkeypatch.setattr(preflight_check.socket, "socket", lambda *_: FakeSocket())

    check = preflight_check._check_port(
        "port_4174",
        "127.0.0.1",
        4174,
        fail_when_in_use=True,
    )

    assert check["status"] == "FAIL"
    assert check["remedy"] == "Stop the existing listener before starting monitor."
