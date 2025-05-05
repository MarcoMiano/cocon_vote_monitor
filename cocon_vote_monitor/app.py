from starlette.applications import Starlette
from starlette.responses import HTMLResponse
from starlette.routing import Route
from starlette.templating import Jinja2Templates
from starlette.requests import Request
from starlette.staticfiles import StaticFiles
import json

templates = Jinja2Templates(directory="templates")


async def index(request: Request) -> HTMLResponse:
    with open("data/votes.json") as f:
        data = json.load(f)

    counts: dict[str, int] = {"yes": 0, "no": 0, "abst": 0}
    for v in data["votes"]:
        vote_type = v["vote"].lower()
        if vote_type in counts:
            counts[vote_type] += 1

    columns = [data["votes"][i : i + 16] for i in range(0, len(data["votes"]), 16)]

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,  # required by Starlette templates
            "title": data["title"],
            "datetime": data["datetime"],
            "columns": columns,
            "counts": counts,
        },
    )


routes = [Route("/", endpoint=index)]

app = Starlette(debug=True, routes=routes)
app.mount("/static", StaticFiles(directory="static"), name="static")
