"""
FaxWatcher - watches a folder for PDFs named <10digitnumber>.pdf and sends
them through a FusionPBX fax server using an API key (no interactive login).

Everything lives in the user's Documents\\FaxSend folder:
    config.ini, faxwatcher.log, Outbox\\, Sent\\, Failed\\, Logs\\log.txt
config.ini [server] method = api (REST API, default) or web (web fax page login).

Windows deployment: unzip FaxSend.exe + a filled-in config.ini, double-click
FaxSend.exe. It installs itself to Program Files and runs as a hidden SYSTEM
scheduled task at startup. Double-clicking again shows the status.

Command line:
    (no arguments)  Windows: install, or show status if already installed
    --install       install / update the background task (needs admin)
    --uninstall     remove the background task
    --status        show whether the background task is running
    --run           run the folder watcher in this window
    --test-api      check the API key and fax server without sending anything
    --base-dir DIR  use DIR instead of <Documents>\\FaxSend
"""
import base64
import configparser
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from xml.sax.saxutils import escape as xml_escape
from html.parser import HTMLParser
from logging.handlers import RotatingFileHandler

from urllib.parse import urljoin

import requests

def documents_dir():
    """The current user's Documents folder. On Windows this asks the OS, so it
    follows OneDrive / folder redirection instead of assuming C:\\Users\\<name>."""
    if os.name == "nt":
        try:
            import ctypes
            # FOLDERID_Documents {FDD39AD0-238F-46AF-ADB4-6C85480369C7}
            guid = (ctypes.c_byte * 16)(*bytes.fromhex("d09ad3fd8f23af46adb46c85480369c7"))
            path_ptr = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(guid, 0, None, ctypes.byref(path_ptr)) == 0:
                path = path_ptr.value
                ctypes.windll.ole32.CoTaskMemFree(path_ptr)
                if path:
                    return path
        except Exception:
            pass
    return os.path.join(os.path.expanduser("~"), "Documents")


FROZEN = getattr(sys, "frozen", False)
APP_DIR = os.path.dirname(os.path.abspath(sys.executable if FROZEN else __file__))
TASK_NAME = "FaxSend"
BASE_DIR = CONFIG_PATH = None


def set_base_dir(path):
    """Where config.ini, logs and the fax folders live. The background task runs as
    SYSTEM, so it is always given the installing user's folder with --base-dir."""
    global BASE_DIR, CONFIG_PATH
    BASE_DIR = os.path.abspath(path)
    CONFIG_PATH = os.path.join(BASE_DIR, "config.ini")


set_base_dir(os.path.join(documents_dir(), "FaxSend"))
NAME_RE = re.compile(r"^(\d{10})(?:[ _-].*)?\.pdf$", re.IGNORECASE)

DEFAULT_CONFIG = """[server]
; Base URL of the customer's FusionPBX, no trailing slash
url = https://pbx.example.com
; api = FusionPBX REST API (needs the API app on the server)
; web = log in to the web fax page (works without the API app)
method = api
; API key of the FusionPBX user (Accounts > User Manager > Edit > API Key)
api_key = PUT_API_KEY_HERE
; UUID of the fax server (the id= value in the URL when you edit it in Fax Server)
fax_uuid = PUT_FAX_UUID_HERE
; api method only: the FusionPBX server's hostname (run "hostname" on the server)
hostname =
verify_ssl = true
; Optional. api: read from the fax server automatically. web: only if login fails
domain_uuid =
domain_name =

[folders]
; Set automatically on first run to <user's Documents>\\FaxSend\\...
; Leave a value blank to go back to the automatic location.
watch = @WATCH@
sent = @SENT@
failed = @FAILED@
; Fax history: every sent/failed fax is appended to log.txt in this folder
logs = @LOGS@

[fax]
header =
sender =
; normal, fine or superfine
resolution = fine
; api method: tif = convert the PDF to a fax TIFF on this PC (needed by FreeSWITCH)
;             pdf = upload the PDF as-is (only if the server converts PDFs itself)
send_format = tif
; letter, legal or a4
page_size = letter
; Leave blank to use the fax server's own caller ID
caller_id_name =
caller_id_number =
; Prefix added to the 10 digit number. Usually leave blank: FusionPBX already
; applies the fax server's own prefix setting.
dial_prefix =
; Optional cover page (web method only). Leave both blank for no cover page.
cover_subject =
cover_message =
; api method only: email address for the fax result notification (optional)
email =

[options]
poll_seconds = 5
; seconds the file size must be unchanged before sending (copy still in progress)
settle_seconds = 3
retries = 2
"""


