import asyncio
import random

from typing import Optional
from contextlib import asynccontextmanager
from urllib.parse import urlsplit
from loguru import logger
from pathlib import Path
from playwright.async_api import (
    Page,
    Route,
    Request,
    Response,
    async_playwright,
    JSHandle,
    BrowserContext,
    Browser,
    PlaywrightContextManager,
)
from playwright._impl._api_types import Error as PlaywrightError

from .data import CookieManager, StreamResponse


SESSION_TOKEN_KEY = "__Secure-next-auth.session-token"
CF_CLEARANCE_KEY = "cf_clearance"


class ChatSessionException(Exception):
    pass


class ChatSession:
    def __init__(
        self,
        *,
        api: str = "https://chat.openai.com/",
        proxies: Optional[str] = None,
        cookie_manager: CookieManager = CookieManager(),
        timeout: int = 30,
    ) -> None:
        self.api_url = api
        self.proxies = proxies
        self.cookie_manager = cookie_manager
        self.timeout = timeout
        self.content: BrowserContext = None
        self.browser: Browser = None
        self.playwright: PlaywrightContextManager = None
        self.cf_clearance: str = ""
        self.page: Page = None
        self.available = False
        self.running = False

    async def set_status(self, status: bool):
        self.available = status

    async def get_status(self):
        return self.available

    async def __aenter__(self) -> "ChatSession":
        """Enter Async Context Manager"""
        self.page = await self.init_page()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        """Exit Async Context Manager"""
        await self.playwright_close()

    async def playwright_start(self):
        """Start Playwright Browser and Context, called when start"""
        self.playwright: PlaywrightContextManager = async_playwright()
        playwright = await self.playwright.start()
        self.browser = await playwright.chromium.launch(
            headless=True,
            proxy={"server": self.proxies}
            if self.proxies
            else None,  # your proxy
        )
        # ua = None
        ua = f"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:72.0) Gecko/20100101 Firefox/{self.browser.version}"
        # ua = f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{self.browser.version} Safari/537.36"
        self.content = await self.browser.new_context(user_agent=ua)

    async def set_cookie(self, key: str, value: str, expires: float = -1):
        """Set Cookie"""
        await self.content.add_cookies(
            [
                {
                    "name": key,
                    "value": value,
                    "domain": "chat.openai.com",
                    "path": "/",
                    "expires": expires,
                    "httpOnly": False,
                    "secure": True,
                }
            ]
        )

    async def get_cookie(self, key: str) -> str:
        """Get Cookie"""
        cookies = await self.content.cookies()
        for cookie in cookies:
            if cookie["name"] == key:
                return cookie["value"]
        return ""

    async def playwright_close(self):
        """Close Playwright Browser and Context, called when stop"""
        await self.content.close()
        await self.browser.close()
        await self.playwright.__aexit__()

    async def init_page(self, restart: bool = False):
        """Init Page, called when start"""
        if not restart and self.page:
            return self.page
        elif restart and self.page:
            self.cookie_manager.delete_cf_clearance(self.cf_clearance)
            await self.wait_for_task()
            await self.page.close()
            await self.playwright_close()
        await self.playwright_start()
        page = await self.content.new_page()
        self.page = page
        await page.add_init_script(path=Path(__file__).parent / "js" / "preload.js")
        await self.get_cf_cookies()
        await page.expose_function("set_cookie", self.set_cookie)
        await page.expose_function("get_cookie", self.get_cookie)
        return page

    async def get_cf_cookies(self, retry: int = 20, wait: bool = False) -> None:
        await self.set_status(False)
        if wait:
            await self.wait_for_task()
        logger.debug("Start get Cloudflare cookies")
        await self.content.add_cookies(
            [
                {
                    "name": CF_CLEARANCE_KEY,
                    "value": self.cookie_manager.cf_clearance,  # Get cf_clearance from cookie_manager
                    "domain": ".chat.openai.com",
                    "path": "/",
                    "expires": -1,
                    "httpOnly": False,
                    "secure": True,
                },
            ]
        )
        await self.page.goto("https://chat.openai.com/backend-api/not_found")
        for i in range(retry):
            try:
                await self.page.wait_for_load_state("domcontentloaded")
                cf = self.page.locator("text=detail")
                if await cf.is_visible():
                    break
                button = self.page.get_by_role(
                    "button", name="Verify you are human"
                )  # Get button of old cf
                if await button.is_visible() and await button.count():
                    await button.click()
                label = self.page.locator(
                    'iframe[title="Widget containing a Cloudflare security challenge"]'
                )
                if await label.is_visible() and await label.count():
                    label = label.locator(
                        "nth=0 >> internal:control=enter-frame >> label input"
                    )
                if await label.is_visible() and await label.count():
                    await label.click()
                await asyncio.sleep(1)
            except Exception:
                logger.debug(f"[{i}/{retry}] Wait for Cloudflare cookies...")
                await asyncio.sleep(1)
        else:
            logger.error("Get Cloudflare cookies failed")
            asyncio.ensure_future(self.get_cf_cookies())
            return
        await self.set_status(True)
        self.cf_clearance = await self.get_cookie(CF_CLEARANCE_KEY)
        self.cookie_manager.save_cf_clearance(self.cf_clearance)
        logger.debug("Get Cloudflare cookies success")

    async def wait_for_task(self, timeout: int = 60):
        """Wait for task, called when restart"""
        logger.debug("Wait for task...")
        await self.set_status(False)
        await self.page.evaluate(
            "([timeout]) => waitForNoFetch(timeout)", [timeout * 1000]
        )

    @asynccontextmanager
    async def fetch(
        self,
        method: str,
        url: str,
        headers={},
        data=None,
        cookies: dict = {},
        timeout: int = 30,
    ):
        """Fetch API"""
        if cookies.__len__():
            self.running = True
            for key, value in cookies.items():
                await self.set_cookie(key, value)
        controller = await self.page.evaluate_handle("new AbortController()")
        # Execute the JavaScript code in the page
        # to send the request directly on the current page
        # and use Streams API to process the request result
        response = await controller.evaluate_handle(
            "(controller, [url, method, headers, data]) => {return trackedFetch(url, {method: method, headers: headers, body: data, signal: controller.signal})}",
            [url, method, headers, data if data else None],
        )
        resp = await StreamResponse.wait_for_headers(
            controller=controller, response=response, timeout=timeout
        )
        yield resp
        self.running = False
        await controller.evaluate("--fetchCounter")
        await resp.stop()

    @asynccontextmanager
    async def _call_api(
        self,
        method: str,
        url: str,
        headers={},
        data=None,
        session_token: str = None,
        timeout: int = 10,
    ):
        """Call API"""
        try:
            logger.debug(f"Call API: {method} {url}")
            if session_token:
                self.running = True
                await self.set_cookie(SESSION_TOKEN_KEY, session_token)
            else:
                await self.set_cookie(SESSION_TOKEN_KEY, "", expires=0)
            async with self.fetch(
                method,
                url,
                headers=headers,
                data=data,
                timeout=timeout,
            ) as response:
                if response.status == 403:
                    self.cookie_manager.delete_cf_clearance(self.cf_clearance)
                    logger.warning(
                        "Cloudflare cookies had expired, trying to get new Cloudflare cookies..."
                    )
                    asyncio.ensure_future(self.get_cf_cookies(wait=True))
                elif response.status == 429 and "/api/auth/session" in url:
                    logger.warning(
                        "Too many session requests, trying to get new Cloudflare cookies..."
                    )
                    response.status = 403
                    if await self.get_status():
                        asyncio.ensure_future(self.init_page(restart=True))
                    yield response
                    return
                if session_token:
                    if token := await self.get_cookie(SESSION_TOKEN_KEY):
                        response.headers[
                            "set-cookie"
                        ] = f"{SESSION_TOKEN_KEY}={token}; path=/; max-age=31536000; secure; httponly"
                yield response
        except PlaywrightError as e:
            logger.error(f"Playwright Error: {e.message}")
            yield StreamResponse(status=403)
        # except Exception as e:
        #     logger.opt(exception=e).error("Call API failed")


