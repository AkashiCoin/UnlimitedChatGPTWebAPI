import asyncio
import random
import time

from pathlib import Path
from typing import Any, Dict
from playwright.async_api import JSHandle
from playwright._impl._api_types import Error
from pydantic import BaseModel, root_validator

try:
    import ujson as json
except ModuleNotFoundError:
    import json


class StreamResponseException(Exception):
    pass


class AsyncStreamIterator:
    def __init__(self, response: JSHandle, timeout: int = 30):
        self.response = response
        self.timeout = timeout
        self.reader: JSHandle = None

    def __aiter__(self):
        return self

    async def read(self):
        if not self.reader:
            self.reader = await self.response.evaluate_handle(
                "response => response.body.getReader()"
            )
        try:
            data = await self.reader.evaluate(
                "reader => reader.read().then(({value, done}) => { return {done, value: Array.from(value)} })"
            )
        except Error:
            data = {"done": True, "value": None}
        return data["done"], bytes(data["value"]) if data["value"] else b""

    async def __anext__(self):
        try:
            done, data = await asyncio.wait_for(self.read(), timeout=self.timeout)
            if done:
                if isinstance(self.response, JSHandle):
                    await self.response.dispose()
                    await self.reader.dispose()
                raise StopAsyncIteration
            return data
        except asyncio.TimeoutError:
            raise StopAsyncIteration


class StreamResponse:
    def __init__(
        self,
        status: int = 0,
        headers: Dict[str, Any] = {},
        controller: JSHandle = None,
        response: JSHandle = None,
        timeout: int = 30,
    ):
        self.status: int = status
        self.headers: Dict[str, Any] = headers
        self.controller: JSHandle = controller
        self.response: JSHandle = response
        self.timeout = timeout

    async def read(self):
        """Read response payload."""
        if self.response:
            arrayBuffer = await self.response.evaluate(
                "response => response.arrayBuffer().then((buffer) => Array.from(new Uint8Array(buffer)))"
            )
        else:
            raise StreamResponseException("Cannot read, response is None")
        return bytes(arrayBuffer)

    async def text(self, encoding="utf-8"):
        """Read response payload and decode."""
        return (await self.read()).decode(encoding=encoding)

    async def json(self):
        """Read response payload and decode as json."""
        return json.loads(await self.text())

    async def stop(self):
        """Stop the response stream."""
        if self.controller:
            await self.controller.evaluate("controller => controller.abort()")
            await self.controller.dispose()
        else:
            raise StreamResponseException("controller is None")

    def iter_chunked(self) -> AsyncStreamIterator:
        """Returns an asynchronous iterator that yields chunks"""
        if self.response:
            return AsyncStreamIterator(self.response, timeout=self.timeout)
        else:
            raise StreamResponseException("response is None")

    @staticmethod
    async def wait_for_headers(
        response: JSHandle, controller: JSHandle, timeout: int = 30
    ):
        """Wait for response headers."""
        if response:
            try:
                status = await response.evaluate("response => response.status")
                headers = await response.evaluate("response => get_headers(response)")
            except Error:
                raise StreamResponseException("Fetch Error, Please try again later")
            except Exception:
                raise StreamResponseException("Unknown Error")
        else:
            raise StreamResponseException("response is None")
        return StreamResponse(
            status=status,
            headers=headers,
            controller=controller,
            response=response,
            timeout=timeout,
        )


class CookieManager(BaseModel):
    cf_clearances: Dict[str, Dict[str, Any]] = {}
    puids: Dict[str, Dict[str, Any]] = {}
    __file_path = Path(__file__).parent / "cookies.json"

    @property
    def file_path(self) -> Path:
        return self.__class__.__file_path

    def get_puid(self, user_id):
        if user_id not in self.puids:
            return None

        puid_info = self.puids[user_id]
        expires = puid_info.get("expires")

        if expires is not None and expires < time.time():
            del self.puids[user_id]
            return None

        return puid_info.get("puid")

    @property
    def puid(self) -> str:
        """Return a random puid"""
        if not self.puids:
            return ""
        user_id = random.choice(list(self.puids.keys()))
        if puid := self.get_puid(user_id=user_id):
            return puid
        return self.puid

    def save_puid(self, puid: str) -> None:
        """Save a puid"""
        [user_id, token] = puid.split(":")
        expires: int = int(token.split("-")[0]) + 7 * 24 * 60 * 60
        self.puids[user_id] = {"puid": puid, "expires": expires}
        self.save()

    @property
    def cf_clearance(self) -> str:
        """Return a random cf_clearance"""
        if not self.cf_clearances:
            return ""
        cf_id = random.choice(list(self.cf_clearances.keys()))
        if cf_clearance := self.get_cf_clearance(cf_id=cf_id):
            return cf_clearance
        return self.cf_clearance

    def get_cf_clearance(self, cf_id):
        """Get a cf_clearance"""
        if cf_id not in self.cf_clearances:
            return None

        cf_clearance_info = self.cf_clearances[cf_id]
        expires = cf_clearance_info.get("expires")

        if expires is not None and expires < time.time():
            del self.cf_clearances[cf_id]
            return None

        return cf_clearance_info.get("cf_clearance")

    def save_cf_clearance(self, cf_clearance: str) -> None:
        """Save a cf_clearance"""
        if cf_clearance:
            [cf_id, expires, _, _, _, _] = cf_clearance.split("-")
            expires: int = int(expires) + 30 * 60
            self.cf_clearances[cf_id] = {
                "cf_clearance": cf_clearance,
                "expires": expires,
            }
            self.save()

    def delete_cf_clearance(self, cf_clearance: str) -> bool:
        """Delete a cf_clearance"""
        if cf_clearance:
            [cf_id, expires, _, _, _, _] = cf_clearance.split("-")
            if cf_id in self.cf_clearances:
                del self.cf_clearances[cf_id]
                self.save()
                return True
        return False

    @root_validator(pre=True)
    def init(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        if cls.__file_path.is_file():
            return json.loads(cls.__file_path.read_text("utf-8"))
        return values

    def save(self) -> None:
        """Save cookies to file"""
        self.file_path.write_text(self.json(), encoding="utf-8")