class FormParser(HTMLParser):
    """Collects hidden inputs (CSRF token) from the fax_send form."""

    def __init__(self):
        super().__init__()
        self.hidden = {}
        self.forms = []  # [{"action": str, "hidden": {...}}]

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            self.forms.append({"action": a.get("action") or "", "hidden": {}})
        elif tag == "input" and a.get("type") == "hidden" and a.get("name"):
            self.hidden[a["name"]] = a.get("value", "")
            if self.forms:
                self.forms[-1]["hidden"][a["name"]] = a.get("value", "")


FAX_WIDTH = 1728                                   # standard fax line: 8.47in at 204 dpi
FAX_YDPI = {"normal": 98, "fine": 196, "superfine": 392}


def _set_min_is_white(data):
    """Set PhotometricInterpretation = 0 (MinIsWhite) in every page of a TIFF."""
    import struct
    bo = "<" if data[:2] == b"II" else ">"
    buf = bytearray(data)
    off, pages = struct.unpack_from(bo + "I", buf, 4)[0], 0
    while off:
        count = struct.unpack_from(bo + "H", buf, off)[0]
        for i in range(count):
            entry = off + 2 + 12 * i
            tag, typ = struct.unpack_from(bo + "HH", buf, entry)
            if tag == 262:
                struct.pack_into(bo + ("H" if typ == 3 else "I"), buf, entry + 8, 0)
                pages += 1
        off = struct.unpack_from(bo + "I", buf, off + 2 + 12 * count)[0]
    if not pages:
        raise RuntimeError("TIFF conversion failed: no photometric tag written")
    return bytes(buf)


def pdf_to_fax_tiff(path, resolution="fine"):
    """Render a PDF to a multi-page TIFF-F (G4, 1728 px wide, 204 x 98/196/392 dpi,
    MinIsWhite) - the same format FusionPBX makes with Ghostscript - so FreeSWITCH
    can send it. Returns (tiff_bytes, page_count)."""
    import io
    import pypdfium2 as pdfium
    from PIL import Image, ImageChops
    ydpi = FAX_YDPI.get(resolution, 196)
    pages = []
    pdf = pdfium.PdfDocument(path)
    try:
        for i in range(len(pdf)):
            page = pdf[i]
            w, h = page.get_size()                       # points
            rotation = 90 if w > h else 0                # fax landscape pages in portrait
            if rotation:
                w, h = h, w
            target_h = max(1, round(h * FAX_WIDTH / w * ydpi / 204))
            scale = FAX_WIDTH / w * max(1.0, ydpi / 204)
            img = page.render(scale=scale, rotation=rotation, grayscale=True).to_pil()
            page.close()
            img = img.convert("L").resize((FAX_WIDTH, target_h), Image.LANCZOS)
            # Same threshold FusionPBX uses with Ghostscript: lighter than 75% grey is white
            bw = img.point(lambda p: 255 if p > 191 else 0).convert("1", dither=Image.Dither.NONE)
            # Inverted so white is stored as 0 bits (fax convention); tag fixed below
            pages.append(ImageChops.invert(bw))
    finally:
        pdf.close()
    if not pages:
        raise RuntimeError("the PDF has no pages")
    out = io.BytesIO()
    pages[0].save(out, format="TIFF", compression="group4", dpi=(204, ydpi),
                  save_all=True, append_images=pages[1:])
    return _set_min_is_white(out.getvalue()), len(pages)


class SendUnconfirmed(Exception):
    """The server may have accepted the fax, but we could not confirm it.
    Never retried, so a fax is not sent twice."""


class ServerUnreachable(Exception):
    """Could not connect at all (network or PBX down). The fax stays in the
    Outbox and is sent automatically when the server is reachable again."""


