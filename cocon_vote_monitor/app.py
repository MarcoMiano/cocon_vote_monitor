from flask import Flask, render_template
import json

app = Flask(__name__)


@app.route("/")
def index() -> str:
    with open("data/votes.json") as f:
        data = json.load(f)

    counts: dict[str, int] = {"yes": 0, "no": 0, "abst": 0}
    for v in data["votes"]:
        vote_type = v["vote"].lower()
        if vote_type in counts:
            counts[vote_type] += 1

    columns = [data["votes"][i : i + 16] for i in range(0, len(data["votes"]), 16)]

    return render_template(
        "index.html",
        title=data["title"],
        datetime=data["datetime"],
        columns=columns,
        counts=counts,
    )


if __name__ == "__main__":
    app.run(debug=True)
