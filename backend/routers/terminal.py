"""
WebSocket PTY Terminal — operator shell access with admin auth.

WebSocket: GET /ws/terminal?token=<ADMIN_TOKEN>

Protocol:
  browser -> backend:
    {"type": "input",  "data": "<stdin chars>"}
    {"type": "resize", "cols": N, "rows": N}
    {"type": "ping"}
  backend -> browser:
    {"type": "output", "data": "<stdout/stderr chars>"}
    {"type": "ready",  "message": "..."}
    {"type": "exit",   "code": N}
    {"type": "error",  "message": "..."}
    {"type": "pong"}
"""
from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import os
import pty
import signal
import struct
import termios
import time
from typing import Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Konfiguracja terminala
_PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
_DEFAULT_SHELL = os.getenv("SHELL", "/bin/bash")
_TERMINAL_READ_TIMEOUT = 0.02    # sekundy — poll interval
_MAX_SESSION_SECONDS = 3600      # max 1h na sesję
_MAX_OUTPUT_BYTES = 1024 * 128   # max 128KB jednorazowy odczyt na cykl

# Aktywnych sesji (symbol)
_active_sessions: set[str] = set()
_MAX_CONCURRENT_SESSIONS = 4


def _verify_token(token: str) -> bool:
    """Weryfikuje ADMIN_TOKEN. Jeśli nie ustawiony — środowisko dev, pozwala."""
    required = (os.getenv("ADMIN_TOKEN", "") or "").strip()
    if not required:
        return True
    return token == required


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    """Ustawia rozmiar okna PTY (TIOCSWINSZ)."""
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    except Exception:
        pass


async def _read_pty_output(fd: int) -> Optional[bytes]:
    """Non-blocking odczyt z fd PTY, zwraca bytes lub None."""
    loop = asyncio.get_event_loop()
    try:
        data = await loop.run_in_executor(None, _sync_read_pty, fd)
        return data
    except OSError:
        return None


def _sync_read_pty(fd: int) -> Optional[bytes]:
    """Synchroniczny odczyt PTY z select (timeout 20ms)."""
    import select as _select
    try:
        r, _, _ = _select.select([fd], [], [], _TERMINAL_READ_TIMEOUT)
        if r:
            return os.read(fd, _MAX_OUTPUT_BYTES)
    except OSError:
        return None
    return None


