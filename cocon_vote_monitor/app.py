# app.py
import asyncio
from contextlib import suppress
from datetime import datetime
from typing import Dict, List, Tuple

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse
from starlette.routing import Route, Mount, WebSocketRoute
from starlette.websockets import WebSocket
from starlette.staticfiles import StaticFiles


from cocon_client import (
    CoConClient,
    Model,
    JSON,
    parse_notification,
    Meeting,
    Delegates,
    AgendaItem,
    logger,
)

###############################################################################
# ─────────────────────────────  CONFIG  ──────────────────────────────────────
###############################################################################

COCON_HOST = "10.17.12.231"
COCON_PORT = 8890


###############################################################################
# ───────────────────────────  SHARED STATE  ─────────────────────────────────-
###############################################################################
# This dict is mutated only by the background worker and read by request-handlers.

state: Dict[str, object] = {
    "meeting_title": "",
    "agenda_title": "Waiting for meeting…",
    "datetime": "",
    "columns": [],  # list[list[tuple[str,str]]]
    "counts": {"YES": 0, "ABST": 0, "NO": 0},
    "show_results": False,
    "voting_state": "",
}

# Active websocket connections
clients: set[WebSocket] = set()

###############################################################################
# ────────────────────────────  HELPERS  ──────────────────────────────────────
###############################################################################


def chunk_votes(votes: Dict[str, str], size: int = 16) -> List[List[Tuple[str, str]]]:
    """Split {'Italy':'YES', …} into chunks for the template."""
    items = list(votes.items())
    return [items[i : i + size] for i in range(0, len(items), size)]


def now_str() -> str:
    now = datetime.now()
    return f"Date {now:%Y-%m-%d} Time {now:%H:%M}"


async def broadcast() -> None:
    """Send the current state to all connected websocket clients."""
    if not clients:
        return
    to_remove: list[WebSocket] = []
    for ws in clients:
        try:
            await ws.send_json(state)
        except Exception:
            to_remove.append(ws)
    for ws in to_remove:
        clients.discard(ws)


###############################################################################
# ───────────────────────  BACKGROUND WORKER  ────────────────────────────────
###############################################################################


