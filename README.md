# FusionFax

FusionFax watches a directory for PDF files and sends them as faxes through a [FusionPBX](https://www.fusionpbx.com) server via its REST API. No mail server or third-party Python packages required.

FusionPBX is an open source multi-tenant PBX built on FreeSWITCH. FusionFax integrates with its fax queue directly, submitting jobs via the FusionPBX REST API so that FusionPBX handles all outbound fax transmission.

## How it works

Drop a PDF file into the watch directory with a 10-digit North American phone number as the filename:

```
9055551234.pdf
```

When the script runs, it reads the filename, strips the extension, and uses those 10 digits as the destination fax number. The PDF is base64-encoded and submitted directly to the FusionPBX fax queue via the REST API. FusionPBX handles the actual sending.

Files that pass validation are moved to the `completed` directory with a timestamp appended to the filename. Files that fail validation or cannot be sent are moved to the `problem` directory with a timestamp appended so originals are never overwritten.

### Filename validation rules

- Must be exactly 10 digits
- Must contain only numbers
- Must have a `.pdf` extension

Any file that does not meet these rules is moved to the `problem` directory and logged as an error.

## Requirements

- Python 3.7 or later
- No third-party packages
- A FusionPBX server with the REST API installed and a user with an API key

## Setup

**1. Copy the example environment file and fill in your values:**

```
cp .env.example .env
```

Open `.env` and set each value. Required fields:

| Variable | Description |
|---|---|
| `FUSIONPBX_HOST` | Hostname or IP of your FusionPBX server |
| `FUSIONPBX_HOSTNAME` | System hostname of the server — run `hostname` on the server |
| `FUSIONPBX_API_KEY` | API key from Menu > Accounts > User Manager > Edit > API Key |
| `FUSIONPBX_DOMAIN_UUID` | Domain UUID from Menu > Accounts > Domains |
| `FUSIONPBX_FAX_UUID` | UUID of the fax server record from Menu > Fax > Fax Servers |
| `FUSIONPBX_FAX_EMAIL` | Email address to receive fax delivery notifications |
| `INSERT_USER` | FusionPBX username to record as the submitting user |
| `WATCH_DIR` | Directory to watch for incoming PDF files |

Optional fields:

| Variable | Default | Description |
|---|---|---|
| `COMPLETED_DIR` | `WATCH_DIR/completed` | Where successfully queued faxes are moved |
| `PROBLEM_DIR` | `WATCH_DIR/problem` | Where invalid or failed faxes are moved |
| `LOG_FILE` | `WATCH_DIR/print2fax.log` | Log file path |
| `LOG_LEVEL` | `INFO` | Logging verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `LOG_MAX_DAYS` | `7` | Number of days of log history to retain |
| `FUSIONPBX_FAX_PREFIX` | _(none)_ | Dial prefix prepended to fax numbers |
| `VERIFY_SSL` | `true` | Set to `false` for self-signed certificates |

Caller ID name and number are fetched automatically from the fax server record in FusionPBX and do not need to be set manually.

**2. Create the watch directory:**

```
mkdir -p /path/to/watch
```

**3. Run the script:**

```
python print2fax.py
```

The script is designed to be run on a schedule. It processes all pending PDFs in the watch directory each time it runs and exits.

## Running as a Windows Scheduled Task

This is the recommended way to run the script on Windows. It will execute automatically at a set interval without requiring the user to do anything.

**If you are running the compiled `.exe` version**, see [windows-exe.md](windows-exe.md) first.

**Steps:**

1. Open **Task Scheduler** (search for it in the Start menu).

2. In the right panel, click **Create Task**.

3. On the **General** tab:
   - Give the task a name, e.g. `FusionFax`
   - Select **Run whether user is logged on or not**
   - Check **Run with highest privileges**

4. On the **Triggers** tab, click **New**:
   - Set **Begin the task** to `On a schedule`
   - Select **Daily**, then check **Repeat task every** and set it to `5 minutes` (or your preferred interval)
   - Set **for a duration of** to `Indefinitely`
   - Click **OK**

5. On the **Actions** tab, click **New**:
   - **Action:** Start a program
   - **Program/script:** Full path to `python.exe`, e.g. `C:\Python311\python.exe`
     (or the full path to `print2fax.exe` if using the compiled version)
   - **Add arguments:** `print2fax.py`
     (leave blank if using the compiled `.exe`)
   - **Start in:** Full path to the directory containing `print2fax.py` and `.env`, e.g. `C:\print2fax`

6. On the **Conditions** tab:
   - Uncheck **Start the task only if the computer is on AC power** if running on a laptop

7. Click **OK** and enter your Windows password when prompted.

**To verify it is working**, right-click the task and select **Run**. Check the log file at the path set in `LOG_FILE` to confirm it executed successfully.

## Running on Linux/macOS via cron

Add an entry to crontab to run every 5 minutes:

```
*/5 * * * * /usr/bin/python3 /path/to/print2fax.py
```

## Building a Windows executable

See [windows-exe.md](windows-exe.md) for instructions on compiling the script into a standalone `.exe` that does not require Python to be installed.

## Logging

Logs are written to both the log file and stdout. Set `LOG_LEVEL=DEBUG` in `.env` to log full API request and response details. Log entries older than `LOG_MAX_DAYS` are automatically removed each time the script runs.
