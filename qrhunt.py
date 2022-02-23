#!/usr/bin/python3.9
import os
import os.path
import asyncio
import json
import glob
import time
import logging
from decimal import Decimal
from typing import Any, Dict, Optional
from textwrap import dedent


import aioprocessing
import base58
from aiohttp import web
from google.protobuf import json_format

import mc_util
from forest.core import (
    Message,
    QuestionBot,
    Response,
    app,
    hide,
    utils,
    requires_admin,
    is_admin,
)
from forest.pdictng import get_safe_key, aPersistDict
from mc_util import mob2pmob, pmob2mob

FEE = int(1e12 * 0.0004)
from qr_labeler import QRLabeler


class MobFriend(QuestionBot):
    def __init__(self) -> None:
        self.seen_phashes = aPersistDict("seen_phashes")
        self.seen_ahashes = aPersistDict("seen_ahashes")
        self.seen_valhashes = aPersistDict("seen_valhashes")
        self.user_claims = aPersistDict("user_claims")
        self.user_points = aPersistDict("user_points")
        self.user_total = aPersistDict("user_total")
        self.notes = aPersistDict("notes")
        self.user_images: dict[str, str] = {}
        self.labeler = QRLabeler()
        self.processing_lock = asyncio.Lock()
        self.epoch = 1644895000
        super().__init__()

    async def handle_message(self, message: Message) -> Response:
        if (
            message.attachments
            and len(message.attachments)
            and message.arg0 != "set_profile"
        ):
            await self.send_message(
                message.uuid, "Thanks for your submission! Let me take a look!"
            )
            attachment_info = message.attachments[0]
            attachment_path = attachment_info.get("fileName")
            timestamp = attachment_info.get("uploadTimestamp")
            download_success = False
            download_path = "/dev/null"
            for _ in range(6):
                if attachment_path is None:
                    attachment_paths = glob.glob(
                        f"/tmp/unnamed_attachment_{timestamp}.*"
                    )
                    if len(attachment_paths) > 0:
                        attachment_path = attachment_paths.pop()
                        download_path = self.user_images[
                            message.uuid
                        ] = f"{attachment_path}"
                else:
                    download_path = self.user_images[
                        message.uuid
                    ] = f"/tmp/{attachment_path}"
                if not (
                    os.path.exists(download_path)
                    and os.path.getsize(download_path) == attachment_info.get("size", 1)
                ):
                    await asyncio.sleep(4)
                else:
                    download_success = True
                    break
                download_success = False

            attachment = self.user_images[message.uuid] if download_success else None
            if attachment:
                message.attachment_path = attachment
                return await self.do_check(message)
        return await super().handle_message(message)

    async def do_points(self, msg: Message) -> Response:
        """points
        Returns how many points a user has gained!"""
        points = await self.user_points.get(msg.uuid, 0)
        return f"You have {points} points!"

    async def do_check(self, msg: Message) -> Response:
        user = msg.uuid
        user_claims = await self.user_claims.get(user)
        if not user_claims:
            await self.send_message(
                user,
                "\n\n".join(
                    (
                        "Welcome to my scavenger hunt! It looks like you're submitting for the first time."
                        "I'm about to take a look at the image you just sent! It might take me a few minutes, but I'll look for a few items in the image, and if this image helps me, you'll earn some points!"
                        "At this point in time, we're looking for QR codes!",
                    )
                ),
            )
        await self.user_claims.increment(user, 1)
        if (user_claims or 0) > 100:
            return "Please use the 'unlock' command to prove you're a human!"
        queue = aioprocessing.AioQueue()
        async with self.processing_lock:
            p = aioprocessing.AioProcess(
                target=self.labeler.process_file, args=(msg.attachment_path, queue)
            )
            p.start()  # pylint: disable=no-member
            try:
                result = await asyncio.wait_for(queue.coro_get(), timeout=30)
                # ['YES', '3jQc6afFoZ3d3jWR9DyEoz1JVbhuLZHAhAu2iHFVWYiGDf2vuNZVNFTC8i7xm5rBLkAkkc1W3SVZ82CZG2fDQCXVXZBz9X1qWVrYMuVWXbSmXvvutgbjHBqBTJQrQQc5Uj9HorArfDfp4ucz', '', '/tmp/rendered87860lsy.png', '9a61649e9971cea6', '00003c3c3c3c0000']
                squareish, val0, val1, output_path, ahash, phash = result
                await self.send_message(
                    user,
                    f"Check this out!\ndebug: {str(dict(squareish=squareish, phash=phash, ahash=ahash, value=val0 or val1))}",
                    attachments=[output_path],
                )
                # await self.send_message(user, str(result))
                if (
                    phash in await self.seen_phashes.keys()
                    or ahash in await self.seen_ahashes.keys()
                ):
                    return "I've already seen this image!"
                if val0 or val1:
                    safe_val = get_safe_key(val0 or val1 or squareish)
                    if safe_val in await self.seen_valhashes.keys():
                        return "Hey, this value looks pretty familiar..."
                    await self.seen_valhashes.set(safe_val, user)
                points = [
                    2 ** (i) if x not in [None, ""] else 0
                    for (i, x) in enumerate((squareish, val0, val1))
                ]
                await self.seen_phashes.set(phash, user)
                await self.seen_ahashes.set(ahash, user)
                await asyncio.wait_for(p.coro_join(), timeout=30)
                if sum(points) == 0:
                    return "Sorry, that's not very helpful."
                await self.user_points.increment(user, sum(points))
                if points == 1:
                    return "That's... close. You can have one point for a vaguely square-ish object."
                return f"You've earned {sum(points)} points!\nYou now have {await self.user_points.get(user)} points!\nThank you for your contribution!"
                # pylint: disable=no-member
            except asyncio.TimeoutError:
                await self.send_message(user, "Sorry, no luck!")

    async def do_unlock(self, msg: Message) -> Response:
        """unlock
        Presents a CAPTCHA challenge to the user, then resets the claim counter from 100 to 0.
        """
        user = msg.uuid
        challenged = await self.do_challenge(msg)
        await self.user_total.increment(user, await self.user_claims.get(user))
        await self.user_claims.set(user, 1)
        return challenged

    # pylint: disable=too-many-branches,too-many-return-statements
    async def default(self, message: Message) -> Response:
        """Handles everything else."""
        msg, code = message, message.arg0
        if code == "?":
            code = msg.arg0 = "help"
        elif code == "y":
            return await self.do_yes(msg)
        elif code == "n":
            return await self.do_no(msg)
        if msg.arg0 and msg.arg0.isalnum() and len(msg.arg0) > 100 and not msg.tokens:
            msg.arg1 = msg.full_text
            return await self.do_check(msg)
        if (
            msg.arg0  # if there's a word
            and len(msg.arg0) > 1  # not a character
            and any(
                msg.arg0 in key.lower() for key in await self.notes.keys()
            )  # and it shows up as a keyword for a note
            and "help" not in msg.arg0.lower()  # and it's not 'help'
            and (
                await self.ask_yesno_question(
                    msg.uuid,
                    f"There are one or more notes matching {msg.arg0}.\n\nWould you like to view them?",
                )
            )
        ):
            # ask for confirmation and then return all notes
            for keywords in self.notes.dict_:
                if msg.arg0 in keywords.lower():
                    await self.send_message(msg.uuid, await self.notes.get(keywords))
        elif msg.arg0:
            await self.send_message(
                utils.get_secret("ADMIN"), f"{msg.uuid} says '{msg.full_text}'"
            )
            return "\n\n".join(
                [
                    "Hi, I'm MOBot!",
                    self.documented_commands(),
                    "Today I'm hunting for QR codes! If you send me QR codes (or things that look close enough) you can earn points!\nCollecting enough points will unlock secret levels and special bonuses!",
                ]
            )
        return None


if __name__ == "__main__":

    @app.on_startup.append
    async def start_wrapper(out_app: web.Application) -> None:
        out_app["bot"] = MobFriend()

    web.run_app(app, port=8080, host="0.0.0.0", access_log=None)
