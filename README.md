# AI CCTV Intelligence System

A Windows desktop application for real-time video surveillance with genuine YOLO
object detection, ByteTrack tracking, a persistent event history and a dark
monitoring dashboard.

Everything runs locally. No frame, snapshot or event leaves the machine, and the
system performs no facial recognition.

---

## 1. Requirements

| Item | Requirement |
|---|---|
| OS | Windows 10 or 11, 64-bit |
| Python | 3.11 or 3.12 (3.13 is not supported by the current wheel set) |
| RAM | 8 GB minimum, 16 GB comfortable |
| GPU | Optional. CPU inference is fully supported |
| Disk | ~3 GB for the virtual environment, plus footage |

A physical CCTV camera is **not** required. A video file is enough to exercise
the entire pipeline.

---

## 2. Installation

```bat
setup.bat
```

The script:

1. finds a supported interpreter (`py -3.12`, `py -3.11`, then `python`);
2. creates the environment in `D:\ai-cctv-env` (falls back to `.venv` when D: is
   absent — the system drive here has only 6 GB free and a CUDA build of PyTorch
   needs nearly 3 GB);
3. upgrades pip;
4. installs `requirements.txt`;
5. verifies that PySide6, OpenCV, NumPy and Ultralytics import correctly.

Any failed step stops the script with an explanation instead of continuing.

### Manual installation

```bat
py -3.11 -m venv D:\ai-cctv-env
D:\ai-cctv-env\Scripts\python.exe -m pip install --upgrade pip
D:\ai-cctv-env\Scripts\python.exe -m pip install -r requirements.txt
```

### GPU acceleration

The environment on `D:` carries a CUDA build, verified on this machine:

| Component | Version |
|---|---|
| torch | 2.9.1+cu128 |
| torchvision | 0.24.1+cu128 |
| GPU | GeForce MX550, compute 7.5, 2 GB VRAM |
| Driver | 610.88 (CUDA 12.8 runtime) |

`detection.device` is set to `cuda:0`, and the violence model inherits the same
device. Measured at 640 px with both models active: **15 ms/frame** for yolov8n,
**26 ms/frame** for the violence model, **~15 fps end to end** — roughly double
the CPU figure.

To rebuild the environment elsewhere:

```bat
D:\ai-cctv-env\Scripts\python.exe -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
```

Then set **Settings → Detection → Device** to `cuda:0`. The dashboard shows the
device *actually in use*, so a silent CPU fallback is visible rather than hidden.

2 GB of VRAM holds both models at 640 px with room to spare. Raising `imgsz`
above 800, or swapping in a larger checkpoint, may exhaust it — the violence
model can be switched off independently to free headroom.

---

## 3. Running

```bat
run.bat
```

or

```bat
D:\ai-cctv-env\Scripts\python.exe main.py
```

If startup fails, `run.bat` keeps the console open and prints the exit code. The
full log is always written to `data\logs\app.log`.

Typing `python main.py` also works. If the interpreter on your PATH is not the
project's virtual environment, the application prints a notice and restarts
itself under `.venv\Scripts\python.exe`, because a system Python may have
different (or broken) versions of PyTorch and Qt. This keeps `python main.py`
and `run.bat` equivalent.

---

## 4. Model initialisation

On the first connection the detector loads `models/yolov8n.pt`. If the file is
absent, Ultralytics downloads it automatically (about 6 MB) and the application
moves it into `models/`.

A second, optional checkpoint — `models/yolo_small_weights.pt`, a 22 MB YOLOv8
with two classes (`non_violence`, `violence`) — is loaded at the same time for
safety alerts. It is **not** downloaded: the file ships with the project. Delete
it, or switch it off in Settings, to run with the main model alone.

* Internet is required **once**. Afterwards the application is fully offline.
* To install weights by hand, download a checkpoint from
  <https://github.com/ultralytics/assets/releases> and place it in `models/`,
  keeping the file name (`yolov8n.pt`, `yolov8s.pt`, `yolo11n.pt`, …).
* Any other `.pt` checkpoint can be selected in **Settings → Detection →
  Checkpoint**.