class ApiFaxClient:
    """Queues faxes through the FusionPBX REST API (/app/api/7/fax_queue)."""

    REDIRECTS = (301, 302, 303, 307, 308)

    def __init__(self, cfg):
        s = cfg["server"]
        self.cfg = cfg
        self.base = s["url"].rstrip("/")
        self.key = s["api_key"].strip()
        self.fax_uuid = s["fax_uuid"].strip()
        self.hostname = s.get("hostname", "").strip()
        self.domain_uuid = s.get("domain_uuid", "").strip()
        self.verify = s.getboolean("verify_ssl", True)
        self.http = requests.Session()
        self.http.headers.update({
            "Authorization": f"Basic {self.key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        })
        self._fax = None

    def _url(self, method, record_uuid=None):
        return f"{self.base}/app/api/7/{method}" + (f"/{record_uuid}" if record_uuid else "")

    def _check(self, r, what):
        if r.status_code in self.REDIRECTS or r.status_code in (401, 403):
            raise RuntimeError(f"API refused {what} (HTTP {r.status_code}) - check api_key "
                               "and the user's permissions")
        if r.status_code == 404:
            raise RuntimeError(f"API not found for {what} (HTTP 404) - is the REST API app "
                               "installed on this server?")
        r.raise_for_status()

    def _get(self, method, record_uuid=None, params=None):
        try:
            r = self.http.get(self._url(method, record_uuid), params=params, verify=self.verify,
                              timeout=30, allow_redirects=False)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            raise ServerUnreachable(f"cannot reach {self.base}: {e}") from e
        self._check(r, method)
        try:
            return r.json()
        except ValueError:
            raise RuntimeError(f"API returned non-JSON for {method}: "
                               + re.sub(r"\s+", " ", r.text)[:200])

    @staticmethod
    def _find(obj, key, value):
        """Find the dict with obj[key] == value anywhere in a JSON response."""
        if isinstance(obj, dict):
            if str(obj.get(key, "")).lower() == value.lower():
                return obj
            obj = list(obj.values())
        if isinstance(obj, list):
            for item in obj:
                found = ApiFaxClient._find(item, key, value)
                if found:
                    return found
        return None

    def fax_server(self):
        """The fax server record: domain_uuid, caller ID, prefix, accountcode."""
        if self._fax is None:
            rec = self._find(self._get("fax", self.fax_uuid), "fax_uuid", self.fax_uuid)
            if not rec:
                raise RuntimeError(f"Fax server {self.fax_uuid} not found through the API - "
                                   "check fax_uuid and the user's fax_view permission")
            self._fax = rec
        return self._fax

    def test(self):
        fax = self.fax_server()
        lines = [
            "OK - API key accepted",
            f"Fax server: {fax.get('fax_name', '')} (extension {fax.get('fax_extension', '')})",
            f"Caller ID:  {fax.get('fax_caller_id_name', '')} {fax.get('fax_caller_id_number', '')}",
            f"Domain:     {self.domain_uuid or fax.get('domain_uuid', '')}",
        ]
        if not self.hostname:
            lines.append("WARNING: hostname is not set in config.ini - sends will fail")
        try:
            self._get("fax_queue", params={"limit": 1})
            lines.append("Fax queue: readable (sends can be confirmed)")
        except Exception as e:
            lines.append(f"WARNING: cannot read the fax queue ({e}) - give the user "
                         "fax_queue_view, or every send will be reported as unconfirmed")
        return "\n".join(lines)

    def send(self, path, number):
        if not self.hostname:
            raise RuntimeError("hostname is not set in config.ini")
        fax = self.fax_server()
        f = self.cfg["fax"]
        queue_uuid = str(uuid.uuid4())
        if f.get("send_format", "tif").strip().lower() == "pdf":
            ext = "pdf"
            with open(path, "rb") as fh:
                data = fh.read()
        else:
            # FreeSWITCH can only transmit TIFF, and the API does not convert PDFs
            ext = "tif"
            try:
                data, page_count = pdf_to_fax_tiff(path, f.get("resolution", "fine"))
            except Exception as e:
                raise RuntimeError(f"could not read the PDF ({e}) - is it damaged or "
                                   "password protected?") from e
            logging.info("Converted %s to fax TIFF (%d pages)", os.path.basename(path), page_count)
        fax_b64 = base64.b64encode(data).decode("ascii")
        record = {
            "fax_queue_uuid": queue_uuid,
            "domain_uuid": self.domain_uuid or fax.get("domain_uuid", ""),
            "fax_uuid": self.fax_uuid,
            "fax_date": "now()",
            "hostname": self.hostname,
            "fax_caller_id_name": f.get("caller_id_name", "") or fax.get("fax_caller_id_name") or "",
            "fax_caller_id_number": f.get("caller_id_number", "") or fax.get("fax_caller_id_number") or "",
            "fax_number": f.get("dial_prefix", "") + number,
            "fax_prefix": fax.get("fax_prefix") or "",
            "fax_email_address": f.get("email", ""),
            "fax_filename": f"{queue_uuid}.{ext}",
            "fax_base64": fax_b64,
            "fax_status": "waiting",
            "fax_retry_count": "0",
            "fax_accountcode": fax.get("accountcode") or "",
        }
        try:
            r = self.http.post(self._url("fax_queue"), data=json.dumps({"fax_queue": [record]}),
                               verify=self.verify, timeout=120, allow_redirects=False)
        except requests.exceptions.ReadTimeout as e:
            # The upload went out but no answer came back: it may have been queued
            raise SendUnconfirmed(f"no reply from the server ({e}). Check the fax queue "
                                  "before resending") from e
        except requests.exceptions.ConnectionError as e:
            raise ServerUnreachable(f"cannot reach {self.base}: {e}") from e
        self._check(r, "fax_queue")  # failed before the fax was accepted: safe to retry
        reply = re.sub(r"\s+", " ", r.text)[:300]

        # From here the server may have queued the fax: never retry (no duplicate faxes)
        try:
            rec = self._find(self._get("fax_queue", queue_uuid), "fax_queue_uuid", queue_uuid)
        except Exception as e:
            raise SendUnconfirmed(f"posted, but could not confirm it is queued ({e}). "
                                  "Check the fax queue before resending")
        if not rec:
            raise SendUnconfirmed(f"posted, but it is not in the fax queue. Server replied: {reply}")
        logging.info("Queued %s as %s (status %s)", os.path.basename(path), queue_uuid,
                     rec.get("fax_status"))
        return queue_uuid


class FaxClient:
    def __init__(self, cfg):
        s = cfg["server"]
        self.base = s["url"].rstrip("/")
        self.key = s["api_key"].strip()
        self.fax_uuid = s["fax_uuid"].strip()
        self.verify = s.getboolean("verify_ssl", True)
        self.cfg = cfg
        self.http = requests.Session()
        self.page = f"{self.base}/app/fax/fax_send.php"

    def _login(self):
        """Log in like the web login page does, using the API key instead of a password.
        FusionPBX requires the login form's CSRF token even for key logins."""
        self.http = requests.Session()
        r = self.http.get(f"{self.base}/login.php", verify=self.verify, timeout=30)
        r.raise_for_status()
        p = FormParser()
        p.feed(r.text)
        form = next((f for f in p.forms if f["hidden"]), p.forms[0] if p.forms else None)
        if not form:
            raise RuntimeError(f"No login form found at {r.url}")
        action = urljoin(r.url, form["action"]) if form["action"] else r.url
        data = dict(form["hidden"])
        data["key"] = self.key
        domain = self.cfg["server"].get("domain_name", "").strip()
        if domain:
            data["domain_name"] = domain
        logging.info("Login form at %s: action=%s forms=%d fields=%s",
                     r.url, action, len(p.forms), [k[:8] + "…" if len(k) > 20 else k for k in data])
        pr = self.http.post(action, data=data, verify=self.verify, timeout=30)
        logging.info("Login POST -> %s (history: %s)", pr.url,
                     [(h.status_code, h.headers.get("Location")) for h in pr.history])

    def _get_form(self):
        return self.http.get(self.page, params={"id": self.fax_uuid},
                             verify=self.verify, timeout=30, allow_redirects=False)

    @staticmethod
    def _needs_login(r):
        # FusionPBX either redirects to the login page or renders it in place (HTTP 200)
        return (r.status_code in (301, 302, 303, 307, 308)
                or re.search(r"""name=['"]username['"]""", r.text) is not None)

    def _form_tokens(self):
        r = self._get_form()
        if self._needs_login(r):
            self._login()
            r = self._get_form()
        if self._needs_login(r):
            where = r.headers.get("Location") or "the login page"
            raise RuntimeError(f"Not authenticated: server sent {where} after login "
                               "(API key rejected, or wrong domain_name)")
        r.raise_for_status()
        if "access denied" in r.text.lower()[:200]:
            raise RuntimeError("Logged in, but access denied: user lacks fax_send "
                               "permission or is not assigned to this fax server")
        if "fax_files" not in r.text:
            with open(os.path.join(BASE_DIR, "debug_page.html"), "w", encoding="utf-8") as fh:
                fh.write(r.text)
            body = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", r.text)
            snippet = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body)).strip()[:600]
            raise RuntimeError(f"Logged in, but {r.url} is not the fax send form "
                               f"(no upload field). Page text: {snippet} "
                               "(full page saved to debug_page.html)")
        p = FormParser()
        p.feed(r.text)
        return p.hidden

    def test(self):
        tokens = self._form_tokens()
        return f"OK - web login works, reached the fax form ({len(tokens)} hidden fields)"

    def send(self, path, number):
        f = self.cfg["fax"]
        tokens = self._form_tokens()
        data = dict(tokens)
        data.update({
            "id": self.fax_uuid,
            "action": "send",
            "fax_numbers[]": f.get("dial_prefix", "") + number,
            "fax_header": f.get("header", ""),
            "fax_sender": f.get("sender", ""),
            "fax_recipient": number,
            "fax_resolution": f.get("resolution", "fine"),
            "fax_page_size": f.get("page_size", "letter"),
            # Empty subject/message/footer = no cover page is generated
            "fax_subject": f.get("cover_subject", ""),
            "fax_message": f.get("cover_message", ""),
            "fax_footer": "",
        })
        # Only override the server's own caller ID (hidden form defaults) if configured
        if f.get("caller_id_name"):
            data["fax_caller_id_name"] = f["caller_id_name"]
        if f.get("caller_id_number"):
            data["fax_caller_id_number"] = f["caller_id_number"]
        with open(path, "rb") as fh:
            files = {"fax_files[]": (os.path.basename(path), fh, "application/pdf")}
            r = self.http.post(self.page, params={"id": self.fax_uuid},
                               data=data, files=files, verify=self.verify, timeout=120)
        r.raise_for_status()
        # FusionPBX redirects to fax_files.php on success; back to fax_send.php on failure
        if "fax_files.php" not in r.url:
            raise RuntimeError(f"Server did not accept the fax (ended at {r.url})")
        return r.status_code


