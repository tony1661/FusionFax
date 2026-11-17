# Deploying FaxSend to a customer

This guide takes you from nothing to a zip file you can send to a customer. You
do part 1 once per Windows PC. Do parts 2–5 for each new customer.

**What you need:**
- A Windows 10 or 11 PC to build on, and administrator rights on it
- An admin login to the customer's FusionPBX
- Internet access to download the code from GitHub

---

## Part 1 – Set up the Windows build PC (one time only)

### 1.1 Install Python
1. Go to https://www.python.org/downloads/ and click the yellow
   **Download Python** button.
2. Run the downloaded installer.
3. **On the first screen, tick "Add python.exe to PATH"** at the bottom, then
   click **Install Now**.
4. When it says "Setup was successful", click **Close**.

### 1.2 Get the FaxSend files
1. Go to https://github.com/tony1661/FusionFax.
2. Click the green **Code** button, then **Download ZIP**.
3. Open your Downloads folder, right-click the zip, and choose
   **Extract All...**. Extract it to an easy location, for example
   `C:\FaxSend-build`.
4. Open that folder. You should see `build.bat`, `make_package.bat`,
   `config.template.ini`, `faxwatcher.py` and a few other files. If you only
   see one folder (such as `FusionFax-main`), open it. That folder is the
   **build folder** for the rest of this guide.

### 1.3 Build FaxSend.exe
1. In the build folder, double-click **build.bat**.
2. A black window opens and downloads what it needs. This takes 1–3 minutes
   the first time.
3. It finishes with **Built: ...\dist\FaxSend.exe**. Press any key to close
   the window.
4. You now have a `dist` folder with `FaxSend.exe` inside it.

If it says **Python not found**, Python wasn't added to PATH. Run the Python
installer again, choose **Modify**, make sure "Add Python to environment
variables" is ticked, and try again.

If your antivirus deletes or blocks `FaxSend.exe`, add an exclusion for the
build folder and run `build.bat` again. Antivirus software sometimes flags
programs built this way even though they are safe.

You only need to build again when the FaxSend code changes. The same
`FaxSend.exe` works for every customer.

---

## Part 2 – Prepare the customer's FusionPBX (each customer)

Log in to the customer's FusionPBX as an admin.

### 2.1 Choose the user FaxSend will send as
FaxSend logs in as one FusionPBX user. Ideally, create a new user just for
this, for example `faxsend`, under **Accounts → Users → Add**. You can also
use an existing user.