async def cocon_worker() -> None:
    """
    Connect to CoCon once, stay subscribed, and update `state` in-place.
    Cancelling this coroutine stops the client gracefully.
    """
    meeting = Meeting()
    agenda_item = AgendaItem()
    delegates_in_meeting = Delegates()
    votes_by_voteid: Dict[int, Dict[str, str]] = {}
    current_vote_id = -1

    async def handler(data: JSON | str) -> None:
        nonlocal meeting, agenda_item, delegates_in_meeting, current_vote_id
        if isinstance(data, str):
            return

        result = parse_notification(data)

        match result.__class__.__name__:
            # meeting state ────────────────────────────────────────────────
            case "MeetingStatus":
                if result.State == "Ended":
                    state["agenda_title"] = "Meeting ended"

            # active agenda item ───────────────────────────────────────────
            case "AgendaItem":
                if result.State == "active":
                    agenda_item = result
                    state["agenda_title"] = agenda_item.Title

            # delegate list ────────────────────────────────────────────────
            case "Delegates":
                delegates_in_meeting = result

            # voting state ─────────────────────────────────────────────────
            case "VotingState":
                if result.State in {"Start", "Stop", "Pause"}:
                    current_vote_id = result.Id
                    votes_by_voteid.setdefault(
                        current_vote_id,
                        {d.Name: "" for d in delegates_in_meeting.delegates},
                    )
                elif result.State == "Clear":
                    current_vote_id = -1
                    votes_by_voteid.clear()  # throw away old vote maps
                    state["columns"] = []  # remove country tiles
                    state["counts"] = {"YES": 0, "ABST": 0, "NO": 0}  # zero the footer
                    state["agenda_title"] = agenda_item.Title or "Waiting for vote…"
                    state["show_results"] = False
                state["show_results"] = result.State == "Stop"
                state["voting_state"] = result.State

            # individual results ──────────────────────────────────────────
            case "IndividualVotingResults":
                if current_vote_id == -1:
                    return
                for vr in result.VotingResults:
                    delegate = delegates_in_meeting.by_id(vr.DelegateId)
                    if delegate:
                        text = next(
                            (
                                opt["Name"]
                                for opt in agenda_item.VotingOptions
                                if opt["Id"] == vr.VotingOptionId
                            ),
                            "",
                        )
                        votes_by_voteid[current_vote_id][delegate.Name] = text

            # totals ───────────────────────────────────────────────────────
            case "GeneralVotingResults":
                totals = {
                    opt["Name"].upper(): opt["Votes"]["Count"]
                    for opt in result.VotingResults["Options"]
                }
                state["counts"] = {"YES": 0, "ABST": 0, "NO": 0} | totals

        # refresh public snapshot whenever anything interesting happened
        if current_vote_id in votes_by_voteid:
            state["columns"] = chunk_votes(votes_by_voteid[current_vote_id])
        state["datetime"] = now_str()
        await broadcast()

    # ───────────  open the CoCon connection  ───────────
    async with CoConClient(
        url=COCON_HOST,
        port=COCON_PORT,
        handler=handler,
        on_handler_error=lambda exc, d: logger.error("handler error: %s", exc),
    ) as client:
        # ─────────────────────────  BOOTSTRAP ONCE  ────────────────────
        await asyncio.sleep(1)
        try:
            # 1. current meeting today
            resp = await client.send("Meeting_Agenda/GetMeetingsForToday")
            meetings = parse_notification(resp.get("GetMeetings", []))
            meeting = meetings.get_active()

            # 2.1. delegates in that meeting
            resp = await client.send(
                "Delegate/GetDelegatesInMeeting",
                {"MeetingId": meeting.Id},
            )
            delegates_in_meeting: Delegates = parse_notification(
                resp.get("GetDelegatesInMeeting", [])
            )
            # 2.2. all delegates
            resp = await client.send("Delegate/GetAllDelegates")
            delegates: Delegates = parse_notification(resp.get("GetAllDelegates", []))

            # 2.3 add voting rights value in delegates_in_meeting objects
            for i in range(len(delegates_in_meeting.delegates)):
                delegate_id = delegates_in_meeting.delegates[i].Id
                for d in delegates.delegates:
                    if d.Id == delegate_id:
                        delegates_in_meeting.delegates[i].VotingRight = d.VotingRight

            # 2.4. filter delegates_in_meeting to only who have voting rights
            delegates_in_meeting = delegates_in_meeting.filter_by_voting_right()

            # 3. active agenda item
            resp = await client.send(
                "Meeting_Agenda/GetAgendaItemInformationInRunningMeeting"
            )
            agenda = parse_notification(
                resp.get("GetAgendaItemInformationInRunningMeeting", [])
            )
            agenda_item = agenda.get_active()

            # initialise states
            state["meeting_title"] = meeting.Title or ""
            state["agenda_title"] = agenda_item.Title or "Waiting for vote…"
            state["datetime"] = now_str()
            state["show_results"] = False
            await broadcast()
        except Exception as exc:  # pragma: no cover
            logger.error("bootstrap failed: %s", exc, exc_info=True)
        # ──────────────────────  END BOOTSTRAP  ────────────────────────

        # subscribe after bootstrap so we still get live updates

        await client.unsubscribe(
            [
                Model.MICROPHONE,
                Model.TIMER,
                Model.AUDIO,
                Model.LOGGING,
                Model.INTERPRETATION,
            ]
        )
        # sleep forever – cancellation will break us out
        await asyncio.Event().wait()


###############################################################################
# ─────────────────────────────  ROUTES  ─────────────────────────────────────
###############################################################################


async def homepage(request: Request) -> FileResponse:
    return FileResponse("templates/index.html")


async def auto_homepage(request: Request) -> FileResponse:
    return FileResponse("templates/index.html")


async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    clients.add(ws)
    try:
        await ws.send_json(state)
        while True:
            await ws.receive_text()  # keep connection open, ignore messages
    except Exception:
        pass
    finally:
        clients.discard(ws)


routes = [
    Route("/", endpoint=homepage),
    Route("/autoprint", endpoint=auto_homepage),
    WebSocketRoute("/ws", endpoint=websocket_endpoint),
    Mount("/static", StaticFiles(directory="static"), name="static"),
]

###############################################################################
# ─────────────────────────────  APP  ────────────────────────────────────────
###############################################################################

app = Starlette(debug=True, routes=routes)


@app.on_event("startup")
async def _start_worker() -> None:
    # store the task on app.state so we can cancel it later
    app.state.cocon_task = asyncio.create_task(cocon_worker(), name="cocon-worker")


@app.on_event("shutdown")
async def _stop_worker() -> None:
    task: asyncio.Task | None = getattr(app.state, "cocon_task", None)
    if task:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
