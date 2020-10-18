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


def download_user_videos(session, user):
    """Download all videos of a user."""
    video_viewkeys = get_user_video_viewkeys(user)

    # Try to get all uploaded videos
    video_upload_viewkeys = get_video_upload_viewkeys(user)
    # If that doesn't work, try to get all public uploaded videos
    if len(video_upload_viewkeys) == 0:
        video_upload_viewkeys = get_video_upload_viewkeys(user, True)

    viewkeys = set(video_viewkeys + video_upload_viewkeys)

    if len(viewkeys) == 0:
        logger.error(f"Found 0 videos for user {user.key}. Aborting")
        sys.exit(1)

    full_success = True

    logger.info(f"Found {len(viewkeys)} videos.")
    for viewkey in viewkeys:
        clip = Clip.get_or_create(session, viewkey, user)

        # The clip has already been downloaded, skip it.
        if clip.completed:
            if clip.title is not None and clip.extension is not None:
                target_path = get_clip_path(user.name, clip.title, clip.extension)
                link_duplicate(clip, target_path)

            if clip.user is None:
                clip.user = user
                session.commit()

            continue

        success, info = download_video(viewkey, user.name)
        if success:
            clip.title = info["title"]
            clip.tags = info["tags"]
            clip.cartegories = info["categories"]
            clip.completed = True
            clip.user = user
            clip.location = info["out_path"]
            clip.extension = info["ext"]

            logger.info(f"New video: {clip.title}")
        else:
            full_success = False

        session.commit()
        time.sleep(20)

    return full_success


def get_user_info(key):
    """Get all necessary user information."""
    user_type, url, soup = get_user_type_and_url(key)
    name = get_user_name_from_soup(soup, "user")
    if name is None:
        logger.error(f"Couldn't get user info for {key}")
        sys.exit(1)

    name = name.strip()
    name = name.replace(" ", "_")
    name = re.sub(r"[\W]+", "_", name)

    return {
        "type": user_type,
        "url": url,
        "name": name,
    }


def get_user_type_and_url(key):
    """Detect the user type and the respective url for this user."""
    possible_urls = {}
    for user_type in [User.PORNSTAR, User.MODEL, User.USER]:
        possible_urls[user_type] = get_user_video_url(user_type, key)

    for user_type, url in possible_urls.items():
        soup = get_soup(url, False)

        if soup is not None:
            return user_type, url, soup

    raise Exception(f"Couldn't detect type for user {key}")


def get_user_name_from_soup(soup, website_type):
    """Get the name of the user by website."""
    profileHeader = soup.find("section", {"class": "topProfileHeader"})
    if profileHeader is None:
        profileHeader = soup.find(id="topProfileHeader")

    if profileHeader is None:
        return None

    # Try to get the user name from subscription element
    div = profileHeader.find("div", {"class": "nameSubscribe"})
    if div is not None:
        h1 = div.find("h1")
        return h1.text

    # Try to get the user name  from normal profile
    div = profileHeader.find("div", {"class": "profileUserName"})
    if div is not None:
        a = div.find("a")
        return a.text

    return None


def get_user_video_url(user_type, key):
    """Compile the user videos url."""
    is_premium = os.path.exists("http_cookie_file")
    if is_premium:
        return f"https://www.pornhubpremium.com/{user_type}/{key}"

    return f"https://www.pornhub.com/{user_type}/{key}"


def get_user_video_viewkeys(user):
    """Scrape viewkeys from the user's user/videos route."""
    is_premium = os.path.exists("http_cookie_file")
    if is_premium:
        url = f"https://www.pornhubpremium.com/{user.user_type}/{user.key}/videos"
    else:
        url = f"https://www.pornhub.com/{user.user_type}/{user.key}/videos"

    soup = get_soup(url)
    if soup is None:
        logger.info(f"Nothing on {url}")
        return []

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
        # Users with normal video upload list
        videos = soup.find("div", {"class": "mostRecentVideosSection"})

        if videos is None:
            return []

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


def get_video_upload_viewkeys(user, public=False):
    """Scrape viewkeys from the user's user/videos/upload route."""
    is_premium = os.path.exists("http_cookie_file")
    if is_premium:
        url = (
            f"https://www.pornhubpremium.com/{user.user_type}/{user.key}/videos/upload"
        )
    else:
        url = f"https://www.pornhub.com/{user.user_type}/{user.key}/videos/upload"

    if public:
        if is_premium:
            url = f"https://www.pornhubpremium.com/{user.user_type}/{user.key}/videos/public"
        else:
            url = f"https://www.pornhub.com/{user.user_type}/{user.key}/videos/public"

    soup = get_soup(url)
    if soup is None:
        logger.info(f"Nothing on {url}")
        return []

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
        videoSection = soup.find("div", {"class": "videoUList"})
        pornstarVideoSection = soup.find(id="pornstarsVideoSection")
        claimedUploadedVideoSection = soup.find(id="claimedUploadedVideoSection")

        # Users with normal video upload list
        if videoSection is not None:
            videos = videoSection.find(id="moreData")
        # Users with pornstarVideoSection
        elif pornstarVideoSection is not None:
            videos = pornstarVideoSection
        # Dunno what this is
        elif claimedUploadedVideoSection is not None:
            videos = claimedUploadedVideoSection
        else:
            logger.error(f"Couldn't find video section on {next_url}. Did we log out?")
            if check_logged_out(soup):
                sys.exit(1)
            return []

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