### 2.2 Give that user the fax permissions
1. Note which **group** the user is in (shown on the user's edit page).
2. Go to **Advanced → Group Manager** and click **Permissions** next to that
   group.
3. Search for each of these permissions, tick it, and click **Save**:
   - `fax_view`
   - `fax_queue_add`
   - `fax_queue_view`

### 2.3 Create the API key
1. Go to **Accounts → Users** and click the user to edit it.
2. Find the **API Key** field. If it is empty, click the button next to it to
   generate a key.
3. Click **Save**.
4. Copy the key into Notepad for now. **Treat it like a password.** Anyone
   with it can send faxes as this customer.

### 2.4 Find the fax server ID
1. Go to **Applications → Fax Server**.
2. Click the fax server (fax number or extension) the customer will send from.
3. Look at the address bar. The address ends with `?id=` followed by a long
   ID, for example:
   `https://pbx.example.com/app/fax/fax_edit.php?id=1a2b3c4d-1111-2222-3333-444455556666`
4. Copy everything after `id=` into Notepad. This is the **fax_uuid**.

### 2.5 Note the server details
- **Web address:** the address you use to log in to this customer's
  FusionPBX, for example `https://pbx.example.com`. It must be the
  customer's own domain, not another customer's.
- **Server hostname:** the server's own name, which is not the web address.
  Ask whoever manages the server to run `hostname` on it, for example `pbx1`.

---

## Part 3 – Fill in the customer's config.ini

1. In the build folder, open the `customers` folder. If it doesn't exist,
   create it.
2. Inside `customers`, create a folder for this customer. Use a short name
   with **no spaces**, for example `smithclinic`. You'll type this name again
   in Part 4.
3. Copy `config.template.ini` from the build folder into
   `customers\smithclinic`, then rename the copy to **config.ini**.

   If Windows hides file extensions, the file may show as just `config` or
   `config.template`. Turn on **View → Show → File name extensions** in File
   Explorer so you can rename it correctly.
4. Right-click `config.ini` → **Open with → Notepad**.
5. Change these lines in the `[server]` section:

   | Line | What to put |
   |---|---|
   | `url =` | The customer's web address from 2.5, with no `/` at the end (replace `PUT_URL_HERE`) |
   | `api_key =` | The API key from 2.3 (replace `PUT_API_KEY_HERE`) |
   | `fax_uuid =` | The ID from 2.4 (replace `PUT_FAX_UUID_HERE`) |
   | `hostname =` | The server hostname from 2.5, for example `pbx1` (blank in the template) |

   Example:
   ```ini
   url = https://pbx.example.com
   method = api
   api_key = a1b2c3d4e5f6...
   fax_uuid = 1a2b3c4d-1111-2222-3333-444455556666
   hostname = pbx1
   ```
6. Leave everything else as it is unless the customer asks for something
   specific. Blank caller ID lines use the fax server's own caller ID.
7. **Save** and close Notepad.

---

## Part 4 – Make the customer's zip

1. Open the build folder in File Explorer.
2. Click in the address bar at the top, type `cmd`, and press **Enter**. A
   Command Prompt opens in that folder.
3. Type the following, using your customer folder name, and press
   **Enter**:
   ```
   make_package.bat smithclinic
   ```
4. FaxSend checks the settings against the customer's server. A good result
   looks like this:
   ```
   OK - API key accepted
   Fax server: Main Fax (extension 5000)
   Caller ID:  Smith Clinic 4165551234
   Domain:     9f8e7d6c-...
   Fax queue: readable (sends can be confirmed)

   Created packages\FaxSend-smithclinic.zip
   ```
   Check that the fax server name and caller ID are the customer's, not
   another customer's.

**If it fails:**

| Message | Fix |
|---|---|
| `dist\FaxSend.exe not found` | Do Part 1.3 first |
| `config.ini not found` | Check the folder name in `customers` and that the file is called `config.ini`, not `config.ini.txt` |
| `still has PUT_URL_HERE, PUT_API_KEY_HERE...` | You didn't replace a placeholder (Part 3) |
| `has no hostname` | Fill in the `hostname =` line (Part 3) |
| `401` / `unauthorized` / API key error | The API key is wrong, or the user wasn't saved after generating it (2.3) |
| `403` / permission error / `not found through the API` | Check the permissions (2.2) and the fax_uuid (2.4) |
| `WARNING: cannot read the fax queue` | Add `fax_queue_view` (2.2) |
| Connection error | Check the `url` line, and that this PC has internet access |

5. The finished zip is at `packages\FaxSend-smithclinic.zip`.

---

## Part 5 – Send the zip and install it

### 5.1 Send it securely
The zip contains the customer's API key. **Don't send it as a normal email
attachment.** Use a secure share link, for example a OneDrive or SharePoint
link restricted to the customer that expires after a few days. Or install it
yourself through remote support.

### 5.2 Install on the customer's PC
Install it on the PC used for faxing, logged in as the **Windows user who
will be saving the faxes**. The fax folders are created in that user's
Documents folder.

1. Copy the zip to the PC, right-click it, and choose **Extract All...**.
2. Open the extracted folder and double-click **FaxSend.exe**.
3. If Windows shows "Windows protected your PC", click **More info → Run
   anyway**.
4. Click **Yes** when Windows asks for permission.
5. Wait for **"FaxSend is installed and running in the background"**, then
   press Enter.
6. You can now delete the zip and the extracted folder.

### 5.3 Test it
1. Open **Documents\FaxSend**. It contains the folders `Outbox`, `Sent`,
   `Failed` and `Logs`, plus `README.txt` for the customer.
2. Save a 1–2 page PDF into **Outbox**, named with a fax number you can check,
   for example `4165551234.pdf`.
3. Within about 10 seconds it should move to **Sent**.
4. Check that the fax arrived and is readable.
5. Open **Logs\log.txt** to see the entry for the send.

If it goes to **Failed**, the reason is in `Logs\log.txt`.

### 5.4 Show the customer
Point them to `Documents\FaxSend\README.txt`. It explains how to name files,
what the Sent and Failed folders mean, and how to uninstall.

---

## Updating a customer later

- **New settings, for example a new API key:** edit
  `customers\NAME\config.ini`, run `make_package.bat NAME` again, and have the
  new zip installed the same way (Part 5.2). The old settings are kept as
  `config.ini.bak` in Documents\FaxSend.
- **New version of FaxSend:** download the latest code (Part 1.2), run
  `build.bat` (Part 1.3), then `make_package.bat NAME` for each customer, and
  install each new zip. Installing over the old version replaces it.
  Faxes and history are kept.

## Keep these safe
- The `customers` and `packages` folders contain API keys. They are never
  uploaded to GitHub, so keep a backup of `customers` somewhere secure, such
  as a password manager or a restricted company share.
- If a customer's API key leaks, generate a new one in FusionPBX (2.3). The
  old key stops working immediately. Then send them a new zip.
