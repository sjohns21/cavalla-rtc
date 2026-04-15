# cavalla-rtc

Real-time video streaming and teleoperation system for a forklift. A camera on the forklift streams live video to a remote operator over [LiveKit](https://livekit.io/), and the operator sends directional commands back over the same connection.

## Architecture

```
forklift/          — runs on the forklift
  stream.py        — captures video from OAK-D camera, publishes to LiveKit room,
                     receives and logs operator commands

operator/          — runs on the operator's machine (or a server)
  server.py        — Flask server that mints LiveKit access tokens
  index.html       — browser UI: live video grid + directional controls
```

The two sides communicate through a shared LiveKit room. The forklift publishes a video track; the operator subscribes to it and sends control messages over a LiveKit data channel.

## Components

### forklift (`stream.py`)

- Connects to a **Luxonis OAK-D Pro W PoE** camera at `169.254.1.222`
- Streams 1280×800 @ 30 fps RGB video to the LiveKit room as a camera track
- Listens for `forklift-control` messages (direction + state) and `forklift-heartbeat` messages from the operator
- Continues running if the camera is unavailable

### operator (`server.py` + `index.html`)

- Flask server exposes `GET /cavalla-rtc/token` to issue short-lived LiveKit JWT tokens for browser participants
- Browser UI shows up to 6 video tiles for forklift camera streams
- D-pad controls send `forward`, `backward`, `left`, `right`, `fork-rise`, and `fork-lower` commands over the LiveKit data channel
- Heartbeat is transmitted to the forklift at regular intervals

## Setup

### Environment variables

Both components read from a `.env` file:

```
LIVEKIT_URL=wss://your-livekit-server
LIVEKIT_API_KEY=your-api-key
LIVEKIT_API_SECRET=your-api-secret
LIVEKIT_ROOM=cavalla-forklift-operator   # optional, defaults shown
```

### forklift

```bash
cd forklift
pip install -r requirements.txt
python stream.py
```

### operator

```bash
cd operator
pip install -r requirements.txt
python server.py          # serves on port 5000 by default
# or: gunicorn server:app
```

Then open `http://localhost:5000` in a browser, enter the room name, and click **Join Room**.

## Dependencies

| Component | Key packages |
|-----------|-------------|
| forklift  | `depthai`, `livekit`, `livekit-api` |
| operator  | `Flask`, `flask-cors`, `livekit-api` |
