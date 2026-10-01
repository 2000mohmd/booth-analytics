"""Probes an ONVIF-compatible NVR/camera for its media profiles and RTSP URIs, so the real
values (not device indices) can be dropped into configs/booth.yaml's `cameras[].source`.

Usage:
    python -m scripts.discover_cameras --host 192.168.1.50 --user admin --password 'secret'

    # or via env vars, to avoid the password showing up in shell history:
    ONVIF_USER=admin ONVIF_PASSWORD=secret python -m scripts.discover_cameras --host 192.168.1.50

Optionally pass --port (default 80) and --wsdl-dir if onvif-zeep's bundled WSDL files aren't
found automatically. Run with --ws-discover first if you don't know the NVR's IP yet.
"""
import argparse
import os
import sys

from onvif import ONVIFCamera


def _default_wsdl_dir() -> str | None:
    """onvif-zeep's wheel installs WSDL files under site-packages/wsdl, not
    onvif/wsdl where the library looks by default - locate it so callers don't
    have to pass --wsdl-dir by hand every time."""
    import onvif

    candidate = os.path.join(os.path.dirname(os.path.dirname(onvif.__file__)), "wsdl")
    return candidate if os.path.isdir(candidate) else None


def discover_on_lan():
    from wsdiscovery.discovery import ThreadedWSDiscovery as WSDiscovery

    wsd = WSDiscovery()
    wsd.start()
    try:
        services = wsd.searchServices()
        for service in services:
            print(service.getEPR(), "->", [str(x) for x in service.getXAddrs()])
    finally:
        wsd.stop()


def dump_profiles(host: str, port: int, user: str, password: str, wsdl_dir: str | None):
    cam = ONVIFCamera(host, port, user, password, wsdl_dir=wsdl_dir)
    media = cam.create_media_service()
    profiles = media.GetProfiles()

    if not profiles:
        print("No media profiles returned - check credentials / ONVIF is enabled on the device.")
        return

    for profile in profiles:
        stream_setup = {
            "Stream": "RTP-Unicast",
            "Transport": {"Protocol": "RTSP"},
        }
        uri = media.GetStreamUri({"StreamSetup": stream_setup, "ProfileToken": profile.token})
        video = getattr(profile, "VideoEncoderConfiguration", None)
        resolution = getattr(video, "Resolution", None) if video else None
        print(f"profile: {profile.Name!r} (token={profile.token})")
        if resolution:
            print(f"  resolution: {resolution.Width}x{resolution.Height}")
        print(f"  rtsp uri:   {uri.Uri}")
        print()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", help="NVR/camera IP address")
    parser.add_argument("--port", type=int, default=80, help="ONVIF port (default 80)")
    parser.add_argument("--user", default=os.environ.get("ONVIF_USER"))
    parser.add_argument("--password", default=os.environ.get("ONVIF_PASSWORD"))
    parser.add_argument("--wsdl-dir", default=_default_wsdl_dir())
    parser.add_argument("--ws-discover", action="store_true",
                         help="broadcast WS-Discovery on the LAN to find ONVIF device addresses first")
    args = parser.parse_args()

    if args.ws_discover:
        discover_on_lan()
        return

    if not args.host or not args.user or not args.password:
        parser.error("--host, --user and --password (or ONVIF_USER/ONVIF_PASSWORD) are required "
                     "unless --ws-discover is passed")

    dump_profiles(args.host, args.port, args.user, args.password, args.wsdl_dir)


if __name__ == "__main__":
    sys.exit(main())