@router.websocket("/ws/terminal")
async def terminal_ws(
    ws: WebSocket,
    token: str = Query(default="", alias="token"),
    cols: int = Query(default=220),
    rows: int = Query(default=50),
):
    """
    WebSocket PTY terminal.
    Wymaga tokenu admin jako query param: ?token=<ADMIN_TOKEN>
    """
    # ── Auth
    if not _verify_token(token):
        await ws.close(code=4001, reason="Unauthorized")
        logger.warning("[terminal] Odrzucono połączenie — nieprawidłowy token")
        return

    # ── Limit sesji
    session_id = f"{id(ws)}"
    if len(_active_sessions) >= _MAX_CONCURRENT_SESSIONS:
        await ws.accept()
        await ws.send_text(json.dumps({"type": "error", "message": "Zbyt wiele aktywnych sesji terminala."}))
        await ws.close()
        return

    _active_sessions.add(session_id)
    await ws.accept()

    pid: Optional[int] = None
    master_fd: Optional[int] = None
    start_time = time.monotonic()

    try:
        # ── Fork PTY + bash
        pid, master_fd = pty.fork()

        if pid == 0:
            # ── Proces dziecko — shell
            os.chdir(_PROJECT_ROOT)
            # Czyste środowisko terminala
            env = os.environ.copy()
            env["TERM"] = "xterm-256color"
            env["PS1"] = r"\[\033[1;32m\]rldc-bot\[\033[0m\]:\[\033[1;34m\]\w\[\033[0m\]\$ "
            env["HOME"] = os.path.expanduser("~")
            os.execle(_DEFAULT_SHELL, _DEFAULT_SHELL, "--login", env)
            # execle nie wraca — poniżej nigdy nie zostanie wykonane

        # ── Proces rodzic — obsługa WS i PTY
        _set_winsize(master_fd, rows, cols)

        # Welcome banner
        await ws.send_text(json.dumps({
            "type": "ready",
            "message": f"RLdC Terminal — bash @ {_PROJECT_ROOT}\r\n",
        }))

        # ── Główna pętla — dwukierunkowy relay
        loop = asyncio.get_event_loop()
        ws_recv_task: Optional[asyncio.Task] = None

        async def read_from_ws() -> Optional[dict]:
            """Czeka na wiadomość od klienta."""
            try:
                raw = await ws.receive_text()
                return json.loads(raw)
            except (WebSocketDisconnect, RuntimeError):
                return None
            except json.JSONDecodeError:
                return None

        ws_recv_task = asyncio.ensure_future(read_from_ws())

        while True:
            # Sprawdzamy timeout sesji
            if time.monotonic() - start_time > _MAX_SESSION_SECONDS:
                await ws.send_text(json.dumps({"type": "error", "message": "Sesja terminala wygasła (max 1h)."}))
                break

            # ── Czytaj output z PTY (non-blocking)
            pty_data = await _read_pty_output(master_fd)
            if pty_data:
                try:
                    text = pty_data.decode("utf-8", errors="replace")
                    await ws.send_text(json.dumps({"type": "output", "data": text}))
                except WebSocketDisconnect:
                    break

            # ── Czytaj input od klienta (non-blocking — check task)
            if ws_recv_task and ws_recv_task.done():
                msg = ws_recv_task.result()
                if msg is None:
                    # Rozłączono
                    break

                mtype = msg.get("type", "")
                if mtype == "input":
                    data = msg.get("data", "")
                    if data and master_fd is not None:
                        try:
                            await loop.run_in_executor(None, os.write, master_fd, data.encode("utf-8", errors="replace"))
                        except OSError:
                            break
                elif mtype == "resize":
                    new_cols = int(msg.get("cols", cols))
                    new_rows = int(msg.get("rows", rows))
                    _set_winsize(master_fd, new_rows, new_cols)
                elif mtype == "ping":
                    await ws.send_text(json.dumps({"type": "pong"}))

                # Uruchamiamy kolejne oczekiwanie
                ws_recv_task = asyncio.ensure_future(read_from_ws())

            # Sprawdź czy dziecko żyje
            try:
                waited = os.waitpid(pid, os.WNOHANG)
                if waited[0] != 0:
                    exit_code = os.waitstatus_to_exitcode(waited[1])
                    # Opróżnij bufor PTY
                    for _ in range(20):
                        remaining = await _read_pty_output(master_fd)
                        if remaining:
                            text = remaining.decode("utf-8", errors="replace")
                            await ws.send_text(json.dumps({"type": "output", "data": text}))
                        else:
                            break
                    await ws.send_text(json.dumps({"type": "exit", "code": exit_code}))
                    break
            except ChildProcessError:
                break

            # Krótka przerwa jeśli nie ma danych (nie spin-loop)
            if not pty_data and (not ws_recv_task or not ws_recv_task.done()):
                await asyncio.sleep(0.01)

    except WebSocketDisconnect:
        logger.debug("[terminal] Klient rozłączył sesję %s", session_id)
    except Exception as exc:
        logger.error("[terminal] Błąd sesji %s: %s", session_id, exc, exc_info=True)
        try:
            await ws.send_text(json.dumps({"type": "error", "message": str(exc)[:200]}))
        except Exception:
            pass
    finally:
        # ── Cleanup
        _active_sessions.discard(session_id)
        if master_fd is not None:
            try:
                os.close(master_fd)
            except OSError:
                pass
        if pid is not None:
            try:
                os.kill(pid, signal.SIGTERM)
                await asyncio.sleep(0.1)
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except Exception:
                pass
        logger.debug("[terminal] Sesja %s zakończona", session_id)
