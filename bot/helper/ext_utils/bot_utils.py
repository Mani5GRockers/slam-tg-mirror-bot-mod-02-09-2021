import logging
import re
import threading
import time
import math

from bot.helper.telegram_helper.bot_commands import BotCommands
from bot import dispatcher, download_dict, download_dict_lock, STATUS_LIMIT
from telegram import InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler
from bot.helper.telegram_helper import button_build, message_utils

LOGGER = logging.getLogger(__name__)

MAGNET_REGEX = r"magnet:\?xt=urn:btih:[a-zA-Z0-9]*"

URL_REGEX = r"(?:(?:https?|ftp):\/\/)?[\w/\-?=%.]+\.[\w/\-?=%.]+"

COUNT = 0
PAGE_NO = 1


class MirrorStatus:
    STATUS_UPLOADING = "𝗨𝗽𝗹𝗼𝗮𝗱𝗶𝗻𝗚...📤"
    STATUS_DOWNLOADING = "𝗗𝗼𝘄𝗻𝗹𝗼𝗮𝗱𝗶𝗻𝗚...📥"
    STATUS_CLONING = "Cloning...♻️"
    STATUS_WAITING = "𝗤𝘂𝗲𝘂𝗲𝗱...📝"
    STATUS_FAILED = "𝗙𝗮𝗶𝗹𝗲𝗱 🚫! 𝗖𝗹𝗲𝗮𝗻𝗶𝗻𝗴 𝗱𝗼𝘄𝗻𝗹𝗼𝗮𝗱..."
    STATUS_CANCELLED = "𝗖𝗮𝗻𝗰𝗲𝗹𝗹𝗲𝗱 ❎! 𝗖𝗹𝗲𝗮𝗻𝗶𝗻𝗴 𝗗𝗼𝘄𝗻𝗹𝗼𝗮𝗱..."
    STATUS_PAUSE = "Paused...⭕️"
    STATUS_ARCHIVING = "𝗔𝗿𝗰𝗵𝗶𝘃𝗶𝗻𝗴...🔐"
    STATUS_EXTRACTING = "𝗘𝘅𝘁𝗿𝗮𝗰𝘁𝗶𝗻𝗴...📂"


PROGRESS_MAX_SIZE = 100 // 8
PROGRESS_INCOMPLETE = ['🟩', '🟩', '🟩', '🟩', '🟩', '🟩']

SIZE_UNITS = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']


class setInterval:
    def __init__(self, interval, action):
        self.interval = interval
        self.action = action
        self.stopEvent = threading.Event()
        thread = threading.Thread(target=self.__setInterval)
        thread.start()

    def __setInterval(self):
        nextTime = time.time() + self.interval
        while not self.stopEvent.wait(nextTime - time.time()):
            nextTime += self.interval
            self.action()

    def cancel(self):
        self.stopEvent.set()


def get_readable_file_size(size_in_bytes) -> str:
    if size_in_bytes is None:
        return '0B'
    index = 0
    while size_in_bytes >= 1024:
        size_in_bytes /= 1024
        index += 1
    try:
        return f'{round(size_in_bytes, 2)}{SIZE_UNITS[index]}'
    except IndexError:
        return 'File too large'


def getDownloadByGid(gid):
    with download_dict_lock:
        for dl in download_dict.values():
            status = dl.status()
            if status != MirrorStatus.STATUS_ARCHIVING and status != MirrorStatus.STATUS_EXTRACTING:
                if dl.gid() == gid:
                    return dl
    return None


def getAllDownload():
    with download_dict_lock:
        for dlDetails in download_dict.values():
            if dlDetails.status() == MirrorStatus.STATUS_DOWNLOADING or dlDetails.status() == MirrorStatus.STATUS_WAITING:
                if dlDetails:
                    return dlDetails
    return None


def get_progress_bar_string(status):
    completed = status.processed_bytes() / 8
    total = status.size_raw() / 8
    if total == 0:
        p = 0
    else:
        p = round(completed * 100 / total)
    p = min(max(p, 0), 100)
    cFull = p // 8
    cPart = p % 8 - 1
    p_str = '🟩' * cFull
    if cPart >= 0:
        p_str += PROGRESS_INCOMPLETE[cPart]
    p_str += '🟨' * (PROGRESS_MAX_SIZE - cFull)
    p_str = f"[{p_str}]"
    return p_str


