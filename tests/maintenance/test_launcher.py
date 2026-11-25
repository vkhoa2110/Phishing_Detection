"""Real socket checks: distinguish a live listener from a just-stopped server."""
import socket

from launch import port_available


def test_launcher_rejects_a_port_held_by_another_listener():
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0)); listener.listen()
        assert not port_available(listener.getsockname()[1])


def test_launcher_can_restart_after_server_side_close_leaves_time_wait():
    with socket.socket() as listener, socket.socket() as client:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0)); listener.listen()
        port = listener.getsockname()[1]
        client.settimeout(2); client.connect(("127.0.0.1", port))
        accepted, _ = listener.accept()
        accepted.shutdown(socket.SHUT_RDWR); accepted.close()
        assert client.recv(1) == b""
    assert port_available(port)
