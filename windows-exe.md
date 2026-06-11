# Building a Windows Executable

These steps produce a single `print2fax.exe` file that can be run on any Windows machine without Python installed.

## Prerequisites

Python 3.7 or later must be installed on the machine used to build the executable. It does not need to be installed on machines that will run the final `.exe`.

## Install PyInstaller

```
pip install pyinstaller
```

## Build the executable

Run this from the directory containing `print2fax.py`:

```
pyinstaller --onefile print2fax.py
```

PyInstaller will create a `dist` folder. The executable is at:

```
dist\print2fax.exe
```

## Deployment

Copy the following to the target machine in the same directory:

```
print2fax.exe
.env
```

The `.env` file must be in the same directory as the `.exe`. The script resolves it relative to its own location, so the working directory does not matter.

Do not copy the `build` folder or the `.spec` file to the target machine. They are only needed during the build process.

## Running the executable

Double-click `print2fax.exe` or run it from the command line:

```
print2fax.exe
```

To run it as a scheduled task, follow the Windows Scheduled Task steps in [README.md](README.md). In the Actions tab, set:

- **Program/script:** Full path to `print2fax.exe`
- **Add arguments:** _(leave blank)_
- **Start in:** Directory containing `print2fax.exe` and `.env`

## Notes

- If Windows Defender or another antivirus flags the `.exe`, you may need to add an exclusion for it. This is common with PyInstaller-built executables and is a false positive.
- The `completed`, `problem`, and log file paths in `.env` should use full absolute paths on Windows, e.g. `C:\print2fax\watch`.
- If your FusionPBX server uses a self-signed SSL certificate, set `VERIFY_SSL=false` in `.env`.