def get_readable_message():
    with download_dict_lock:
        msg = "\n✥═══ @Mani5GRockers ═══✥\n\n"
        INDEX = 0
        if STATUS_LIMIT is not None:
            dick_no = len(download_dict)
            global pages
            pages = math.ceil(dick_no/STATUS_LIMIT)
            if PAGE_NO > pages and pages != 0:
                globals()['COUNT'] -= STATUS_LIMIT
                globals()['PAGE_NO'] -= 1
        for download in list(download_dict.values()):
            INDEX += 1
            if INDEX > COUNT:
                msg += f"<b>🗂 𝗙𝗶𝗹𝗲𝗡𝗮𝗺𝗲 :</b> <code>{download.name()}</code>"
                msg += f"\n<b>🚦 𝐒𝐭𝐚𝐭𝐮𝐬 :</b> <i>{download.status()}</i>"
                if download.status() != MirrorStatus.STATUS_ARCHIVING and download.status() != MirrorStatus.STATUS_EXTRACTING:
                    msg += f"\n<code>{get_progress_bar_string(download)} 〘{download.progress()}〙</code>"
                    if download.status() == MirrorStatus.STATUS_CLONING:
                        msg += f"\n<b>♻️ Cloned:</b> <code>〘{get_readable_file_size(download.processed_bytes())}</code> of <code>{download.size()}〙</code>"
                    elif download.status() == MirrorStatus.STATUS_UPLOADING:
                        msg += f"\n<b>📤 𝐔𝐩𝐥𝐨𝐚𝐝𝐞𝐝 :</b> <code>〘{get_readable_file_size(download.processed_bytes())}</code> of <code>{download.size()}〙</code>"
                    else:
                        msg += f"\n<b>📥 𝐃𝐨𝐰𝐧𝐥𝐨𝐚𝐝𝐞𝐝 :</b> <code>〘{get_readable_file_size(download.processed_bytes())}</code> of <code>{download.size()}〙</code>"
                    msg += f"\n<b>🚀 𝐒𝐩𝐞𝐞𝐝 :</b> <code>〘{download.speed()}〙</code>" \
                            f", <b>⏳ 𝐄𝐓𝐀 :</b> <code>〘{download.eta()}〙</code> "
                    # if hasattr(download, 'is_torrent'):
                    try:
                        msg += f"\n<b>⚓️ 𝐒𝐞𝐞𝐝𝐞𝐫𝐬 :</b> <code>{download.aria_download().num_seeders}</code>" \
                            f" | <b>🔄 𝐏𝐞𝐞𝐫𝐬 :</b> <code>{download.aria_download().connections}</code>"
                    except:
                        pass
                    try:
                        msg += f"\n<b>⚓️ 𝐒𝐞𝐞𝐝𝐞𝐫𝐬 :</b> <code>{download.torrent_info().num_seeds}</code>" \
                            f" | <b>🔄 Leechers :</b> <code>{download.torrent_info().num_leechs}</code>"
                    except:
                        pass
                    msg += f'\n<b>👨‍🦱 Uploader: 👉 </b> <a href="tg://user?id={download.message.from_user.id}">{download.message.from_user.first_name}</a> (<code>{download.message.from_user.id}</code>)'
                if download.status() == MirrorStatus.STATUS_DOWNLOADING:
                    msg += f"\n<b>🚫 𝐓𝐨 𝐒𝐭𝐨𝐩 :</b> <code>/{BotCommands.CancelMirror} {download.gid()}</code>"
                msg += "\n\n"
                if STATUS_LIMIT is not None:
                    if INDEX >= COUNT + STATUS_LIMIT:
                        break
        if STATUS_LIMIT is not None:
            if INDEX > COUNT + STATUS_LIMIT:
                return None, None
            if dick_no > STATUS_LIMIT:
                msg += f"Page: <code>{PAGE_NO}/{pages}</code> | <code>Tasks: {dick_no}</code>\n"
                buttons = button_build.ButtonMaker()
                buttons.sbutton("Previous", "pre")
                buttons.sbutton("Next", "nex")
                button = InlineKeyboardMarkup(buttons.build_menu(2))
                return msg, button
        return msg, ""


def flip(update, context):
    query = update.callback_query
    query.answer()
    global COUNT, PAGE_NO
    if query.data == "nex":
        if PAGE_NO == pages:
            COUNT = 0
            PAGE_NO = 1
        else:
            COUNT += STATUS_LIMIT
            PAGE_NO += 1
    elif query.data == "pre":
        if PAGE_NO == 1:
            COUNT = STATUS_LIMIT * (pages - 1)
            PAGE_NO = pages
        else:
            COUNT -= STATUS_LIMIT
            PAGE_NO -= 1
    message_utils.update_all_messages()


def get_readable_time(seconds: int) -> str:
    result = ''
    (days, remainder) = divmod(seconds, 86400)
    days = int(days)
    if days != 0:
        result += f'{days}d'
    (hours, remainder) = divmod(remainder, 3600)
    hours = int(hours)
    if hours != 0:
        result += f'{hours}h'
    (minutes, seconds) = divmod(remainder, 60)
    minutes = int(minutes)
    if minutes != 0:
        result += f'{minutes}m'
    seconds = int(seconds)
    result += f'{seconds}s'
    return result


def is_url(url: str):
    url = re.findall(URL_REGEX, url)
    if url:
        return True
    return False


def is_gdrive_link(url: str):
    return "drive.google.com" in url


def is_mega_link(url: str):
    return "mega.nz" in url or "mega.co.nz" in url


def get_mega_link_type(url: str):
    if "folder" in url:
        return "folder"
    elif "file" in url:
        return "file"
    elif "/#F!" in url:
        return "folder"
    return "file"


def is_magnet(url: str):
    magnet = re.findall(MAGNET_REGEX, url)
    if magnet:
        return True
    return False


def new_thread(fn):
    """To use as decorator to make a function call threaded.
    Needs import
    from threading import Thread"""

    def wrapper(*args, **kwargs):
        thread = threading.Thread(target=fn, args=args, kwargs=kwargs)
        thread.start()
        return thread

    return wrapper


next_handler = CallbackQueryHandler(flip, pattern="nex", run_async=True)
previous_handler = CallbackQueryHandler(flip, pattern="pre", run_async=True)
dispatcher.add_handler(next_handler)
dispatcher.add_handler(previous_handler)
