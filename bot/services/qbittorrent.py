import httpx

from config import settings


class QBittorrentClient:
    def __init__(self):
        self._client = httpx.AsyncClient(base_url=settings.qbit_host)
        self._logged_in = False

    async def _login(self):
        resp = await self._client.post(
            "/api/v2/auth/login",
            data={"username": settings.qbit_username, "password": settings.qbit_password},
        )
        self._logged_in = resp.text == "Ok."
        return self._logged_in

    async def _ensure_logged_in(self):
        if not self._logged_in:
            await self._login()

    def _is_auth_failure(self, resp: httpx.Response) -> bool:
        return resp.status_code == 403 or resp.text.strip() in ("Forbidden", "")

    async def add_magnet(self, magnet: str, _retry: bool = True) -> bool:
        await self._ensure_logged_in()
        resp = await self._client.post(
            "/api/v2/torrents/add",
            data={"urls": magnet, "savepath": settings.download_path},
        )
        if self._is_auth_failure(resp) and _retry:
            self._logged_in = False
            return await self.add_magnet(magnet, _retry=False)
        return resp.status_code == 200

    async def add_torrent_file(self, content: bytes, _retry: bool = True) -> bool:
        await self._ensure_logged_in()
        resp = await self._client.post(
            "/api/v2/torrents/add",
            files={"torrents": ("file.torrent", content, "application/x-bittorrent")},
            data={"savepath": settings.download_path},
        )
        if self._is_auth_failure(resp) and _retry:
            self._logged_in = False
            return await self.add_torrent_file(content, _retry=False)
        return resp.status_code == 200

    async def get_torrents(self, _retry: bool = True) -> list[dict]:
        await self._ensure_logged_in()
        resp = await self._client.get("/api/v2/torrents/info")
        if self._is_auth_failure(resp) and _retry:
            self._logged_in = False
            return await self.get_torrents(_retry=False)
        return resp.json()


qbittorrent = QBittorrentClient()
