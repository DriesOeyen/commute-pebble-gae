# Commute for Pebble (server back-end)
Commute is an application for the Pebble smartwatch that allows users to look up commute times from their current location to home and work.
Integration with Pebble Timeline allows users to receive proactive notifications when it's time to leave for work.
The app is backed by data from the Google Maps API.

This is the server back-end, meant to be deployed on Google App Engine. All relevant repos:

- :watch: Pebble watch app (required): https://github.com/DriesOeyen/commute-pebble-app/
- :cloud: Server back-end (required): this repository
- :bulb: Activity indicator LED-strip (optional): https://github.com/DriesOeyen/commute-pebble-headlights/

## Deploy instructions
Before deploying, open `main.py` and set the following variables:

- `google_maps_key`: your own Google Maps API key
- `pebble_timeline_base_url`: a replacement for Pebble's Timeline API

Before deploying, install Python dependencies with the following command:

```sh
$ pip install -r requirements.txt -t lib/
```

Then deploy to Google App Engine.
In order to use the app, compile your own version of the Pebble watch app (repo linked above) and make sure to update the server base URL to that of your own App Engine back-end.

Note on branches:

- `master`: stable version.
- `ferrari-6`: contains multiple fixes and improvements that were still in development. Most importantly: switches from App Engine Channels (deprecated) to Pub/Sub for communicating with `commute-pebble-headlights`.
- `stripe-subscriptions`: contains an early-stage abandoned effort to offer a paid service tier for Commute users.
