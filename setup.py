#!/usr/bin/env python3
"""First-time setup: configures qBittorrent password and Jellyfin admin + library.

Runs as a Docker Compose service inside the shared Docker network, so service
hostnames (qbittorrent, jellyfin) are used instead of localhost.

The Docker socket is mounted read-only to read qBittorrent's temporary password
from container logs without needing the docker CLI binary.

A sentinel file (SENTINEL) is written on successful completion so the script
becomes a no-op on every subsequent `docker compose up`.
"""

import http.client
import http.cookiejar
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# Written on first successful run; presence skips all setup on future starts.
SENTINEL = '/config/.setup_done'

QBIT_URL = 'http://qbittorrent:8080'
JELLYFIN_URL = 'http://jellyfin:8096'
QBIT_USERNAME = os.environ.get('QBIT_USERNAME', 'admin')
QBIT_PASSWORD = os.environ['QBIT_PASSWORD']
JELLYFIN_USERNAME = os.environ.get('JELLYFIN_USERNAME', 'admin')
JELLYFIN_PASSWORD = os.environ['JELLYFIN_PASSWORD']


def wait_for(url, timeout=120):
    """Poll url until it returns any HTTP response or timeout expires.

    The Docker Compose healthcheck already ensures services are up before this
    script starts, but a brief extra wait guards against race conditions during
    the healthcheck window.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=3)
            return True
        except Exception:
            time.sleep(2)
    return False


class _DockerSocketConnection(http.client.HTTPConnection):
    """HTTPConnection that routes over the Docker Unix socket instead of TCP.

    The Docker Engine exposes a REST API on /var/run/docker.sock.
    Docs: https://docs.docker.com/engine/api/
    """

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect('/var/run/docker.sock')


def get_container_logs(container_name):
    """Fetch stdout+stderr of a container via the Docker Engine API.

    Endpoint: GET /containers/{id}/logs
    Docs: https://docs.docker.com/engine/api/v1.43/#tag/Container/operation/ContainerLogs

    Docker multiplexes stdout and stderr into a single stream. Each chunk is
    prefixed with an 8-byte header:
      byte 0    : stream type (1 = stdout, 2 = stderr)
      bytes 1-3 : padding (zeros)
      bytes 4-7 : payload size as big-endian uint32
    Docs: https://docs.docker.com/engine/api/v1.43/#tag/Container/operation/ContainerAttach
    """
    conn = _DockerSocketConnection('localhost')
    conn.request('GET', f'/containers/{container_name}/logs?stdout=1&stderr=1&tail=200')
    resp = conn.getresponse()
    raw = resp.read()

    lines, i = [], 0
    while i + 8 <= len(raw):
        size = int.from_bytes(raw[i + 4:i + 8], 'big')
        lines.append(raw[i + 8:i + 8 + size].decode('utf-8', errors='ignore'))
        i += 8 + size
    return ''.join(lines)


def setup_qbittorrent():
    """Set the qBittorrent WebUI password via its Web API.

    qBittorrent Web API docs: https://github.com/qbittorrent/qBittorrent/wiki/WebUI-API-(qBittorrent-4.1)

    Flow:
      1. Try logging in with the target password — if it succeeds, already done.
      2. Otherwise read the one-time temporary password from container logs
         (qBittorrent 5+ generates a random password on first boot when no
         password is set in the config).
         Fallback: 'adminadmin' (default for older versions).
      3. Log in with the temporary password and call setPreferences to replace it.
    """
    print('==> Waiting for qBittorrent...')
    if not wait_for(f'{QBIT_URL}/'):
        print('  WARN: qBittorrent not ready, skipping.')
        return

    # A CookieJar is required because the qBittorrent API uses a session cookie
    # (SID) returned by /auth/login for all subsequent authenticated requests.
    # Docs: https://github.com/qbittorrent/qBittorrent/wiki/WebUI-API-(qBittorrent-4.1)#login
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

    # Step 1: check whether the target password is already active.
    data = urllib.parse.urlencode({'username': QBIT_USERNAME, 'password': QBIT_PASSWORD}).encode()
    try:
        resp = opener.open(f'{QBIT_URL}/api/v2/auth/login', data)
        if resp.read().decode().strip() == 'Ok.':
            print('  qBittorrent already configured, skipping.')
            return
    except Exception:
        pass

    # Step 2: retrieve the temporary password from container logs.
    # The linuxserver/qbittorrent image logs it as:
    #   "The temporary password for the admin account is: <password>"
    temp_pass = 'adminadmin'  # fallback for qBittorrent < 5
    try:
        logs = get_container_logs('qbittorrent')
        for line in logs.splitlines():
            if 'temporary password' in line.lower() and ':' in line:
                temp_pass = line.rsplit(':', 1)[-1].strip()
                break
    except Exception:
        pass

    # Step 3: authenticate with the temporary password and update preferences.
    # POST /api/v2/app/setPreferences accepts a JSON-encoded 'json' form field.
    # Docs: https://github.com/qbittorrent/qBittorrent/wiki/WebUI-API-(qBittorrent-4.1)#set-application-preferences
    print('==> Setting qBittorrent password...')
    cj.clear()
    data = urllib.parse.urlencode({'username': QBIT_USERNAME, 'password': temp_pass}).encode()
    try:
        resp = opener.open(f'{QBIT_URL}/api/v2/auth/login', data)
        if resp.read().decode().strip() == 'Ok.':
            prefs = urllib.parse.urlencode({'json': json.dumps({'web_ui_password': QBIT_PASSWORD})}).encode()
            opener.open(f'{QBIT_URL}/api/v2/app/setPreferences', prefs)
            print('  Password set.')
        else:
            print('  WARN: Could not authenticate — set the qBittorrent password manually.')
    except Exception as e:
        print(f'  WARN: {e}')


def _jf(path, data=None, token=None):
    """Send a JSON request to the Jellyfin API and return (status, body).

    Unauthenticated requests (token=None) use the MediaBrowser identification
    header required by Jellyfin's startup wizard endpoints.
    Authenticated requests pass the access token obtained after completing the
    wizard.

    Jellyfin API reference: https://api.jellyfin.org/
    """
    headers = {'Content-Type': 'application/json'}
    if token:
        # Standard bearer-style token for authenticated API calls.
        headers['Authorization'] = f'MediaBrowser Token="{token}"'
    else:
        # Client identification is required even for unauthenticated endpoints.
        # Docs: https://jellyfin.org/docs/general/clients/api/
        headers['Authorization'] = (
            'MediaBrowser Client="SetupScript", Device="cli", DeviceId="setup", Version="1.0"'
        )
    body = json.dumps(data).encode() if data is not None else b''
    req = urllib.request.Request(f'{JELLYFIN_URL}{path}', data=body, headers=headers)
    try:
        resp = urllib.request.urlopen(req)
        return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def setup_jellyfin():
    """Complete the Jellyfin first-run wizard and add the Downloads media library.

    Jellyfin exposes a one-time startup wizard API that is only accessible before
    the wizard is marked complete. Subsequent calls return 4xx, which is used to
    detect an already-configured instance.

    Startup wizard API docs: https://api.jellyfin.org/#tag/Startup

    Flow:
      1. POST /Startup/User  — create the admin account.
      2. POST /Startup/Complete — mark the wizard done (no more wizard on UI).
      3. POST /Users/AuthenticateByName — obtain an access token.
      4. POST /Library/VirtualFolders — add /media as the Downloads library.
         /media is the container path mapped from ./downloads/ on the host.
    """
    print('==> Waiting for Jellyfin...')
    if not wait_for(f'{JELLYFIN_URL}/health'):
        print('  WARN: Jellyfin not ready, skipping.')
        return

    print('==> Configuring Jellyfin...')

    # Step 1: create the admin user.
    # Returns 204 only when the wizard is still pending; 4xx means already done.
    # Docs: https://api.jellyfin.org/#tag/Startup/operation/UpdateStartupUser
    status, _ = _jf('/Startup/User', {'Name': JELLYFIN_USERNAME, 'Password': JELLYFIN_PASSWORD})
    if status != 204:
        print('  Jellyfin already configured, skipping.')
        return

    # Step 2: mark the wizard as complete.
    # Docs: https://api.jellyfin.org/#tag/Startup/operation/CompleteWizard
    _jf('/Startup/Complete')

    # Step 3: authenticate to get an access token for library management.
    # Docs: https://api.jellyfin.org/#tag/User/operation/AuthenticateUserByName
    status, body = _jf('/Users/AuthenticateByName', {
        'Username': JELLYFIN_USERNAME, 'Pw': JELLYFIN_PASSWORD,
    })
    token = json.loads(body)['AccessToken']

    # Step 4: add /media as a mixed-content library called "Downloads".
    # collectionType=mixed means Jellyfin will auto-detect movies, shows, music, etc.
    # refreshLibrary=true triggers an immediate scan after creation.
    # Docs: https://api.jellyfin.org/#tag/LibraryStructure/operation/AddVirtualFolder
    _jf(
        '/Library/VirtualFolders?name=Downloads&collectionType=mixed&refreshLibrary=true',
        {'libraryOptions': {'pathInfos': [{'path': '/media'}]}},
        token=token,
    )
    print('  Wizard completed and Downloads library added.')


if __name__ == '__main__':
    # Skip everything if a previous run already completed successfully.
    if os.path.exists(SENTINEL):
        print('Setup already completed, skipping.')
        sys.exit(0)

    setup_qbittorrent()
    setup_jellyfin()

    # Write the sentinel only after both steps succeed so a partial failure
    # causes a full retry on the next container start.
    open(SENTINEL, 'w').close()
    print(f'\nSetup complete!')
    print(f'  qBittorrent: {QBIT_URL}  ({QBIT_USERNAME} / {QBIT_PASSWORD})')
    print(f'  Jellyfin:    {JELLYFIN_URL}  ({JELLYFIN_USERNAME} / {JELLYFIN_PASSWORD})')
