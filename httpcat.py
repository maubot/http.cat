# httpcat - A maubot that posts http.cats on request.
# Copyright (C) 2020 Tulir Asokan
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
from typing import Dict, Type, Optional
from io import BytesIO
import asyncio

from aiohttp import ClientResponseError

from PIL import Image
from mimetypes import guess_extension

from mautrix.util.config import BaseProxyConfig, ConfigUpdateHelper
from mautrix.types import MediaMessageEventContent, MessageType, ImageInfo

from maubot import Plugin, MessageEvent
from maubot.handlers import command


class Config(BaseProxyConfig):
    def do_update(self, helper: ConfigUpdateHelper) -> None:
        helper.copy("command")
        helper.copy("url")
        helper.copy("reuploaded_cats")


class HTTPCatBot(Plugin):
    cats: Dict[int, MediaMessageEventContent]
    reupload_lock: asyncio.Lock

    async def start(self):
        self.config.load_and_update()
        self.cats = {}
        self.reupload_lock = asyncio.Lock()

    async def _reupload(self, status: int) -> Optional[MediaMessageEventContent]:
        url = self.config["url"].format(status=status)
        self.log.info(f"Reuploading {url}")
        resp = await self.http.get(url)
        if resp.status != 200:
            resp.raise_for_status()
        data = await resp.read()
        img = Image.open(BytesIO(data))
        width, height = img.size
        mimetype = Image.MIME[img.format]
        filename = f"{status}{guess_extension(mimetype)}"
        mxc = await self.client.upload_media(data, mimetype, filename=filename)
        return MediaMessageEventContent(msgtype=MessageType.IMAGE, body=filename, url=mxc,
                                        info=ImageInfo(mimetype=mimetype, size=len(data),
                                                       width=width, height=height))

    async def get(self, status: int) -> MediaMessageEventContent:
        try:
            return self.cats[status]
        except KeyError:
            pass
        try:
            cat = MediaMessageEventContent.deserialize(self.config["reuploaded_cats"][status])
            self.cats[status] = cat
            return cat
        except KeyError:
            pass
        try:
            async with self.reupload_lock:
                try:
                    return self.cats[status]
                except KeyError:
                    pass
                cat = await self._reupload(status)
                self.cats[status] = cat
                self.config["reuploaded_cats"][status] = cat.serialize()
                self.config.save()
            return cat
        except ClientResponseError as e:
            raise KeyError(f"Failed to get 🐈️ for HTTP {status}: HTTP {e.status}") from e

    @command.new(name=lambda self: self.config["command"])
    @command.argument("status", parser=int)
    async def post_cat(self, evt: MessageEvent, status: int) -> None:
        try:
            cat = await self.get(status)
            await evt.respond(cat)
        except KeyError as e:
            await evt.reply(str(e)[1:-1])

    @classmethod
    def get_config_class(cls) -> Type[BaseProxyConfig]:
        return Config
