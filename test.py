import json
import asyncio
import logging
from cocon_client import (
    CoConClient,
    Model,
    JSON,
    parse_notification,
    Meeting,
    IndividualVotingResults,
    Delegates,
    Delegate,
    AgendaItem,
    AgendaItems,
    logger,
)
from pprint import pprint


def handler_error(exc: Exception, data: dict) -> None:
    print(f"handler error: {exc}\n")


async def main() -> None:
    current_meeting: Meeting = Meeting()
    current_agenda: AgendaItems
    current_agenda_item: AgendaItem
    individual_votes: IndividualVotingResults
    delegates: Delegates
    current_voting_id: int = -1
    votes: dict[int, dict[str, str]] = dict()
    current_votes: dict[str, str] = dict()
    counts: dict[str, int] = dict()
    try:
        async with CoConClient(
            url="10.17.12.231",
            port=8890,
            on_handler_error=handler_error,
        ) as cocon_server:

            async def handler(data: JSON | str) -> None:
                nonlocal \
                    current_meeting, \
                    current_agenda_item, \
                    delegates, \
                    votes, \
                    current_voting_id
                if isinstance(data, str):
                    print(f"Received a str: {data}")
                    return
                result = parse_notification(data)
                print(result.__class__)
                pprint(result)
                match result.__class__.__name__:
                    case "MeetingStatus":
                        if result.State == "Running":
                            resp: JSON = await cocon_server.send(
                                "Delegate/GetDelegatesInMeeting",
                                params={"MeetingId": current_meeting.Id},
                            )
                            resp = resp.get("GetDelegatesInMeeting", [])
                            try:
                                delegates = parse_notification(resp)
                                for delegate in delegates:
                                    votes[current_voting_id][delegate.Name] = ""
                            except Exception as exc:
                                logger.error(
                                    "parse_notification raised %s", exc, exc_info=True
                                )
                        if (
                            result.State in ["Running", "Paused", "Prepared"]
                            and result.State != current_meeting.State
                        ):
                            current_meeting_id = result.MeetingId
                            logger.debug(
                                "new meeting state: %s - current meeting ID: %s",
                                result.State,
                                current_meeting_id,
                            )
                            resp: JSON = await cocon_server.send(
                                endpoint="Meeting_Agenda/GetMeetingById",
                                params={"MeetingId": current_meeting_id},
                            )
                            current_meeting = parse_notification(
                                resp.get("GetMeeting", [])
                            )
                        elif result.State in ["Ended"]:
                            current_meeting_id = -1
                            print(f"Current Meeting ID: {current_meeting_id}")
                    case "AgendaItem":
                        if result.State == "active":
                            current_agenda_item = result
                    case "IndividualVotingResults":
                        for vote_result in result.VotingResults:
                            delegate = delegates.by_id(vote_result.DelegateId)
                            if delegate is None:
                                continue
                            delegate_name: str = delegate.Name
                            vote_text = ""
                            for vote_option in current_agenda_item.VotingOptions:
                                if vote_option["Id"] == 0:
                                    vote_text = ""
                                if vote_option["Id"] == vote_result.VotingOptionId:
                                    vote_text: str = vote_option["Name"]
                            votes[current_voting_id][delegate_name] = vote_text
                        pprint(votes)
                    case "VotingState":
                        match result.State:
                            case "Start" | "Stop" | "Pause":
                                current_voting_id = result.Id
                                if current_voting_id not in votes.keys():
                                    votes[current_voting_id] = dict()
                                    for delegate in delegates.delegates:
                                        votes[current_voting_id][delegate.Name] = ""
                                print(f"State: {result.State}")
                            case "Clear":
                                current_voting_id = -1
                    case "GeneralVotingResults":
                        for option in result.VotingResults["Options"]:
                            counts[option["Name"]] = option["Votes"]["Count"]
                        pprint(counts)

            await cocon_server.set_handler(handler=handler)
            await asyncio.sleep(0.25)
            await cocon_server.unsubscribe(
                [
                    Model.MICROPHONE,
                    Model.TIMER,
                    Model.DELEGATE,
                    Model.AUDIO,
                    Model.LOGGING,
                ]
            )
            await asyncio.sleep(1)

            # Get current meeting
            resp: JSON = await cocon_server.send(
                "Meeting_Agenda/GetMeetingsForToday",
            )
            resp = resp.get("GetMeetings", [])
            try:
                meetings = parse_notification(resp)
                current_meeting = meetings.get_active()
            except Exception as exc:
                logger.error("parse_notification raised %s", exc, exc_info=True)

            # Get delegates currently in meeting and build the votes list for the frontend
            resp = await cocon_server.send(
                "Delegate/GetDelegatesInMeeting",
                params={"MeetingId": current_meeting.Id},
            )
            resp = resp.get("GetDelegatesInMeeting", [])
            try:
                delegates = parse_notification(resp)
                for delegate in delegates.delegates:
                    current_votes[delegate.Name] = ""
            except Exception as exc:
                logger.error("parse_notification raised %s", exc, exc_info=True)

            # Get all the Agenda and extract the active item.
            resp = await cocon_server.send(
                "Meeting_Agenda/GetAgendaItemInformationInRunningMeeting"
            )
            resp = resp.get("GetAgendaItemInformationInRunningMeeting", [])
            try:
                current_agenda = parse_notification(resp)
                current_agenda_item = current_agenda.get_active()
            except Exception as exc:
                logger.error("parse_notification raised %s", exc, exc_info=True)

            while True:
                await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("Exiting")


if __name__ == "__main__":
    asyncio.run(main())
