# app.py
import asyncio
from contextlib import suppress
from datetime import datetime
from pprint import pprint
from typing import Dict, List, Tuple

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route, Mount
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

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

templates = Jinja2Templates(directory="templates")

###############################################################################
# ───────────────────────────  SHARED STATE  ─────────────────────────────────-
###############################################################################
# This dict is mutated only by the background worker and read by request-handlers.

state: Dict[str, object] = {
    "title": "Waiting for meeting…",
    "datetime": "",
    "columns": [],  # list[list[tuple[str,str]]]
    "counts": {"YES": 0, "ABST": 0, "NO": 0},
}

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
    delegates = Delegates()
    votes_by_voteid: Dict[int, Dict[str, str]] = {}
    current_vote_id = -1

    async def handler(data: JSON | str) -> None:
        nonlocal meeting, agenda_item, delegates, current_vote_id
        if isinstance(data, str):
            return

        result = parse_notification(data)
        pprint(result)

        match result.__class__.__name__:
            # meeting state ────────────────────────────────────────────────
            case "MeetingStatus":
                if result.State == "Ended":
                    state["title"] = "Meeting ended"

            # active agenda item ───────────────────────────────────────────
            case "AgendaItem":
                if result.State == "active":
                    agenda_item = result
                    state["title"] = agenda_item.Title

            # delegate list ────────────────────────────────────────────────
            case "Delegates":
                delegates = result

            # voting state ─────────────────────────────────────────────────
            case "VotingState":
                if result.State in {"Start", "Stop", "Pause"}:
                    current_vote_id = result.Id
                    votes_by_voteid.setdefault(
                        current_vote_id,
                        {d.Name: "" for d in delegates.delegates},
                    )
                elif result.State == "Clear":
                    current_vote_id = -1
                    votes_by_voteid.clear()  # throw away old vote maps
                    state["columns"] = []  # remove country tiles
                    state["counts"] = {"YES": 0, "ABST": 0, "NO": 0}  # zero the footer
                    state["title"] = agenda_item.Title or "Waiting for vote…"

            # individual results ──────────────────────────────────────────
            case "IndividualVotingResults":
                if current_vote_id == -1:
                    return
                for vr in result.VotingResults:
                    delegate = delegates.by_id(vr.DelegateId)
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
            print("!!!!!!!!!!!!BOOTSTRAP!!!!!!!!!!!!!!")
            # 1. current meeting today
            resp = await client.send("Meeting_Agenda/GetMeetingsForToday")
            meetings = parse_notification(resp.get("GetMeetings", []))
            meeting = meetings.get_active()

            # 2. delegates in that meeting
            resp = await client.send(
                "Delegate/GetDelegatesInMeeting",
                {"MeetingId": meeting.Id},
            )
            delegates = parse_notification(resp.get("GetDelegatesInMeeting", []))

            # 3. active agenda item
            resp = await client.send(
                "Meeting_Agenda/GetAgendaItemInformationInRunningMeeting"
            )
            agenda = parse_notification(
                resp.get("GetAgendaItemInformationInRunningMeeting", [])
            )
            agenda_item = agenda.get_active()

            # initialise state so tiles appear immediately
            votes_by_voteid[0] = {d.Name: "" for d in delegates.delegates}
            state["columns"] = chunk_votes(votes_by_voteid[0])
            state["title"] = agenda_item.Title or "Waiting for vote…"
            state["datetime"] = now_str()
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
            ]
        )
        # sleep forever – cancellation will break us out
        await asyncio.Event().wait()


###############################################################################
# ─────────────────────────────  ROUTES  ─────────────────────────────────────
###############################################################################


async def homepage(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request, **state})


async def api_data(request: Request) -> JSONResponse:
    return JSONResponse(state)


routes = [
    Route("/", endpoint=homepage),
    Route("/api/data", endpoint=api_data),
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