FOLDER_NAMES = {"watch": "Outbox", "sent": "Sent", "failed": "Failed", "logs": "Logs"}


def default_folders():
    return {key: os.path.join(BASE_DIR, sub) for key, sub in FOLDER_NAMES.items()}


def load_config():
    os.makedirs(BASE_DIR, exist_ok=True)
    bundled = os.path.join(APP_DIR, "config.ini")
    if not os.path.exists(CONFIG_PATH) and os.path.isfile(bundled) \
            and os.path.abspath(bundled) != os.path.abspath(CONFIG_PATH):
        shutil.copyfile(bundled, CONFIG_PATH)
    if not os.path.exists(CONFIG_PATH):
        text = DEFAULT_CONFIG
        for key, path in default_folders().items():
            text = text.replace(f"@{key.upper()}@", path)
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"Created {CONFIG_PATH}")
        print("Edit url, api_key and fax_uuid in config.ini, then run again.")
        ensure_folders(default_folders())
        sys.exit(1)
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.read(CONFIG_PATH, encoding="utf-8")
    if not cfg.has_section("folders"):
        cfg.add_section("folders")
    defaults = default_folders()
    for key in FOLDER_NAMES:
        if not cfg["folders"].get(key, "").strip():
            cfg["folders"][key] = defaults[key]
    return cfg


