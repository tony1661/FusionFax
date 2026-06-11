#!/usr/bin/env python3
import logging
import os
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path

from fusionpbx_api import get_fax_server, get_insert_user_uuid, send_fax

# Resolve .env relative to this script's location so the script can be run
# from any working directory on any platform.
_SCRIPT_DIR = Path(__file__).parent


def load_env(path=None):
    env = {}
    env_path = Path(path) if path else _SCRIPT_DIR / '.env'
    try:
        with open(env_path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, _, value = line.partition('=')
                env[key.strip()] = value.strip()
    except FileNotFoundError:
        pass
    # OS environment variables take precedence over .env file
    env.update(os.environ)
    return env


def truncate_log(log_file, max_days):
    """Remove log lines older than max_days from the log file."""
    path = Path(log_file)
    if not path.exists():
        return
    cutoff = datetime.now() - timedelta(days=max_days)
    kept = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            try:
                ts = datetime.strptime(line[:19], '%Y-%m-%d %H:%M:%S')
                if ts >= cutoff:
                    kept.append(line)
            except ValueError:
                kept.append(line)
    with open(path, 'w', encoding='utf-8') as f:
        f.writelines(kept)


def setup_logging(log_file, log_level, max_days):
    os.makedirs(os.path.dirname(os.path.abspath(log_file)), exist_ok=True)
    truncate_log(log_file, max_days)
    level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler(),
        ],
    )


def main():
    config = load_env()

    required = (
        'FUSIONPBX_HOST',
        'FUSIONPBX_HOSTNAME',
        'FUSIONPBX_API_KEY',
        'FUSIONPBX_DOMAIN_UUID',
        'FUSIONPBX_FAX_UUID',
        'FUSIONPBX_FAX_EMAIL',
        'INSERT_USER',
        'WATCH_DIR',
    )
    missing = [k for k in required if not config.get(k)]
    if missing:
        raise SystemExit(f'Missing required config: {", ".join(missing)}')

    watch_dir = config['WATCH_DIR']
    completed_dir = config.get('COMPLETED_DIR') or os.path.join(watch_dir, 'completed')
    problem_dir = config.get('PROBLEM_DIR') or os.path.join(watch_dir, 'problem')
    log_file = config.get('LOG_FILE') or os.path.join(watch_dir, 'print2fax.log')

    log_level = config.get('LOG_LEVEL', 'INFO')
    log_max_days = int(config.get('LOG_MAX_DAYS', '7'))

    os.makedirs(completed_dir, exist_ok=True)
    os.makedirs(problem_dir, exist_ok=True)
    setup_logging(log_file, log_level, log_max_days)

    # Validate INSERT_USER and resolve to a UUID.
    config['INSERT_USER_UUID'] = get_insert_user_uuid(config)
    logging.info(f"Insert user: {config['INSERT_USER']} ({config['INSERT_USER_UUID']})")

    # Fetch caller ID from the fax server record.
    fax_server = get_fax_server(config)
    config.setdefault('FUSIONPBX_CALLER_ID_NAME', fax_server['caller_id_name'])
    config.setdefault('FUSIONPBX_CALLER_ID_NUMBER', fax_server['caller_id_number'])
    logging.info(
        f"Fax server: caller_id={config['FUSIONPBX_CALLER_ID_NAME']} "
        f"<{config['FUSIONPBX_CALLER_ID_NUMBER']}>, "
        f"email={config['FUSIONPBX_FAX_EMAIL']}"
    )

    timestamp = time.strftime('%m%d-%H%M%S')
    logging.debug(f'Scanning watch directory: {watch_dir}')

    for entry in sorted(Path(watch_dir).iterdir()):
        logging.debug(f'Found entry: {entry.name} (is_file={entry.is_file()}, suffix={entry.suffix})')
        if not entry.is_file() or entry.suffix.lower() != '.pdf':
            continue

        stem = entry.stem
        new_name = f'{stem}-{timestamp}.pdf'
        logging.debug(f'{entry.name}: stem="{stem}", will rename to "{new_name}"')

        if not stem.isnumeric():
            dest = Path(problem_dir) / new_name
            shutil.move(str(entry), str(dest))
            logging.error(f'{entry.name}: filename is not numeric - moved to problem')
            continue

        if len(stem) != 10:
            dest = Path(problem_dir) / new_name
            shutil.move(str(entry), str(dest))
            logging.error(
                f'{entry.name}: filename must be exactly 10 digits (got {len(stem)}) - moved to problem'
            )
            continue

        logging.debug(f'{entry.name}: validation passed, submitting to FusionPBX fax queue')
        try:
            response = send_fax(str(entry), stem, config)
            logging.debug(f'{entry.name}: API response: {response}')
            dest = Path(completed_dir) / new_name
            shutil.move(str(entry), str(dest))
            logging.info(f'{entry.name}: queued successfully - moved to completed as {new_name}')
        except Exception as e:
            dest = Path(problem_dir) / new_name
            shutil.move(str(entry), str(dest))
            logging.error(f'{entry.name}: failed to send - {e} - moved to problem')


if __name__ == '__main__':
    main()
