#!/usr/bin/env python3
"""
Stream video from Luxonis OAK-D Pro W PoE to a LiveKit room.
Camera IP: 169.254.1.222
"""

import asyncio
import json
import threading
import time

import depthai as dai
from livekit import rtc
from livekit.api import AccessToken, VideoGrants

LIVEKIT_URL = "wss://cavalla-pxnr4t34.livekit.cloud"
LIVEKIT_API_KEY = "APIDL38BLr62tR2"
LIVEKIT_API_SECRET = "Ve31E1uUqQBJPST5s1Leu8v8ViOBcoQ5oEVwVBHcvLJ"
ROOM_NAME = "test-rig"
CAMERA_IP = "169.254.1.222"

WIDTH = 1280
HEIGHT = 800  # native sensor resolution (OV9782)
FPS = 30


def generate_token() -> str:
    token = AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
    token.with_identity("oak-camera")
    token.with_name("OAK-D Camera")
    token.with_grants(VideoGrants(room_join=True, room=ROOM_NAME))
    return token.to_jwt()


def camera_thread(
    frame_queue: "asyncio.Queue[tuple[bytes, int]]",
    loop: asyncio.AbstractEventLoop,
    stop_event: threading.Event,
    ready_event: threading.Event,
) -> None:
    try:
        # depthai 3.x API: Device is passed into Pipeline, nodes are created inside
        print(f"Connecting to OAK camera at {CAMERA_IP}...")
        devs = dai.Device.getAllAvailableDevices()
        device_info = next((d for d in devs if d.name == CAMERA_IP), None)
        if device_info is None:
            raise RuntimeError(f"No device found at {CAMERA_IP} (found: {[d.name for d in devs]})")

        with dai.Pipeline(dai.Device(device_info)) as pipeline:
            device = pipeline.getDefaultDevice()
            print(f"OAK camera connected — {device.getDeviceName()}")

            cam = pipeline.create(dai.node.Camera).build(dai.CameraBoardSocket.CAM_A)
            rgb_out = cam.requestOutput(
                (WIDTH, HEIGHT),
                type=dai.ImgFrame.Type.RGB888i,
                fps=float(FPS),
            )
            q = rgb_out.createOutputQueue(maxSize=4, blocking=False)
            pipeline.start()
            ready_event.set()  # signal main thread that camera is up

            while not stop_event.is_set():
                frame = q.tryGet()
                if frame is None:
                    time.sleep(0.001)
                    continue

                raw: bytes = bytes(frame.getData())
                ts_us: int = int(frame.getTimestampDevice().total_seconds() * 1_000_000)

                asyncio.run_coroutine_threadsafe(
                    frame_queue.put((raw, ts_us)),
                    loop,
                )
    except Exception as e:
        import traceback
        print(f"[camera_thread ERROR] {type(e).__name__}: {e}")
        traceback.print_exc()
    finally:
        ready_event.set()  # unblock main thread even on error


async def publish_frames(
    source: rtc.VideoSource,
    frame_queue: "asyncio.Queue[tuple[bytes, int]]",
    stop_event: threading.Event,
) -> None:
    frames_sent = 0
    t0 = time.monotonic()

    try:
        while not stop_event.is_set():
            raw, ts_us = await asyncio.wait_for(frame_queue.get(), timeout=5.0)

            video_frame = rtc.VideoFrame(
                width=WIDTH,
                height=HEIGHT,
                type=rtc.VideoBufferType.RGB24,
                data=raw,
            )
            source.capture_frame(video_frame, timestamp_us=ts_us)

            frames_sent += 1
            if frames_sent % 100 == 0:
                elapsed = time.monotonic() - t0
                print(f"Sent {frames_sent} frames ({frames_sent / elapsed:.1f} fps)")
    except asyncio.TimeoutError:
        print("No frames received for 5 seconds — stopping")
    except asyncio.CancelledError:
        pass


async def main() -> None:
    token = generate_token()

    room = rtc.Room()

    source = rtc.VideoSource(WIDTH, HEIGHT)
    track = rtc.LocalVideoTrack.create_video_track("oak-camera", source)

    @room.on("data_received")
    def on_data_received(data_packet) -> None:
        try:
            msg = json.loads(data_packet.data.decode("utf-8"))
        except Exception as e:
            print(f"[data] Failed to parse: {e} — raw: {data!r}")
            return

        msg_type = msg.get("type")
        if msg_type == "forklift-control":
            direction = msg.get("direction", "?")
            state = msg.get("state", "?")
            sent_at = msg.get("sentAt", "")
            print(f"[cmd] {direction} {state}  (sentAt={sent_at})")
        elif msg_type == "forklift-heartbeat":
            sent_at = msg.get("sentAt", "")
            print(f"[heartbeat] sentAt={sent_at}")
        else:
            print(f"[data] Unknown message type: {msg!r}")

    print(f"Connecting to LiveKit room '{ROOM_NAME}'...")
    await room.connect(LIVEKIT_URL, token)
    print(f"Connected. Room: {room.name}")

    publish_opts = rtc.TrackPublishOptions()
    publish_opts.source = rtc.TrackSource.SOURCE_CAMERA
    await room.local_participant.publish_track(track, publish_opts)
    print("Video track published — streaming started")

    frame_queue: asyncio.Queue[tuple[bytes, int]] = asyncio.Queue(maxsize=16)
    stop_event = threading.Event()
    ready_event = threading.Event()
    loop = asyncio.get_running_loop()

    cam_thread = threading.Thread(
        target=camera_thread,
        args=(frame_queue, loop, stop_event, ready_event),
        daemon=True,
    )
    cam_thread.start()

    print("Waiting for camera to connect...")
    await loop.run_in_executor(None, lambda: ready_event.wait(timeout=60))
    if not ready_event.is_set() or not cam_thread.is_alive():
        print("Camera failed to connect — aborting")
        stop_event.set()
        await room.disconnect()
        return

    try:
        await publish_frames(source, frame_queue, stop_event)
    except KeyboardInterrupt:
        pass
    finally:
        print("Shutting down...")
        stop_event.set()
        cam_thread.join(timeout=3)
        await room.disconnect()
        print("Done")


if __name__ == "__main__":
    asyncio.run(main())
