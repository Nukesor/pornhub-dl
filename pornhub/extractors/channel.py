"""Helper for extracting meta information from pornhub."""
import re
import os
import sys
import time
import requests
from bs4 import BeautifulSoup

from pornhub.models import User, Clip
from pornhub.logging import logger
from pornhub.helper import get_clip_path, link_duplicate, check_logged_out
from pornhub.download import get_soup, download_video


def download_channel_videos(session, channel):
    """Download all videos of a user."""
    viewkeys = set(get_channel_viewkeys(channel))

    if len(viewkeys) == 0:
        logger.error(f"Found 0 videos for user {user.key}. Aborting")
        sys.exit(1)

    full_success = True

    logger.info(f"Found {len(viewkeys)} videos.")
    for viewkey in viewkeys:
        clip = Clip.get_or_create(session, viewkey)

        # The clip has already been downloaded, skip it.
        if clip.completed:
            if clip.title is not None and clip.extension is not None:
                target_path = get_clip_path(channel.name, clip.title, clip.extension)
                link_duplicate(clip, target_path)

            continue

        success, info = download_video(viewkey, channel.name)
        if success:
            clip.title = info["title"]
            clip.tags = info["tags"]
            clip.cartegories = info["categories"]
            clip.completed = True
            clip.location = info["out_path"]
            clip.extension = info["ext"]

            logger.info(f"New video: {clip.title}")
        else:
            full_success = False

        session.commit()
        time.sleep(20)

    return full_success


def get_channel_video_url(channel_id):
    """Compile the channel videos url."""
    is_premium = os.path.exists("http_cookie_file")
    if is_premium:
        return f"https://www.pornhubpremium.com/channels/{channel_id}"

    return f"https://www.pornhub.com/channels/{channel_id}"


def get_channel_info(channel_id):
    """Get meta information from channel website."""
    url = get_channel_video_url(channel_id)
    soup = get_soup(url)
    if soup is None:
        logger.error("Got invalid response for channel: {url}")
        sys.exit(1)

    profile = soup.find(id="channelsProfile")
    if profile is None:
        logger.info(f"Couldn't get info for channel: {url}")
        check_logged_out(soup)
        sys.exit(1)

    header = profile.find("div", {"class": "header"})
    wrapper = profile.find("div", {"class": "bottomExtendedWrapper"})
    title = profile.find("div", {"class": "title"})
    name = title.find("h1").text.strip()

    name = name.replace(" ", "_")
    name = re.sub(r"[\W]+", "_", name)

    return {"name": name}


def get_channel_viewkeys(channel):
    """Scrape all public viewkeys of the channel's videos."""
    is_premium = os.path.exists("http_cookie_file")
    if is_premium:
        url = f"https://www.pornhubpremium.com/channels/{channel.id}/videos"
    else:
        url = f"https://www.pornhub.com/channels/{channel.id}/videos"

    soup = get_soup(url)
    if soup is None:
        logger.error(f"Failed to find video page for channel {channel.id}")
        check_logged_out(soup)
        sys.exit(1)

    pages = 1
    hasNavigation = False
    hasEndlessScrolling = False

    # Some sites have a navigation at the bottom
    navigation = soup.find("div", {"class": "pagination3"})
    if navigation is not None:
        children = navigation.findChildren("li", {"class": "page_number"})
        pages = len(children) + 1
        hasNavigation = True
    # Others have a button for "endless scrolling"
    # In that case we have to search as long as
    elif soup.find(id="moreDataBtn"):
        hasEndlessScrolling = True

    keys = []
    current_page = 1
    next_url = url
    while current_page <= pages:
        # Check if the next site has another "endless scrolling" button as qell
        # If that's the case, increase the counter
        if hasEndlessScrolling and soup.find(id="moreDataBtn"):
            pages += 1

        logger.info(f"Crawling {next_url}")
        # Channel with normal video upload list
        videos = soup.find(id="showAllChanelVideos")

        if videos is None:
            logger.error(f"Couldn't find channel videos in site: {url}")
            check_logged_out(soup)
            sys.exit(1)

        for video in videos.find_all("li"):
            if video.has_attr("_vkey"):
                keys.append(video["_vkey"])

        current_page += 1
        next_url = url + f"?page={current_page}"

        time.sleep(4)

        soup = get_soup(next_url)
        # We couldn't get the next url.
        if soup is None:
            break

    return keys