If the model cannot be loaded, the Live page shows a banner with the exact
reason and the feed continues to play without detection. Nothing is faked: an
empty result means the model really found nothing.

---

## 5. Using the application

### Dashboard
Four KPI cards (active cameras, people, vehicles, events today), a live status
panel, the detection-model panel and the eight most recent events. All values
come from the running pipeline or the database.

### Live Cameras
* Source selector: **video file**, **webcam**, **IP camera (RTSP)** or
  **EarthCam (live)**.
* Connect / Disconnect, plus transport controls (play, pause, stop, seek).
* Snapshot and Record buttons — both explicit, neither runs automatically.
* Right-hand panel: every current object with class, confidence, tracking ID and
  estimated movement direction.
* Bottom timeline: event chips, newest first. Clicking one opens the stored
  event.
* The footer of the detection panel states which tracker is active.

### Recordings
Lists every clip and snapshot this application has written, with size and
timestamp. Files can be opened, revealed in Explorer, or deleted (only inside
`data/snapshots` and `data/recordings`).

### Events
Searchable history: free-text search, event-type filter, time-range filter. The
type filter also offers **Warnings and alarms** and **Alarms only** aggregates;
alarm rows are coloured red, warnings amber. Snapshots open in the default image
viewer. Selected rows can be deleted, and the whole history can be cleared — both
behind a confirmation dialog.

### Analytics
Range selector (24 h / 7 d / 30 d / all). Cards for events, region alerts,
average processed FPS and measured uptime; a class distribution chart; an event
frequency chart; per-camera uptime; recent events. Empty states are shown when
there is no data — no synthetic numbers.

### Settings
Detection thresholds, inference size, device, enabled classes, event rules,
cooldowns, loitering threshold, evidence snapshots, retention limit, region
editor and privacy notes.

---

## 6. Camera sources