def ensure_folders(folders):
    """Create any missing folders. Runs on every start."""
    for path in folders.values():
        if not os.path.isdir(path):
            os.makedirs(path, exist_ok=True)
            print(f"Created folder {path}")


def setup_logging():
    h = RotatingFileHandler(os.path.join(BASE_DIR, "faxwatcher.log"), maxBytes=1_000_000, backupCount=3)
    logging.basicConfig(level=logging.INFO, handlers=[h, logging.StreamHandler()],
                        format="%(asctime)s %(levelname)s %(message)s")


def unique_dest(folder, name):
    dest = os.path.join(folder, name)
    base, ext = os.path.splitext(name)
    n = 1
    while os.path.exists(dest):
        dest = os.path.join(folder, f"{base}_{int(time.time())}_{n}{ext}")
        n += 1
    return dest


def fax_log(log_dir, status, filename, number, detail=""):
    """Append one line per fax to <log_dir>/log.txt:
    2026-11-17 09:20:01 | SENT   | 5551234567 | 5551234567.pdf | """
    line = " | ".join([time.strftime("%Y-%m-%d %H:%M:%S"), f"{status:<6}",
                       number or "-", filename, detail.replace("\n", " ")])
    try:
        with open(os.path.join(log_dir, "log.txt"), "a", encoding="utf-8") as fh:
            fh.write(line.rstrip() + "\n")
    except OSError as e:
        logging.error("Could not write fax log: %s", e)


