import base64
import http.client
import json
import logging
import ssl
import uuid
from pathlib import Path
from urllib.parse import quote


def _make_ssl_context(verify_ssl):
    ctx = ssl.create_default_context()
    if not verify_ssl:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _api_request(method, path, config, body=None):
    host = config['FUSIONPBX_HOST']
    api_key = config['FUSIONPBX_API_KEY']
    verify_ssl = config.get('VERIFY_SSL', 'true').strip().lower() != 'false'

    logging.debug(f'API {method} https://{host}{path}')
    if body:
        try:
            logged = json.loads(body)
            for entry in logged.get('fax_queue', []):
                if 'fax_base64' in entry:
                    entry['fax_base64'] = '<omitted>'
            logging.debug(f'Request body: {json.dumps(logged)}')
        except (json.JSONDecodeError, AttributeError):
            logging.debug(f'Request body: {body.decode("utf-8")}')

    conn = http.client.HTTPSConnection(host, context=_make_ssl_context(verify_ssl))
    try:
        conn.request(
            method,
            path,
            body=body,
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Basic {api_key}',
            },
        )
        response = conn.getresponse()
        response_body = response.read().decode('utf-8')
    finally:
        conn.close()

    logging.debug(f'API response {response.status}: {response_body}')
    return response.status, response_body


def get_insert_user_uuid(config):
    """Validate INSERT_USER exists and return their user_uuid."""
    username = config['INSERT_USER']
    status, body = _api_request('GET', f'/app/api/7/users?username={quote(username)}', config)
    if status != 200:
        raise RuntimeError(f'Failed to look up user "{username}" (HTTP {status}): {body}')
    try:
        data = json.loads(body)
        rows = data.get('users') if isinstance(data, dict) else data
        if not rows:
            raise RuntimeError(f'User "{username}" not found in FusionPBX')
        # Filter client-side in case the API does a LIKE instead of exact match
        matches = [u for u in rows if u.get('username') == username]
        if not matches:
            raise RuntimeError(f'User "{username}" not found in FusionPBX')
        if len(matches) > 1:
            raise RuntimeError(f'Multiple users matched "{username}" - use a more specific username')
        return matches[0]['user_uuid']
    except (json.JSONDecodeError, KeyError) as e:
        raise RuntimeError(f'Unexpected users response: {e}\n{body}')


def get_fax_server(config):
    """Fetch caller ID name, caller ID number, and email from the fax server record."""
    fax_uuid = config['FUSIONPBX_FAX_UUID']
    status, body = _api_request('GET', f'/app/api/7/fax/{fax_uuid}', config)
    if status != 200:
        raise RuntimeError(f'Failed to fetch fax server details (HTTP {status}): {body}')
    try:
        data = json.loads(body)
        # API may return {"fax": [{...}]} or a bare dict depending on version
        if isinstance(data, dict) and 'fax' in data:
            record = data['fax'][0] if isinstance(data['fax'], list) else data['fax']
        elif isinstance(data, list):
            record = data[0]
        else:
            record = data
    except (json.JSONDecodeError, IndexError, KeyError) as e:
        raise RuntimeError(f'Unexpected fax server response: {e}\n{body}')
    return {
        'caller_id_name': record.get('fax_caller_id_name', ''),
        'caller_id_number': record.get('fax_caller_id_number', ''),
    }


def send_fax(pdf_path, fax_number, config):
    with open(pdf_path, 'rb') as f:
        fax_base64 = base64.b64encode(f.read()).decode('ascii')

    hostname = config.get('FUSIONPBX_HOSTNAME') or ''

    payload = {
        "fax_queue": [
            {
                "fax_queue_uuid": str(uuid.uuid4()),
                "domain_uuid": config['FUSIONPBX_DOMAIN_UUID'],
                "fax_uuid": config['FUSIONPBX_FAX_UUID'],
                "fax_date": "now()",
                "hostname": hostname,
                "fax_caller_id_name": config.get('FUSIONPBX_CALLER_ID_NAME', ''),
                "fax_caller_id_number": config.get('FUSIONPBX_CALLER_ID_NUMBER', ''),
                "fax_number": fax_number,
                "fax_prefix": config.get('FUSIONPBX_FAX_PREFIX', ''),
                "fax_email_address": config.get('FUSIONPBX_FAX_EMAIL', ''),
                "fax_filename": Path(pdf_path).name,
                "fax_base64": fax_base64,
                "fax_status": "waiting",
                "fax_retry_date": "",
                "fax_notify_date": "",
                "fax_retry_count": "",
                "fax_accountcode": config['FUSIONPBX_HOST'],
                "fax_command": "",
                "fax_response": "",
                "insert_user": config['INSERT_USER_UUID'],
            }
        ]
    }

    body = json.dumps(payload).encode('utf-8')
    status, response_body = _api_request('POST', '/app/api/7/fax_queue', config, body)

    if status not in (200, 201):
        raise RuntimeError(f'API returned HTTP {status}: {response_body}')

    return response_body