class SessionManager:
    def __init__(
        self,
        proxies: str = None,
        cookie_manager: CookieManager = CookieManager(),
        limit=4,
    ):
        self.limit = limit
        self.sessions = [
            ChatSession(proxies=proxies, cookie_manager=cookie_manager)
            for _ in range(limit)
        ]
        for session in self.sessions:
            asyncio.ensure_future(session.init_page())

    async def get_sessions(self):
        """Get available sessions"""
        return [
            session
            for session in self.sessions
            if (await session.get_status() and not session.running)
        ]

    async def get_session(self):
        """Get a random available session"""
        sessions = await self.get_sessions()
        if sessions:
            return random.choice(sessions)
        else:
            await asyncio.sleep(3)
            return await self.get_session()

    @asynccontextmanager
    async def call_api(
        self,
        method: str,
        url: str,
        headers: dict,
        data,
        session_token: str,
        first=True,
    ):
        """Call API with a random session"""
        session = await self.get_session()
        url_split = urlsplit(url)
        # Ignore session_token when calling API that does not need to use session_token
        if (
            not session_token
            or headers.get("authorization")
            or not (
                url_split.path.endswith(("/", "session"))
                or url_split.path.startswith(
                    ("/_next/data", "/c/", "/api/auth/callback/auth0")
                )
            )
        ):
            session_token = None
        async with session._call_api(
            method, url, headers, data=data, session_token=session_token
        ) as resp:
            if resp.status == 403:
                if not first:
                    resp.status = 499
                    yield resp
            else:
                yield resp
        if resp.status == 403 and first:
            # Retry once
            async with self.call_api(
                method, url, headers, data, session_token, False
            ) as resp:
                yield resp
