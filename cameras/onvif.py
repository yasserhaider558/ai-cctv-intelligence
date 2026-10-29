"""ONVIF discovery (WS-Discovery) with an optional media-profile lookup.

Scope of what is implemented here, stated plainly:

* :func:`discover` sends a real WS-Discovery ``Probe`` over UDP multicast and
  parses the ``ProbeMatch`` responses. That part works without any extra
  dependency and returns the device service address.
* Turning that service address into a playable RTSP URL requires authenticated
  SOAP calls. Those are implemented with the optional ``onvif-zeep`` package in
  :func:`resolve_stream_uri`. If it is not installed the function says so and
  the user types the stream URL manually.

Discovery is a convenience, never an assumption: plenty of cameras answer
WS-Discovery and still refuse anonymous media access, and many expose several
profiles with different resolutions.
"""

from __future__ import annotations

import re
import socket
import uuid
from dataclasses import dataclass, field

from utils.logging_setup import get_logger
from utils.secrets import mask_url

log = get_logger(__name__)

MULTICAST_ADDRESS = "239.255.255.250"
MULTICAST_PORT = 3702

_PROBE_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope"
            xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing"
            xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
            xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
  <e:Header>
    <w:MessageID>uuid:{message_id}</w:MessageID>
    <w:To e:mustUnderstand="true">urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>
    <w:Action e:mustUnderstand="true">http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>
  </e:Header>
  <e:Body>
    <d:Probe>
      <d:Types>dn:NetworkVideoTransmitter</d:Types>
    </d:Probe>
  </e:Body>
</e:Envelope>"""

_XADDRS = re.compile(r"<[^>]*XAddrs[^>]*>(.*?)</[^>]*XAddrs>", re.IGNORECASE | re.DOTALL)
_SCOPES = re.compile(r"<[^>]*Scopes[^>]*>(.*?)</[^>]*Scopes>", re.IGNORECASE | re.DOTALL)
_ENDPOINT = re.compile(r"<[^>]*Address[^>]*>(urn:uuid:[^<]+)</[^>]*Address>", re.IGNORECASE)


@dataclass
class OnvifDevice:
    endpoint: str = ""
    addresses: list[str] = field(default_factory=list)
    scopes: list[str] = field(default_factory=list)

    @property
    def service_url(self) -> str:
        return self.addresses[0] if self.addresses else ""

    @property
    def name(self) -> str:
        for scope in self.scopes:
            if "/name/" in scope:
                return scope.rsplit("/", 1)[-1]
        if self.addresses:
            return mask_url(self.addresses[0])
        return self.endpoint or "ONVIF device"

    @property
    def hardware(self) -> str:
        for scope in self.scopes:
            if "/hardware/" in scope:
                return scope.rsplit("/", 1)[-1]
        return ""


def discover(timeout_s: float = 3.0, max_devices: int = 12) -> list[OnvifDevice]:
    """Send a WS-Discovery probe and collect the answers."""
    message_id = str(uuid.uuid4())
    payload = _PROBE_TEMPLATE.format(message_id=message_id).encode("utf-8")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(0.4)
    devices: dict[str, OnvifDevice] = {}
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.sendto(payload, (MULTICAST_ADDRESS, MULTICAST_PORT))
        import time

        deadline = time.monotonic() + max(0.5, float(timeout_s))
        while time.monotonic() < deadline and len(devices) < max_devices:
            try:
                data, _addr = sock.recvfrom(65535)
            except socket.timeout:
                continue
            text = data.decode("utf-8", errors="ignore")
            if "ProbeMatch" not in text and "XAddrs" not in text:
                continue
            device = _parse_response(text)
            if device is None:
                continue
            key = device.endpoint or device.service_url
            if key and key not in devices:
                devices[key] = device
    except OSError as exc:
        log.info("ONVIF discovery unavailable on this network: %s", exc)
        return []
    finally:
        try:
            sock.close()
        except Exception:
            pass
    log.info("ONVIF discovery found %d device(s)", len(devices))
    return list(devices.values())


def _parse_response(text: str) -> OnvifDevice | None:
    addresses: list[str] = []
    match = _XADDRS.search(text)
    if match:
        addresses = [part.strip() for part in match.group(1).split() if part.strip()]
    scopes: list[str] = []
    scope_match = _SCOPES.search(text)
    if scope_match:
        scopes = [part.strip() for part in scope_match.group(1).split() if part.strip()]
    endpoint_match = _ENDPOINT.search(text)
    endpoint = endpoint_match.group(1) if endpoint_match else ""
    if not addresses and not endpoint:
        return None
    return OnvifDevice(endpoint=endpoint, addresses=addresses, scopes=scopes)


def resolve_stream_uri(
    service_url: str, username: str, password: str
) -> tuple[str | None, str]:
    """Ask the camera for its media profile URI via onvif-zeep.

    Returns ``(uri, message)``. ``uri`` is ``None`` when it could not be
    resolved; ``message`` always explains what happened.
    """
    if not service_url:
        return None, "No ONVIF service address was discovered."
    try:
        from onvif import ONVIFCamera  # type: ignore
    except Exception:
        return None, (
            "Automatic stream URL resolution needs the optional 'onvif-zeep' "
            "package, which is not installed.\n\n"
            "Install it with:\n"
            "    .venv\\Scripts\\python.exe -m pip install onvif-zeep\n\n"
            "Or simply paste the RTSP URL from the camera's web interface."
        )
    try:
        from urllib.parse import urlparse

        parsed = urlparse(service_url)
        host = parsed.hostname or ""
        port = parsed.port or 80
        camera = ONVIFCamera(host, port, username, password)
        media = camera.create_media_service()
        profiles = media.GetProfiles()
        if not profiles:
            return None, "The camera reported no media profiles."
        token = profiles[0].token
        request = media.create_type("GetStreamUri")
        request.ProfileToken = token
        request.StreamSetup = {
            "Stream": "RTP-Unicast",
            "Transport": {"Protocol": "RTSP"},
        }
        response = media.GetStreamUri(request)
        uri = getattr(response, "Uri", None)
        if not uri:
            return None, "The camera returned an empty stream URI."
        return uri, f"Resolved stream URI from profile '{token}'."
    except Exception as exc:
        return None, (
            "The ONVIF request failed. This usually means wrong credentials, "
            "disabled ONVIF support on the camera, or a different ONVIF port.\n\n"
            f"Technical detail: {exc}"
        )