### EarthCam live street cameras
The **EarthCam (live)** source plays public street cameras as real HLS video —
not stills. Seven cameras in five countries are listed: New York (Times Square),
New Orleans (Bourbon Street), Chicago (Chicago River), London (Abbey Road),
Dublin (O'Connell Street), Amsterdam (Dam Square) and Cape Town.

How it works, because it is not obvious:

1. EarthCam has no API, but every camera page carries its player configuration
   in the HTML (`html5_streamingdomain` + `html5_streampath`). That pair gives a
   playlist URL with a **session token**, which is why it is resolved on every
   connection and never written to `config.json`.
2. The media host rejects requests without a `Referer: https://www.earthcam.com/`
   header (HTTP 403). OpenCV's FFmpeg backend ignores the header option, so the
   playlist is served through a small **loopback relay** (`cameras/earthcam.py`)
   that adds the header and rewrites child playlists and segments back through
   itself. Nothing leaves the machine except the requests to EarthCam.
3. `cv2.VideoCapture` then opens `http://127.0.0.1:<port>/master.m3u8`, so the
   rest of the pipeline — tracking, events, recording — is unchanged.

Notes and limits:

* Streams measured at 1280×720 to 1920×1080, 15–30 fps. Opening takes 5–11 s
  because the token and the first segments have to be fetched.
* HLS arrives one segment at a time, so frames come in bursts. Delivery is paced
  to the stream's own frame rate; without that the pipeline drained a burst
  instantly, starved for the rest of the segment, and processed about 1 frame per
  second. Paced, the same stream processes at ~14 fps.
* Reading is bounded: if a segment never arrives, the capture thread gives up
  after 15 s and reconnects instead of freezing the feed. Disconnecting returns
  in under a second.
* The camera list is curated, not discovered: entries were opened and decoded
  before being listed. Cameras that advertise a stream but never produce a frame
  (Las Vegas, Nashville, San Francisco and Seattle at the time of writing) are
  deliberately absent, and the many EarthCam pages that return 404 are not
  guessed at.
* EarthCam can move or retire a camera at any time. When that happens the Live
  page shows the failure with the camera name, and another camera can be picked.
* This is EarthCam's public web output, intended for viewing. Check their terms
  before using it for anything beyond personal viewing.

### Video files
MP4, AVI, MKV, MOV, WMV, MPEG, TS and WEBM are offered in the file dialog, but
what actually plays depends on the FFmpeg build bundled with your OpenCV wheel.
H.264 MP4 is the safest choice. Playback is paced to the file's own frame rate,
so a 60-second clip takes 60 seconds.

### Webcams
**Rescan devices** probes indices 0–4 using DirectShow (falling back to MSMF on
Windows). If no camera opens:

1. close other applications that may hold the device (Teams, Zoom, OBS);
2. check *Windows Settings → Privacy → Camera* and allow desktop apps;
3. try another index.

### IP cameras (RTSP)
Enter the URL, for example:

```
rtsp://192.168.1.50:554/stream1
```

Credentials are entered in separate fields, injected into the URL only at open
time, and stored encrypted with the Windows DPAPI. Passwords never appear in
logs, tables or error dialogs — every URL is masked before it is logged.

**Test** opens the stream, reads one frame and reports the resolution, frame
rate and open time. Failures include a reachability check and a checklist rather
than a bare OpenCV error.

**Discover** sends a real WS-Discovery probe over UDP multicast. It reports the
devices that answer, but discovery does **not** yield a playable URL: that needs
authenticated ONVIF media calls. Install the optional package if you want them
resolved automatically:

```bat
.venv\Scripts\python.exe -m pip install onvif-zeep
```

Otherwise copy the RTSP URL from the camera's web interface — it is usually on
the network or streaming page.

---

## 7. Tracking, regions and events

### Tracking
ByteTrack is used through `ultralytics`' supported `model.track()` interface with
the bundled `bytetrack.yaml`. If that path fails on a particular installation,
the detector switches to a small built-in IoU tracker and the interface says
`fallback-iou` instead of `bytetrack`.

Tracking IDs are temporary counters. They are not identities, they are not
matched across sessions, and they reset whenever the source changes. A person
who leaves the frame and returns will normally receive a new ID.

### Regions
**Settings → Edit regions…** opens a polygon editor. Left-click adds a point,
right-click removes the last one, double-click (or *Finish*) closes the polygon.
Points are stored normalised (0–1), so they survive a resolution change.

### Event types
| Type | Severity | Trigger |
|---|---|---|
| `person` | info | A person is detected in the frame |
| `vehicle` | info | A bicycle, car, motorcycle, bus, truck, train, boat or plane is detected |
| `intrusion` | warning | A tracked object enters a configured polygon |
| `loitering` | warning | A tracked object stays inside a polygon longer than the threshold |
| `hazard` | warning | A class on the hazard list is detected |
| `armed` | **alarm** | A hazard class is detected next to a person |
| `altercation` | **alarm** | Two people overlap and move together for a sustained period |

Region events are stored with a different `event_type` and show the region name,
so they are never confused with a plain detection.

A cooldown (default 15 s) is applied per rule and per track. Without it a person
standing in view would write an event for every processed frame.

### Safety alerts

There are two tiers here, and it matters which is which.

**1. Violence model — real inference.** `models/yolo_small_weights.pt` is a
separate YOLOv8 checkpoint with two classes: `non_violence` and `violence`. It
runs as a **second detector alongside the main model**, every N frames (default
2), and a `violence` box raises an alarm. It is configured in
**Settings → Safety alerts**: on/off, weights file, confidence, stride and
cooldown. If the file is missing or fails to load, the application logs it, shows
`safety_state` on the dashboard, and keeps running with the main model only.

The model classifies a *scene*, not an action. It was trained on fight/non-fight
imagery, so it reacts to bodies in violent configurations. It can miss a fight
that looks like rough play, and it can fire on crowded or chaotic scenes. Running
it costs a second inference pass — that is what the stride setting is for.

**2. Heuristics — no model involved.** `hazard`, `armed` and `altercation` are
geometric rules over the main detector's output:

* **`armed`** — a box whose class is on the hazard list (`knife`,
  `baseball bat`, `scissors` by default) has its centre within roughly a quarter
  of the person's height of a person's box. If no person is nearby the object is
  ignored, which keeps a knife block in a kitchen from alarming.
* **`altercation`** — two person boxes overlap by at least 22 % and at least one
  is moving, continuously for 1.2 s.

Limits of the heuristic tier:

* **There is no firearm detection.** COCO has no `gun` or `rifle` class. To cover
  firearms you need a checkpoint trained on them; drop the `.pt` into `models/`,
  select it as the main model, and add its class names to the hazard list.
* **Fighting is only classified by the violence model**, not by the heuristics.
  Two people hugging, dancing or queueing closely will trip `altercation`.
* **Small objects are missed.** A knife is a handful of pixels at 20 m.

Treat every alarm as "something worth looking at", never as a fact. All rules are
configurable in **Settings → Safety alerts**, and the whole tier can be switched
off there.

---

## 8. Performance tuning

The dominant cost is inference. In rough order of impact:

| Change | Effect |
|---|---|
| `imgsz` 640 → 416 | Large speed-up, small accuracy loss |
| `imgsz` 640 → 800/1280 | Slower, better on distant objects |
| `yolov8n` → `yolov8s` | Better accuracy, roughly 3× slower on CPU |
| Narrow the enabled class list | Slight speed-up, much less visual noise |
| `cuda:0` device | 10–50× faster if an NVIDIA GPU is present |

Measured throughput is displayed live in the transport bar as
`processed fps · inference ms · capture fps`. The application does not claim a
guaranteed frame rate — it reports what it actually achieves on your hardware.

When inference is slower than the source, capture keeps running in real time and
older frames are dropped rather than queued. Memory therefore stays flat no
matter how long the session runs.

---

## 9. Data and privacy

```
data/
  cctv.db            SQLite database (events, sessions)
  logs/app.log       rotating log, credentials masked
  snapshots/         evidence JPEGs (only when enabled or requested)
  recordings/        MP4 clips (only when you press Record)
models/              downloaded .pt weights
```

* Processing is local. The only network traffic is the one-time weight download
  and your own camera streams.
* No facial recognition, no identity matching, no biometric templates.
* Nothing is recorded silently: snapshots and recordings require an explicit
  action or an explicit setting.
* Camera passwords are encrypted with DPAPI (per Windows user, per machine) and
  masked in every log line and error message.
* Object detection produces false positives — poor light, reflections, rain and
  unusual angles all cause them. Treat events as hints, not proof.

---

## 10. Project layout

```
main.py                  entry point
requirements.txt         pinned dependency ranges
setup.bat / run.bat      Windows setup and launcher
config/                  defaults + JSON configuration manager
  defaults.py            COCO classes, colours, default config
  settings.py            thread-safe dot-path config access
detection/               YOLO loading, inference, result parsing
tracking/                IoU fallback tracker, trail and direction estimation
cameras/                 sources, capture thread, inference thread, pipeline
events/                  polygon regions, rules, event engine
analytics/               aggregates over stored events and sessions
database/                SQLite schema and repositories
ui/                      theme, icons, widgets, pages, dialogs, main window
utils/                   paths, logging, DPAPI secrets, imaging, buffers
tests/                   pytest suite (no Qt/OpenCV/torch required)
```

Threading model:

```
CaptureThread ──frame──▶ LatestBuffer ──▶ InferenceThread ──QImage──▶ LatestBuffer
      │                                          │
      └── position/stats ──▶ signals             └── events ──▶ SQLite + signals
                                                                   │
                                              MainWindow QTimer ───┘ (pulls newest frame)
```

Two buffers, each holding exactly one frame. A slow consumer drops frames
instead of growing a queue.

---

## 11. Tests

```bat
.venv\Scripts\python.exe -m pytest -q
```

The suite covers configuration merging, the SQLite repositories, polygon
geometry, the event engine (cooldowns, region entry, loitering, presence reset),
the IoU tracker, trail direction estimation and credential masking. It does not
require Qt, OpenCV or torch, so it runs in a bare Python environment.

---

## 12. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `module 'torch._C' has no attribute '_has_gds'` or `module functions cannot set METH_CLASS or METH_STATIC` | You are running a different Python than the project environment, and its PyTorch is broken. Use `run.bat` — or just `python main.py`, which now relaunches itself under `.venv` |
| `Could not parse stylesheet of object QFrame…` | Cosmetic warning from a Qt build that rejects a non-standard QSS property. It does not affect behaviour |
| `torch.cuda.is_available()` is False | A CPU-only torch wheel is installed. Reinstall from the cu128 index (see §2) |
| `CUDA out of memory` | Lower `imgsz`, turn off the violence model, or use `yolov8n` |
| Dashboard device row says `cpu` although you set `cuda:0` | CUDA could not initialise; the detector fell back. Check the driver with `nvidia-smi` |
| Dashboard shows `Safety model: error` | The violence checkpoint failed to load. Confirm `models/yolo_small_weights.pt` exists and that its class list in Settings matches the model |
| `setup.bat` says no supported Python | Install 3.11/3.12 64-bit and tick *Add python.exe to PATH* |
| `pip` fails behind a proxy | Set `HTTPS_PROXY`, or install from a local wheel mirror |
| A second copy reports "already running" and exits | By design. Two copies load two CUDA models each, and on a small GPU the second one blocks inside CUDA initialisation with no error - the window just stops responding. Close the open window first |
| `ImportError: DLL load failed` for cv2/torch | Usually a missing VC++ redistributable, or a 32-bit Python |
| Window opens but the model banner shows an error | No internet for the first download. Download the `.pt` manually into `models/` |
| "No webcam could be opened" | Device in use, blocked by Windows privacy settings, or wrong index |
| RTSP test fails immediately | Wrong host/port, camera offline, or the stream path is wrong (`/stream1`, `/Streaming/Channels/101`) |
| RTSP test fails after a long pause | Firewall blocking TCP 554, or the camera allows only one client |
| Video file will not open | Codec missing from the OpenCV build — re-encode to H.264 MP4 |
| Interface stutters during detection | Lower `imgsz`, disable unused classes, or reduce `torch_threads` |
| Tracking IDs change constantly | ByteTrack lost the object (occlusion). Check the panel footer to see which tracker is active |
| No events appear | Check the rules in Settings, and note that the cooldown suppresses repeats |
| Events exist but no snapshots | Enable *Save an evidence snapshot for every event* — it only applies to future events |

Log file: `data\logs\app.log`.

---

## 13. Verification status

Executed on Windows with Python 3.11.9, PySide6 6.8.3, OpenCV 4.10.0,
torch 2.15.0+cpu and ultralytics 8.4.192:

| Check | Result |
|---|---|
| `pytest` suite | **110 passed** |
| Window construction, all six pages, theme, drawn icons | Passed (offscreen Qt) |
| `main.py` startup | Reached "Interface ready"; model preloaded in the background |
| Automatic weight download | `yolov8n.pt` (6.3 MB) fetched into `models/` |
| Real detection | bus + 3 people on a test frame, confidence 0.83–0.87 |
| ByteTrack | IDs stable across consecutive frames (`bytetrack` reported) |
| File pipeline end to end | 35 frames at 7.5 fps, 14 events written, snapshots saved |
| Mid-stream stop and restart | Threads stopped, sessions closed, restart clean |
| Session accounting | Per-session frames and fps recorded correctly |
| EarthCam live video | 7 cameras in 5 countries opened and decoded: 1280×720 – 1920×1080 |
| EarthCam referer gate | Playlist returns 403 without `Referer`, 200 with it; relay makes it play |
| EarthCam through the pipeline | `open_capture` → 1280×720, 15 fps, frames decoded, window builds offscreen |

Not verified, and why:

* **A physical webcam** — none attached to the build machine. The enumeration and
  open code paths are exercised only through their error branches.
* **A real RTSP camera or ONVIF discovery** — no hardware on the network. URL
  masking, credential handling and failure diagnostics are unit tested; the
  actual stream negotiation is not.
* **Visual appearance on a real screen** — the GUI was driven offscreen, so
  layout, spacing and colours were never seen rendered. They are unverified
  aesthetically, though every widget constructs without error.
* **GPU inference** — no CUDA device available; `device` falls back to CPU and
  says so.

Re-run the suite at any time with:

```bat
.venv\Scripts\python.exe -m pytest -q
```
