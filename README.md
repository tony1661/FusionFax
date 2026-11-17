# FusionFax

Send faxes from a Windows PC through a [FusionPBX](https://www.fusionpbx.com)
server by saving a PDF into a folder. FusionFax doesn't need a web login, an
email-to-fax gateway or anyone to watch it. It runs in the background and
starts with Windows.

Inside the program, and in the folders it creates on the PC, it is called
**FaxSend**.

## How it works

1. Save a PDF into `Documents\FaxSend\Outbox`, named with the 10-digit fax
   number:
   ```
   4165551234.pdf
   4165551234 lab results.pdf     (text after the number is fine)
   ```
2. FaxSend converts the PDF to a fax TIFF (TIFF-F). FreeSWITCH can only send
   that format.
3. It sends the fax to the FusionPBX fax queue through the REST API, then
   checks that the fax was queued.
4. The file moves to `Sent` or `Failed`, and a line is added to
   `Logs\log.txt` with the time, number and result.

If the server can't be reached, faxes wait in the Outbox and are sent
automatically when the connection is back.

## Features

- **One-click install.** Run `FaxSend.exe` once and it copies itself to
  Program Files and registers a startup task that restarts itself if it
  stops.
- **Per-customer settings.** Each customer gets a zip containing the exe and
  a pre-filled `config.ini`, so they never enter an API key.
- **No duplicate faxes.** A send that might have gone through is never
  retried automatically.
- **Handles awkward PDFs.** Landscape pages are rotated. Fax resolution is
  `normal`, `fine` or `superfine`. Damaged or password-protected PDFs go to
  `Failed` with a clear reason.

## Requirements

- **FusionPBX** with the REST API (`/app/api/7/`).
- **A FusionPBX user with an API key** and these permissions: `fax_view`,
  `fax_queue_add`, `fax_queue_view`.
- **Windows 10 or 11** to run it.
- **Python 3** on the PC that builds the exe. `build.bat` installs the
  libraries it needs: `requests`, `pypdfium2`, `pillow` and `pyinstaller`.

## Quick start

```
build.bat                                  builds dist\FaxSend.exe
copy config.template.ini customers\NAME\config.ini    then fill in url, api_key, fax_uuid, hostname
make_package.bat NAME                      tests the settings, creates packages\FaxSend-NAME.zip
```

The customer extracts the zip and double-clicks `FaxSend.exe`. That's all
they need to do.

**[DEPLOY.md](DEPLOY.md)** is a full step-by-step guide covering FusionPBX
setup, building, packaging and installing. It's written so someone new to it
can follow along.

## Commands

| Command | What it does |
|---|---|
| `FaxSend.exe` | Installs it, or shows the status if it's already installed |
| `FaxSend.exe --status` | Shows whether the background task is running |
| `FaxSend.exe --uninstall` | Removes the background task (fax folders are kept) |
| `FaxSend.exe --test-api` | Checks the API key and fax server without sending anything |
| `FaxSend.exe --run` | Runs the watcher in the open window, for troubleshooting |

## Files

| File | Purpose |
|---|---|
| `faxwatcher.py` | The program |
| `build.bat` | Builds `FaxSend.exe` with PyInstaller |
| `make_package.bat` | Tests a customer's settings and builds their zip |
| `config.template.ini` | Settings template, with an explanation of each option |
| `README-customer.txt` | Instructions for end users, included in each zip |
| `DEPLOY.md` | Deployment guide |

**Never commit a filled-in `config.ini`.** It contains the customer's API
key. `.gitignore` already excludes `config.ini`, `customers/` and
`packages/`.

## License

MIT. See [LICENSE](LICENSE).
