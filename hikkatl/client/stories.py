import asyncio
import functools
import io
import os
import re
import tempfile
import typing

from ..tl import types, functions
from .. import utils, hints

if typing.TYPE_CHECKING:
    from .telegramclient import TelegramClient


class StoriesMethods:
    # region Public methods

    async def send_story(
        self: "TelegramClient",
        media: "types.TypeInputMedia",
        *,
        caption: typing.Union[str, typing.Sequence[str]] = None,
        entities: typing.Optional[typing.List[types.TypeMessageEntity]] = None,
        pinned: bool = False,
        noforwards: bool = True,
        privacy_rules: typing.Optional[typing.List[types.TypeInputPrivacyRule]] = None,
        period: int = 86400,
        parse_mode: str = (),
        media_areas: typing.Optional[typing.List[types.TypeMediaArea]] = None,
        **kwargs,
    ) -> "types.StoryItem":
        """
        Sends a story.

        Arguments
            media (`str` | `bytes` | `file` | `media`):
                The photo to send, which can be one of:

                * A local file path to an in-disk file. The file name
                  will be the path's base name.

                * A `bytes` byte array with the file's data to send
                  (for example, by using ``text.encode('utf-8')``).
                  A default file name will be used.

                * A bytes `io.IOBase` stream over the file to send
                  (for example, by using ``open(file, 'rb')``).
                  Its ``.name`` property will be used for the file name,
                  or a default if it doesn't have one.

                * An external URL to a file over the internet. This will
                  send the file as "external" media, and Telegram is the
                  one that will fetch the media and send it.

                * A Bot API-like ``file_id``. You can convert previously
                  sent media to file IDs for later reusing with
                  `telethon.utils.pack_bot_file_id`.

                * A handle to an existing file (for example, if you sent a
                  message with media before, you can use its ``message.media``
                  as a file here).

                * A handle to an uploaded file (from `upload_file`).

                * A :tl:`InputMedia` instance.

            caption (`str`, optional):
                Optional caption for the sent media message.

            entities (`list`, optional):
                Optional list of message entities for ``caption``.

            pinned (`bool`, optional):
                Whether the story should be pinned.

            noforwards (`bool`, optional):
                Whether the forwards should be disabled.

            privacy_rules (`list`, optional):
                Optional list of privacy rules for the story.

            period (`int`, optional):
                The period in seconds for which the story should be visible.
                Default is 24 hours.
            
            media_areas (`list`, optional):
                Optional list of media areas for the story.

        Returns
            The `<telethon.tl.StoryItem>`
            containing the sent story.

        Example
            .. code-block:: python

                # Normal files like photos
                await client.send_story('/my/photos/zoo.jpg', caption="It's me in the zoo!")
        """
        if not media:
            raise TypeError("Cannot use {!r} as story".format(media))

        if not caption:
            caption = ""

        if entities is not None:
            msg_entities = entities
        else:
            caption, msg_entities = await self._parse_message_text(caption, parse_mode)

        if isinstance(media, str) and re.match("https?://", media):
            import requests

            name = media.split("/")[-1]
            media = io.BytesIO(
                (
                    await asyncio.get_event_loop().run_in_executor(
                        None,
                        functools.partial(requests.get, media),
                    )
                ).content
            )
            media.name = name
        elif isinstance(media, (types.InputFile, types.InputFileBig)):
            name = media.name
            media = io.BytesIO(await self.download_file(media))
            media.name = name
        elif not isinstance(media, str) or os.path.isfile(media):
            media = open(media, "rb")
        else:
            bot_file = utils.resolve_bot_file_id(media)
            if bot_file:
                media = utils.get_input_media(bot_file, ttl=None)

            name = (
                "story.jpg" if isinstance(media, types.InputMediaPhoto) else "story.mp4"
            )
            media = io.BytesIO(await self.download_file(media))
            media.name = name

        video = False
        if isinstance(media, io.BytesIO) and (
            media.name.endswith(("mp4", "mkv", "webm", "avi", "mov", "m4v", "gif"))
        ):
            try:
                from ffmpeg.asyncio import FFmpeg
            except ImportError:
                raise RuntimeError(
                    "FFmpeg (PyPI python-ffmpeg) is required to send video stories"
                )

            video = True
            with tempfile.TemporaryDirectory() as tmpdir:
                with open(os.path.join(tmpdir, "in.mp4"), "wb") as f:
                    f.write(media.read())

                width, height = map(
                    lambda line: int(line.split("=")[1]),
                    (
                        await FFmpeg("ffprobe")
                        .output(
                            os.path.join(tmpdir, "in.mp4"),
                            {
                                "v": "quiet",
                                "show_entries": "stream=width,height",
                                "of": "default=noprint_wrappers=1",
                            },
                        )
                        .execute()
                    )
                    .decode()
                    .splitlines(),
                )

                duration = round(
                    float(
                        (
                            await FFmpeg("ffprobe")
                            .option("v", "quiet")
                            .option("show_entries", "format=duration")
                            .option("of", "default=noprint_wrappers=1")
                            .input(os.path.join(tmpdir, "in.mp4"))
                            .execute()
                        )
                        .decode()
                        .split("=")[1]
                        .strip()
                    ),
                    2,
                )

                if width > height:
                    new_width = int(height * 720 / 1280)
                    new_height = height
                else:
                    new_width = width
                    new_height = int(width * 1280 / 720)

                ffmpeg = (
                    FFmpeg()
                    .option("y")
                    .option("hwaccel", "auto")
                    .input(os.path.join(tmpdir, "in.mp4"))
                    .output(
                        os.path.join(tmpdir, "out.mp4"),
                        {
                            "preset": "superfast",
                            "s": "hd720",
                            "crf": 24,
                            "vcodec": "libx264",
                            "acodec": "aac",
                            "vf": f"crop={new_width}:{new_height},scale=720:1280",
                        },
                        f="mp4",
                    )
                )

                await ffmpeg.execute()

                with open(os.path.join(tmpdir, "out.mp4"), "rb") as f:
                    media = io.BytesIO(f.read())
                    media.name = "story.mp4"
        elif isinstance(media, io.BytesIO) and media.name.endswith(
            ("jpg", "jpeg", "png", "webp")
        ):
            try:
                from PIL import Image
            except ImportError:
                raise RuntimeError("Pillow is required to send image stories")

            media.name = f"story.{media.name.split('.')[-1]}"
            image = Image.open(media)
            width, height = image.size
            if width > height:
                new_width = int(height * 720 / 1280)
                new_height = height
            else:
                new_width = width
                new_height = int(width * 1280 / 720)

            image = image.crop(
                (
                    (width - new_width) // 2,
                    (height - new_height) // 2,
                    (width + new_width) // 2,
                    (height + new_height) // 2,
                )
            )
            image = image.resize((1080, 1920), Image.ANTIALIAS)

            media = io.BytesIO()
            media.name = "image.jpg"
            image.save(media, format="JPEG")
            media.seek(0)
        else:
            raise TypeError("Cannot use {!r} as story".format(media))

        request = functions.stories.SendStoryRequest(
            utils.get_input_media(
                await self.upload_file(media, file_name=media.name),
                attributes=[
                    types.DocumentAttributeVideo(w=720, h=1280, duration=duration)
                ]
                if video
                else None,
                is_photo=not video,
            ),
            caption=caption,
            entities=msg_entities or [],
            pinned=pinned,
            noforwards=noforwards,
            privacy_rules=privacy_rules or [types.InputPrivacyValueAllowAll()],
            period=period,
            media_areas=media_areas or [],
        )

        return self._get_response_message(request, await self(request), input_chat=None)

    async def delete_stories(
        self: "TelegramClient",
        stories: "typing.Sequence[hints.StoryItemLike]",
    ) -> typing.List[int]:
        return await self(
            functions.stories.DeleteStoriesRequest(
                id=[utils.get_input_story_id(story) for story in stories]
            )
        )

    async def get_all_stories(
        self: "TelegramClient",
        next: bool = True,
        hidden: bool = True,
        state: typing.Optional[str] = None,
    ) -> types.stories.AllStories:
        return await self(
            functions.stories.GetAllStoriesRequest(
                next=next,
                hidden=hidden,
                state=state,
            )
        )

    async def get_user_stories(
        self: "TelegramClient",
        user: "hints.EntityLike",
    ) -> types.stories.Stories:
        return await self(
            functions.stories.GetUserStoriesRequest(
                user_id=await self.get_input_entity(user),
            )
        )

    async def get_pinned_stories(
        self: "TelegramClient",
        user: "hints.EntityLike",
        offset_id: int = 0,
        limit: int = 100,
    ) -> types.stories.Stories:
        return await self(
            functions.stories.GetPinnedStoriesRequest(
                user_id=await self.get_input_entity(user),
                offset_id=offset_id,
                limit=limit,
            )
        )

    async def get_stories_archive(
        self: "TelegramClient",
        offset_id: int = 0,
        limit: int = 100,
    ) -> types.stories.Stories:
        return await self(
            functions.stories.GetStoriesArchiveRequest(
                offset_id=offset_id,
                limit=limit,
            )
        )

    async def get_stories_by_id(
        self: "TelegramClient",
        user: "hints.EntityLike",
        stories: "typing.Sequence[hints.StoryItemLike]",
    ) -> types.stories.Stories:
        return await self(
            functions.stories.GetStoriesByIdRequest(
                user_id=await self.get_input_entity(user),
                id=[utils.get_input_story_id(story) for story in stories],
            )
        )

    async def toggle_all_stories_hidden(
        self: "TelegramClient",
        hidden: bool = True,
    ) -> bool:
        return await self(
            functions.stories.ToggleAllStoriesHiddenRequest(
                hidden=hidden,
            )
        )

    async def read_stories(
        self: "TelegramClient",
        user: "hints.EntityLike",
        max_id: int,
    ) -> typing.List[int]:
        return await self(
            functions.stories.ReadStoriesRequest(
                user_id=await self.get_input_entity(user),
                max_id=max_id,
            )
        )

    async def increment_story_views(
        self: "TelegramClient",
        user: "hints.EntityLike",
        story: "hints.StoryItemLike",
    ) -> bool:
        return await self(
            functions.stories.IncrementStoryViewsRequest(
                user_id=await self.get_input_entity(user),
                id=utils.get_input_story_id(story),
            )
        )

    async def get_story_views(
        self: "TelegramClient",
        story: "hints.StoryItemLike",
        offset_date: int = 0,
        offset_id: int = 0,
        limit: int = 100,
    ) -> types.stories.StoryViews:
        return await self(
            functions.stories.GetStoryViewsListRequest(
                id=story,
                offset_date=offset_date,
                offset_id=offset_id,
                limit=limit,
            )
        )

    async def get_stories_views(
        self: "TelegramClient",
        stories: "typing.Sequence[hints.StoryItemLike]",
    ) -> types.stories.StoryViews:
        return await self(
            functions.stories.GetStoriesViewsRequest(
                id=stories,
            )
        )

    async def export_story_link(
        self: "TelegramClient",
        story: "hints.StoryItemLike",
    ) -> types.ExportedStoryLink:
        return await self(
            functions.stories.ExportStoryLinkRequest(
                id=story,
            )
        )

    async def report_story(
        self: "TelegramClient",
        user: "hints.EntityLike",
        stories: "typing.Sequence[hints.StoryItemLike]",
        reason: types.TypeReportReason,
        message: str,
    ) -> bool:
        return await self(
            functions.stories.ReportStoryRequest(
                user_id=await self.get_input_entity(user),
                id=[utils.get_input_story_id(story) for story in stories],
                reason=reason,
                message=message,
            )
        )

    # endregion