def is_settled(path, seconds):
    try:
        a = os.path.getsize(path)
        time.sleep(seconds)
        return a == os.path.getsize(path) and a > 0
    except OSError:
        return False


def make_client(cfg):
    method = cfg["server"].get("method", "api").strip().lower()
    return method, (FaxClient(cfg) if method == "web" else ApiFaxClient(cfg))


def single_instance():
    """Return False if another FaxSend watcher is already running (Windows)."""
    if os.name != "nt":
        return True
    import ctypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    global _MUTEX  # keep the handle open for the life of the process
    _MUTEX = kernel32.CreateMutexW(None, False, "Global\\FaxSendWatcher")
    return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS


def run_watcher():
    cfg = load_config()
    ensure_folders({key: cfg["folders"][key] for key in FOLDER_NAMES})
    setup_logging()
    if not single_instance():
        logging.info("Another FaxSend is already running - exiting")
        return
    method, client = make_client(cfg)
    watch = cfg["folders"]["watch"]
    sent = cfg["folders"]["sent"]
    failed = cfg["folders"]["failed"]
    logs = cfg["folders"]["logs"]
    poll = cfg.getfloat("options", "poll_seconds", fallback=5)
    settle = cfg.getfloat("options", "settle_seconds", fallback=3)
    retries = cfg.getint("options", "retries", fallback=2)

    logging.info("Watching %s (method: %s)", watch, method)
    offline_since = None
    while True:
        try:
            for name in sorted(os.listdir(watch)):
                path = os.path.join(watch, name)
                if not os.path.isfile(path) or not name.lower().endswith(".pdf"):
                    continue
                m = NAME_RE.match(name)
                if not m:
                    logging.warning("Bad filename (need 10 digit number): %s", name)
                    fax_log(logs, "FAILED", name, None, "Bad filename - must start with a 10 digit number")
                    shutil.move(path, unique_dest(failed, name))
                    continue
                if not is_settled(path, settle):
                    continue
                number = m.group(1)
                ok = False
                last_error = ""
                for attempt in range(1, retries + 2):
                    try:
                        client.send(path, number)
                        ok = True
                        break
                    except SendUnconfirmed as e:
                        last_error = f"UNCONFIRMED, not retried: {e}"
                        logging.error("Send %s: %s", name, last_error)
                        break
                    except (ServerUnreachable, requests.exceptions.ConnectionError):
                        raise  # leave the fax in the Outbox; handled below
                    except Exception as e:
                        last_error = str(e)
                        logging.error("Send %s attempt %d failed: %s", name, attempt, e)
                        time.sleep(5)
                if offline_since:
                    logging.info("Server reachable again")
                    offline_since = None
                if ok:
                    logging.info("Sent %s to %s", name, number)
                    fax_log(logs, "SENT", name, number)
                    shutil.move(path, unique_dest(sent, name))
                else:
                    fax_log(logs, "FAILED", name, number,
                            last_error if last_error.startswith("UNCONFIRMED")
                            else f"{retries + 1} attempts - {last_error}")
                    shutil.move(path, unique_dest(failed, name))
        except (ServerUnreachable, requests.exceptions.ConnectionError) as e:
            if not offline_since:
                offline_since = time.time()
                logging.warning("Server unreachable - faxes stay in the Outbox and will be "
                                "sent when it is back: %s", e)
            time.sleep(max(poll, 30))
            continue
        except Exception as e:
            logging.error("Loop error: %s", e)
        time.sleep(poll)


# ---------------------------------------------------------------- Windows install

