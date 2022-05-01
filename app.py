import json
import os
import urllib.parse
from datetime import datetime

import requests
from cachetools import TTLCache, cached
from dateutil import parser, tz
from flask import Flask, render_template

API_URL_BASE = "https://otp-mta-prod.camsys-apps.com/otp/routers/default/nearby"

app = Flask(__name__)


class Train:
    def __init__(
        self, short_name, headsign, trip_headsign, arrival, minutes, line_info
    ):
        self.short_name = short_name
        self.headsign = headsign
        self.trip_headsign = trip_headsign
        self.arrival = arrival
        self.minutes = minutes
        self.line_info = line_info


class LineInfo:
    def __init__(self, short_name, color, sort_order):
        self.short_name = short_name
        self.color = color
        self.sort_order = sort_order

    def __key(self):
        return (self.short_name, self.color, self.sort_order)

    def __hash__(self):
        return hash(self.__key())

    def __eq__(self, other):
        if isinstance(other, LineInfo):
            return self.__key() == other.__key()
        return NotImplemented


class Stop:
    def __init__(self, name, headsigns, lines):
        self.name = name
        self.headsigns = headsigns
        self.lines = list(lines)

        # Sort the line letters (e.g. A/C/E).
        self.lines.sort(key=lambda line: line.sort_order)

        # Sort the arrival times, in descending order.
        for headsign, trains in self.headsigns.items():
            trains.sort(key=lambda train: train.minutes)
            self.headsigns[headsign] = trains[:4]


class FetchResult:
    def __init__(self, stops, timestamp):
        self.stops = stops
        self.timestamp = timestamp


@cached(cache=TTLCache(maxsize=32, ttl=10))
def fetch_train_data(stops_str, api_key):
    params = {"apikey": api_key, "stops": stops_str}
    stops = []

    response = requests.get(API_URL_BASE, params=params)
    if response.status_code != 200:
        return None

    now = datetime.now(tz.gettz("US/Eastern"))

    for stop in response.json():
        stop_name = stop["stop"]["name"]

        headsigns = {}
        lines = set()  # For deduplication.

        for group in stop["groups"]:
            route = group["route"]
            headsign = group["headsign"]
            short_name = route["shortName"]
            sort_order = route["sortOrder"]
            color = route["color"]

            for time in group["times"]:
                trip_headsign = time["tripHeadsign"]
                arrival_fmt = time["arrivalFmt"]
                arrival = parser.parse(arrival_fmt)
                minutes = (arrival - now).total_seconds() / 60

                line_info = LineInfo(
                    short_name=short_name, color=color, sort_order=sort_order
                )

                train = Train(
                    short_name=short_name,
                    headsign=headsign,
                    trip_headsign=trip_headsign,
                    arrival=arrival,
                    minutes=round(minutes),
                    line_info=line_info,
                )

                if headsign not in headsigns:
                    headsigns[headsign] = []

                headsigns[headsign].append(train)
                lines.add(line_info)

        stops.append(Stop(name=stop_name, headsigns=headsigns, lines=lines))

    return FetchResult(stops=stops, timestamp=now)


@app.route("/")
def main():
    stops = os.environ.get("STOPS")
    api_key = os.environ.get("API_KEY")
    result = fetch_train_data(stops, api_key)
    return render_template("index.html", stops=result.stops, timestamp=result.timestamp)