def program_dir():
    return os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "FaxSend")


def schtasks(*args):
    return subprocess.run(["schtasks", *args], capture_output=True, text=True,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def task_installed():
    return schtasks("/Query", "/TN", TASK_NAME).returncode == 0


def is_admin():
    import ctypes
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin(args):
    """Re-run this exe elevated (UAC prompt). Returns True if it was launched."""
    import ctypes
    params = subprocess.list2cmdline(args)
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
    return rc > 32


TASK_XML = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>FaxSend: faxes PDFs dropped into {watch}</Description>
  </RegistrationInfo>
  <Triggers>
    <BootTrigger><Enabled>true</Enabled><Delay>PT30S</Delay></BootTrigger>
    <TimeTrigger>
      <Repetition><Interval>PT5M</Interval><StopAtDurationEnd>false</StopAtDurationEnd></Repetition>
      <StartBoundary>2024-01-01T00:00:00</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author"><UserId>S-1-5-18</UserId><RunLevel>HighestAvailable</RunLevel></Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure><Interval>PT1M</Interval><Count>999</Count></RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{command}</Command>
      <Arguments>{arguments}</Arguments>
    </Exec>
  </Actions>
</Task>
"""


def install(source_dir):
    """Copy the exe to Program Files, put config.ini in place, check the server,
    and register + start the background task. Runs elevated."""
    print("FaxSend setup\n=============")
    os.makedirs(BASE_DIR, exist_ok=True)

    # 1. config.ini shipped next to FaxSend.exe in the zip
    bundled = os.path.join(source_dir, "config.ini")
    if os.path.isfile(bundled):
        if os.path.isfile(CONFIG_PATH):
            with open(bundled, "rb") as a, open(CONFIG_PATH, "rb") as b:
                same = a.read() == b.read()
            if not same:
                shutil.copyfile(CONFIG_PATH, CONFIG_PATH + ".bak")
                shutil.copyfile(bundled, CONFIG_PATH)
                print("Updated settings (previous ones saved as config.ini.bak)")
        else:
            shutil.copyfile(bundled, CONFIG_PATH)
    elif not os.path.isfile(CONFIG_PATH):
        print("ERROR: config.ini was not found next to FaxSend.exe.\n"
              "Unzip the whole folder first, then run FaxSend.exe from the unzipped folder.")
        return False

    # 2. folders + connection check
    cfg = load_config()
    folders = {key: cfg["folders"][key] for key in FOLDER_NAMES}
    ensure_folders(folders)
    setup_logging()
    readme = os.path.join(source_dir, "README.txt")
    if os.path.isfile(readme):
        try:
            shutil.copyfile(readme, os.path.join(BASE_DIR, "README.txt"))
        except OSError as e:
            print(f"Note: could not copy README.txt to {BASE_DIR}: {e}")
    print("Checking the connection to the fax server...")
    try:
        method, client = make_client(cfg)
        print(client.test())
    except Exception as e:
        print(f"\nERROR: could not connect to the fax server:\n  {e}\n\n"
              "Nothing was installed. Check the internet connection and try again,\n"
              "or contact your phone system provider.")
        return False

    # 3. stop an old copy, then install the exe
    if task_installed():
        schtasks("/End", "/TN", TASK_NAME)
        time.sleep(3)
    dest_dir = program_dir()
    dest_exe = os.path.join(dest_dir, "FaxSend.exe")
    os.makedirs(dest_dir, exist_ok=True)
    if FROZEN and os.path.abspath(sys.executable).lower() != dest_exe.lower():
        for attempt in range(10):
            try:
                shutil.copyfile(sys.executable, dest_exe)
                break
            except PermissionError:
                subprocess.run(["taskkill", "/F", "/IM", "FaxSend.exe", "/FI",
                                f"PID ne {os.getpid()}"], capture_output=True)
                time.sleep(1)
        else:
            print(f"ERROR: could not replace {dest_exe} (it is in use). Restart the PC and try again.")
            return False
    command = dest_exe if FROZEN else sys.executable
    arguments = subprocess.list2cmdline(
        ([] if FROZEN else [os.path.abspath(__file__)]) + ["--run", "--base-dir", BASE_DIR])

    # 4. register and start the task
    xml_path = os.path.join(dest_dir, "FaxSend-task.xml")
    with open(xml_path, "w", encoding="utf-16") as fh:
        fh.write(TASK_XML.format(watch=xml_escape(folders["watch"]),
                                 command=xml_escape(command), arguments=xml_escape(arguments)))
    r = schtasks("/Create", "/TN", TASK_NAME, "/XML", xml_path, "/F")
    if r.returncode != 0:
        print("ERROR: could not create the background task:\n" + r.stdout + r.stderr)
        return False
    schtasks("/Run", "/TN", TASK_NAME)
    time.sleep(3)

    print("\nFaxSend is installed and running in the background.")
    print("It starts automatically with Windows - nothing needs to stay open.\n")
    print(f"  To send a fax, save or copy the PDF into:\n    {folders['watch']}")
    print("  and name it with the 10 digit fax number, for example 4165551234.pdf\n")
    print(f"  Sent faxes are moved to:   {folders['sent']}")
    print(f"  Problem faxes are moved to: {folders['failed']}")
    print(f"  History of every fax:       {os.path.join(folders['logs'], 'log.txt')}")
    return True


def uninstall():
    if not task_installed():
        print("FaxSend is not installed.")
        return True
    schtasks("/End", "/TN", TASK_NAME)
    r = schtasks("/Delete", "/TN", TASK_NAME, "/F")
    if r.returncode != 0:
        print("ERROR: could not remove the background task:\n" + r.stdout + r.stderr)
        return False
    print("FaxSend background task removed. Your fax folders and history were not deleted.")
    print(f"You can delete {program_dir()} manually.")
    return True


def status():
    r = schtasks("/Query", "/TN", TASK_NAME, "/FO", "LIST", "/V")
    if r.returncode != 0:
        print("FaxSend is NOT installed.")
        return False
    info = {}
    for line in r.stdout.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            info.setdefault(k.strip(), v.strip())
    print(f"FaxSend background task: {info.get('Status', 'unknown')}")
    print(f"Last run: {info.get('Last Run Time', '?')}")
    print(f"Fax folder: {cfg_watch_folder()}")
    log = os.path.join(BASE_DIR, "Logs", "log.txt")
    if os.path.isfile(log):
        with open(log, encoding="utf-8", errors="replace") as fh:
            last = fh.readlines()[-5:]
        if last:
            print("\nLast faxes:")
            print("".join("  " + line for line in last), end="")
    return True


def cfg_watch_folder():
    try:
        cfg = configparser.ConfigParser(interpolation=None)
        cfg.read(CONFIG_PATH, encoding="utf-8")
        return cfg.get("folders", "watch", fallback="").strip() or default_folders()["watch"]
    except Exception:
        return default_folders()["watch"]


def pause():
    """Keep the window open when the user double-clicked the exe."""
    if FROZEN and sys.stdin and sys.stdin.isatty():
        input("\nPress Enter to close this window...")


def main():
    args = sys.argv[1:]
    if "--base-dir" in args:
        i = args.index("--base-dir")
        set_base_dir(args[i + 1])
        del args[i:i + 2]
    flags = set(args)

    if flags & {"--test-api", "--test-login"}:
        cfg = load_config()
        setup_logging()
        try:
            method, client = make_client(cfg)
            print(f"Method: {method}")
            print(client.test())
        except Exception as e:
            print("FAILED:", e)
            sys.exit(1)
        return

    if "--run" in flags or os.name != "nt":
        run_watcher()
        return

    if "--status" in flags:
        status()
        pause()
        return

    if "--uninstall" in flags:
        if not is_admin():
            relaunch_as_admin(["--uninstall"])
            return
        uninstall()
        pause()
        return

    # --install, or double-clicked with no arguments
    if "--install" not in flags and task_installed():
        status()
        pause()
        return
    if not is_admin():
        # Pass this user's folder, so it is kept even if an admin login is used for UAC
        source = args[args.index("--source") + 1] if "--source" in args else APP_DIR
        if relaunch_as_admin(["--install", "--base-dir", BASE_DIR, "--source", source]):
            print("Continuing setup in the administrator window...")
        else:
            print("Setup needs administrator approval. Run FaxSend.exe again and choose Yes.")
            pause()
        return
    source = args[args.index("--source") + 1] if "--source" in args else APP_DIR
    ok = install(source)
    pause()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
