#
# MIT License
#
# Copyright (c) 2020-21  Matthew Lovell and contributors
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
# ----------------------------------------------------------------------------

import sys
try:
    import RPi.GPIO as GPIO
except ImportError:
    pass

from luma.core.device import device
from PIL import Image
from PIL import ImageDraw
from PIL import ImageFont

from datetime import datetime, timedelta
from aenum import Enum, extend_enum
from functools import lru_cache
import copy
import math
import time
import logging
import requests
import json
import io
import re
import os
import threading
import warnings
import traceback

# kodi_panel settings
import config

PANEL_VER = "v1.50"

#
# Audio/Video codec lookup table
#
#   Should any collision in codec names occur, this table may have to
#   be split for distinct audio and video codecs.  Until then, though,
#   we can use it for both.
#
#   The codec table can now be extended via the setup.toml file
#
codec_name = {
    "ac3": "DD",
    "wvc1": "VC1",
    "eac3": "DD+",
    "dtshd_ma": "DTS-MA",
    "dtshd_hra": "DTS-HRA",
    "dca": "DTS",
    "truehd": "DD-HD",
    "wmapro": "WMA",
    "mp3float": "MP3",
    "flac": "FLAC",
    "alac": "ALAC",
    "vorbis": "OggV",
    "aac": "AAC",
    "pcm_s16be": "PCM",
    "mp2": "MP2",
    "pcm_u8": "PCM",
    "BXA": "AirPlay",    # used with AirPlay
    "dsd_lsbf_planar": "DSD",
    "h264": "x264"
}


#
# Default InfoLabels
#
#   These can be augmented via the setup.toml file.  Search further
#   below for the updates that occur to these lists.
#
#   See https://kodi.wiki/view/InfoLabels for what is available.
#
#   Entries should NOT be removed if there is active code that assumes
#   their existence in Kodi responses.
#
#   For instance, the MusicPlayer.Cover and VideoPlayer.Cover labels
#   must be present if artwork is desired.  Current time and file
#   duration must be present if a progress bar is desired.
#
#
# NOTES:
#
# Here is how the Player.Filenameandpath InfoLabel behaves for me:
#
# - UPnP/DLNA music:  http://10.0.0.3:52100/Music/F1205284.m4a?Reader=32652
# - UPnP/DLNA movie:  http://10.0.0.3:52100/Video/F233148.mkv
# - Library movie:    smb://10.0.0.3/Movies/Amelie.mkv
# - AirPlay audio:    pipe://11/
#
# It therefore seems useful to have a test whether the current media's
# path starts with "http://" (and potentially "https://").  This is
# solely because Kodi parsing of UPnP fields seems somewhat
# incomplete.  Knowing the path could be helpful in making display of
# some info conditional.
#
# Also, AirPlay starts off for ~2 seconds with MusicPlayer.Title equal
# to "AirPlay", the Filenameandpath as shown above, but with many
# other fields blank or set according to whatever was previously
# playing.  I may use that in update_display() below to filter out the
# two seconds of default cover art that then results.
#
# Based on feedback from @nico1080, it seems like PVR recordings start
# out with "pvr://".  That gets used below for video auto-selection of
# screen mode.
#

# Status screen information
STATUS_LABELS = [
    "System.Uptime",
    "System.CPUTemperature",
    "System.CpuFrequency",
    "System.Date",
    "System.Time",
    "System.Time(hh:mm:ss)",
    "System.BuildVersion",
    "System.BuildDate",
]

# Audio screen information
AUDIO_LABELS = [
    "Player.Filenameandpath",
    "MusicPlayer.Title",
    "MusicPlayer.Album",
    "MusicPlayer.Artist",
    "MusicPlayer.Time",
    "MusicPlayer.Duration",
    "MusicPlayer.TrackNumber",
    "MusicPlayer.Property(Role.Composer)",
    "MusicPlayer.Codec",
    "MusicPlayer.BitsPerSample",
    "MusicPlayer.SampleRate",
    "MusicPlayer.Year",
    "MusicPlayer.Genre",
    "MusicPlayer.Cover",
]

# Video screen information
VIDEO_LABELS = [
    "Player.Filenameandpath",      # used with video mode auto-selection
    "VideoPlayer.Title",
    "VideoPlayer.OriginalTitle",
    "VideoPlayer.TVShowTitle",
    "VideoPlayer.Season",
    "VideoPlayer.Episode",
    "VideoPlayer.EpisodeName",
    "VideoPlayer.Duration",
    "VideoPlayer.Time",
    "VideoPlayer.Genre",
    "VideoPlayer.Year",
    "VideoPlayer.VideoCodec",
    "VideoPlayer.AudioCodec",
    "VideoPlayer.VideoResolution",
    "VideoPlayer.ChannelName",
    "VideoPlayer.ChannelNumberLabel",
    "VideoPlayer.Rating",
    "VideoPlayer.ParentalRating",
    "VideoPlayer.Cover",
]

# Slideshow information
SLIDESHOW_LABELS = [
    "Slideshow.Filename",
    "Slideshow.Resolution",
    "Slideshow.CameraMake",
    "Slideshow.CameraModel",
    "Slideshow.Aperture",
    "Slideshow.ExposureTime",
    "Slideshow.Exposure",
    "Slideshow.FocalLength",
]


#
# Kodi InfoBooleans to retrieve
#
#   https://kodi.wiki/view/List_of_boolean_conditions
#
#   The results get included in the *same* dictionary that carries the
#   InfoLabels above.  This is possible since all names appear to be
#   distinct.
#
#   If there is ever a name collision between an InfoLabel and an
#   InfoBoolean, the current implementation will effectively drop the
#   Label, replacing it with the Boolean.
#
STATUS_BOOLEANS    = ['System.ScreenSaverActive']
AUDIO_BOOLEANS     = ['Player.Paused']
VIDEO_BOOLEANS     = ['Player.Paused']
SLIDESHOW_BOOLEANS = []


# ----------------------------------------------------------------------------

#
# Start processing settings...
#
if "BASE_URL" in config.settings.keys():
    base_url = config.settings["BASE_URL"]
    rpc_url = base_url + "/jsonrpc"
    headers = {'content-type': 'application/json'}
else:
    print("Settings file does not specify BASE_URL!  Stopping.")
    sys.exit(1)

# Is Kodi running locally?
_local_kodi = (base_url.startswith("http://localhost:") or
               base_url.startswith("https://localhost:"))

# Image handling
if ("DISPLAY_WIDTH" in config.settings.keys() and
        "DISPLAY_HEIGHT" in config.settings.keys()):
    _frame_size = (
        config.settings["DISPLAY_WIDTH"],
        config.settings["DISPLAY_HEIGHT"])
else:
    print("Settings file does not specify DISPLAY_WIDTH and DISPLAY_HEIGHT!  Stopping.")
    sys.exit(1)

# State to prevent re-fetching cover art unnecessarily
_last_thumb = None
_last_image_time = None   # used with airtunes / airplay coverart

# Flag set or cleared by get_artwork() to indicate if fallback to one
# of the default images was necessary.  Knowing that state could be
# useful for any element-rendering callback functions.
_image_default = False

# Re-use static portion of a screen.  The various _last_* variables
# below are checked to determine when the static portion can be
# reused.
_static_image = None
_static_video = False  # set True by video_screens(), False by audio_screens()

_last_track_num     = None
_last_track_title   = None
_last_track_album   = None
_last_track_time    = None
_last_video_title   = None
_last_video_time    = None
_last_video_episode = None

# Thumbnail defaults (these now DO get resized as needed)
_kodi_thumb = config.settings.get("KODI_THUMB", "images/kodi_thumb.jpg")
_default_audio_thumb = config.settings.get("DEFAULT_AUDIO", "images/music_icon2_lg.png")
_default_video_thumb = config.settings.get("DEFAULT_VIDEO", "images/video_icon2.png")
_default_airplay_thumb = config.settings.get("DEFAULT_AIRPLAY", "images/airplay_thumb.png")

# RegEx for recognizing AirPlay images (compiled once)
_airtunes_re = re.compile(
    r'^special:\/\/temp\/(airtunes_album_thumb\.(png|jpg))')


#
# Debug flags
#
DEBUG_FIELDS = config.settings.get("DEBUG_FIELDS", False)
DEBUG_ART    = config.settings.get("DEBUG_ART", False)

if DEBUG_FIELDS: print("DEBUG_FIELDS print statements enabled.")
if DEBUG_ART:    print("DEBUG_ART print statements enabled.")


#
# Load all user-specified fonts
#
_fonts = {}
if "fonts" in config.settings.keys():
    for user_font in config.settings["fonts"]:
        try:
            if "encoding" in user_font.keys():
                _fonts[user_font["name"]] = ImageFont.truetype(
                    user_font["path"], user_font["size"], encoding=user_font["encoding"]
                )
            else:
                _fonts[user_font["name"]] = ImageFont.truetype(
                    user_font["path"], user_font["size"]
                )
        except OSError:
            print(
                "Unable to load font ",  user_font["name"],
                " with path '", user_font["path"], "'",
                sep='')
            sys.exit("Exiting")
else:
    print("Settings file does not provide a fonts table!  Stopping.")
    sys.exit(1)


if "font_main" in _fonts.keys():
    pass
else:
    print("fonts table must specify a 'font_main' entry!  Stopping.")
    sys.exit(1)


#
# Color lookup table
#
if "COLORS" in config.settings.keys():
    _colors = config.settings.get("COLORS", {})
else:
    print("Settings file does not provide a COLORS table!  Stopping.")
    sys.exit(1)


#
# Check for any additional InfoLabels to retrieve
#

if ("STATUS_LABELS" in config.settings.keys() and
        type(config.settings["STATUS_LABELS"]) == list):
    STATUS_LABELS += config.settings["STATUS_LABELS"]

if ("AUDIO_LABELS" in config.settings.keys() and
        type(config.settings["AUDIO_LABELS"]) == list):
    AUDIO_LABELS += config.settings["AUDIO_LABELS"]

if ("VIDEO_LABELS" in config.settings.keys() and
        type(config.settings["VIDEO_LABELS"]) == list):
    VIDEO_LABELS += config.settings["VIDEO_LABELS"]

if ("SLIDESHOW_LABELS" in config.settings.keys() and
        type(config.settings["SLIDESHOW_LABELS"]) == list):
    SLIDESHOW_LABELS += config.settings["SLIDESHOW_LABELS"]

#
# Also check for any additional InfoBooleans to retrieve
#

if ("STATUS_BOOLEANS" in config.settings.keys() and
        type(config.settings["STATUS_BOOLEANS"]) == list):
    STATUS_BOOLEANS += config.settings["STATUS_BOOLEANS"]

if ("AUDIO_BOOLEANS" in config.settings.keys() and
        type(config.settings["AUDIO_BOOLEANS"]) == list):
    AUDIO_BOOLEANS += config.settings["AUDIO_BOOLEANS"]

if ("VIDEO_BOOLEANS" in config.settings.keys() and
        type(config.settings["VIDEO_BOOLEANS"]) == list):
    VIDEO_BOOLEANS += config.settings["VIDEO_BOOLEANS"]

if ("SLIDESHOW_BOOLEANS" in config.settings.keys() and
        type(config.settings["SLIDESHOW_BOOLEANS"]) == list):
    SLIDESHOW_BOOLEANS += config.settings["SLIDESHOW_BOOLEANS"]

#
# Permit codec_name table to be augmented
#
if ("CODECS" in config.settings.keys() and
    type(config.settings["CODECS"]) == dict):
    codec_name.update( config.settings["CODECS"] )


#
# Which display screens are enabled for use?
#
AUDIO_ENABLED     = config.settings.get("ENABLE_AUDIO_SCREENS", False)
VIDEO_ENABLED     = config.settings.get("ENABLE_VIDEO_SCREENS", False)
SLIDESHOW_ENABLED = config.settings.get("ENABLE_SLIDESHOW_SCREENS", False)

# Status screen is handled differently
STATUS_ENABLED    = config.settings.get("ENABLE_STATUS_SCREEN", True)
# Should the status screen always be shown when idle?
IDLE_STATUS_ENABLED = config.settings.get("ENABLE_IDLE_STATUS", False)


# Current Screen Mode
# -------------------
#
# Define an enumerated type (well, it's still Python, so a class)
# representing whether the screen being drawn is for audio playback,
# video playback, or is just a status screen.
#
# This state was added mainly to pass down to the element and string
# callback functions, in case a callback gets used in layouts for
# completely different media.
#

class ScreenMode(Enum):
    STATUS = 0   # kodi_panel status/info screen
    AUDIO  = 1   # audio playback is active
    VIDEO  = 2   # video playback is active
    SLIDE  = 3   # slideshow is active


# Shared Elements
# ---------------
#
# Provide a lookup table such that elements can be shared across
# multiple layouts.  Thanks to @nico1080 for the suggestion.

_SHARED_ELEMENT = {}
_USE_SHARED = False

if ("shared_element" in config.settings.keys() and
        type(config.settings["shared_element"]) is dict):
    _SHARED_ELEMENT = config.settings["shared_element"]

if len(_SHARED_ELEMENT.keys()):
    _USE_SHARED = True



# Screen / Layout Enumeration
# ---------------------------
#
#   Use an enumerated type to capture all the distinct layouts for
#   audio screens, etc.  The next() function that makes available then
#   serves to switch modes in response to screen touches.
#
#   The number of audio layouts can grow, based on the contents
#   of the setup.toml file.
#
#   During development, the ability to support different layouts got
#   somewhat re-purposed, after general video screen support was
#   added.  The "auto-selection" feature provides hooks by which the
#   media being played can determine which layout to use.  This was
#   originally suggested by @noggin in the CE Forums.
#

# Base class, providing the next() functionality
class LayoutEnum(Enum):
    def next(self):
        cls = self.__class__
        members = list(cls)
        index = members.index(self) + 1
        if index >= len(members):
            index = 0
        return members[index]

# Provide the same behavior across audio, video, and slideshow.  With
# the addition of InfoLabels, also permit the same flexibility for
# status.

class ADisplay(LayoutEnum): pass   # audio
class VDisplay(LayoutEnum): pass   # video
class SDisplay(LayoutEnum): pass   # slideshow (photos)
class IDisplay(LayoutEnum): pass   # status/info screen


#
# Populate each enum based upon settings file
#

if AUDIO_ENABLED:
    if ("ALAYOUT_NAMES" in config.settings.keys() and
            "ALAYOUT_INITIAL" in config.settings.keys()):
        for index, value in enumerate(config.settings["ALAYOUT_NAMES"]):
            extend_enum(ADisplay, value, index)

        # At startup, use the default layout mode specified in settings
        audio_dmode = ADisplay[config.settings["ALAYOUT_INITIAL"]]

        # Should audio content (in InfoLabels) be used to select layout?
        AUDIO_LAYOUT_AUTOSELECT = config.settings.get(
            "ALAYOUT_AUTOSELECT", False)

    else:
        warnings.warn(
            "Cannot find settings for ALAYOUT_NAMES and/or ALAYOUT_INITIAL!")
        print("Disabling audio screens (AUDIO_ENABLED=0)")
        AUDIO_ENABLED = 0


if VIDEO_ENABLED:
    if ("VLAYOUT_NAMES" in config.settings.keys() and
            "VLAYOUT_INITIAL" in config.settings.keys()):
        # Populate enum based upon settings file
        for index, value in enumerate(config.settings["VLAYOUT_NAMES"]):
            extend_enum(VDisplay, value, index)

        # At startup, use the default layout mode specified in settings
        video_dmode = VDisplay[config.settings["VLAYOUT_INITIAL"]]

        # Should video layout be auto-determined as part of video_screens()
        VIDEO_LAYOUT_AUTOSELECT = config.settings.get(
            "VLAYOUT_AUTOSELECT", False)

    else:
        warnings.warn(
            "Cannot find settings for VLAYOUT_NAMES and/or VLAYOUT_INITIAL!")
        print("Disabling video screens (VIDEO_ENABLED=0)")
        VIDEO_ENABLED = 0


if SLIDESHOW_ENABLED:
    if ("SLAYOUT_NAMES" in config.settings.keys() and
            "SLAYOUT_INITIAL" in config.settings.keys()):
        # Populate enum based upon settings file
        for index, value in enumerate(config.settings["SLAYOUT_NAMES"]):
            extend_enum(SDisplay, value, index)

        # At startup, use the default layout mode specified in settings
        slide_dmode = SDisplay[config.settings["SLAYOUT_INITIAL"]]

        # Provide the same hook as for the other modes
        SLIDESHOW_LAYOUT_AUTOSELECT = config.settings.get(
            "SLAYOUT_AUTOSELECT", False)

    else:
        warnings.warn(
            "Cannot find settings for SLAYOUT_NAMES and/or SAYOUT_INITIAL!")
        print("Disabling slideshow screens (SLIDESHOW_ENABLED=0)")
        SLIDESHOW_ENABLED = 0


# The status/info screen(s) is treated differently.  For historical
# reasons, the setup file is free to define only a single layout.  So,
# if no config variables exist declaring other status/info layout
# names, don't emit any warning.
#
# Also, the variable naming for the status/info screens isn't quite
# consistent due to the development history of this feature.

if STATUS_ENABLED:
    if ("STATUS_NAMES" in config.settings.keys() and
            "STATUS_INITIAL" in config.settings.keys()):
        # Populate enum based upon settings file
        for index, value in enumerate(config.settings["STATUS_NAMES"]):
            extend_enum(IDisplay, value, index)

        # At startup, use the default layout mode specified in settings
        info_dmode = IDisplay[config.settings["STATUS_INITIAL"]]

        # Provide the same hook as for the other modes
        STATUS_LAYOUT_AUTOSELECT = config.settings.get(
            "STATUS_AUTOSELECT", False)
    else:
        info_dmode = None
        STATUS_LAYOUT_AUTOSELECT = False



# Screen Layouts
# --------------
#
# Fixup font and color entries now, so that further table lookups are
# not necessary at run-time.  Also provide for shared element
# replacement.
#

def fixup_layouts(nested_dict):
    newdict = copy.deepcopy(nested_dict)
    for key, value in nested_dict.items():
        if type(value) is dict:
            if (_USE_SHARED and "shared_element" in value and
                    value["shared_element"] in _SHARED_ELEMENT):
                # print("Looking up", value["shared_element"], "in _SHARED_ELEMENT dict")
                newdict[key] = fixup_layouts(
                    _SHARED_ELEMENT[value["shared_element"]])
            else:
                newdict[key] = fixup_layouts(value)
        elif type(value) is list:
            newdict[key] = fixup_array(value)
        else:
            if ((key.startswith("color") or key == "lcolor" or
                 key.endswith("outline") or
                 key.startswith("fill") or
                 key.endswith("fill")) and
                value.startswith("color_")):
                # Lookup color
                newdict[key] = _colors[value]
            elif (key == "font" or key == "lfont" or
                  key == "smfont"):
                # Lookup font
                newdict[key] = _fonts[value]
    return newdict


def fixup_array(array):
    newarray = []
    for item in array:
        if type(item) is dict:
            if (_USE_SHARED and "shared_element" in item and
                    item["shared_element"] in _SHARED_ELEMENT):
                # print("Looking up", item["shared_element"], "in _SHARED_ELEMENT dict")
                newarray.append(fixup_layouts(
                    _SHARED_ELEMENT[item["shared_element"]]))
            else:
                newarray.append(fixup_layouts(item))
        else:
            newarray.append(item)
    return newarray


# Patch up the audio layout nested dictionary
if (AUDIO_ENABLED and "A_LAYOUT" in config.settings.keys()):
    AUDIO_LAYOUT = fixup_layouts(config.settings["A_LAYOUT"])
elif AUDIO_ENABLED:
    warnings.warn(
        "Cannot find any A_LAYOUT screen settings in setup file!  Disabling audio screens.")
    AUDIO_ENABLED = 0

# Patch up the video layout nested dictionary
if (VIDEO_ENABLED and "V_LAYOUT" in config.settings.keys()):
    VIDEO_LAYOUT = fixup_layouts(config.settings["V_LAYOUT"])
elif VIDEO_ENABLED:
    warnings.warn(
        "Cannot find any V_LAYOUT screen settings in setup file!  Disabling video screens.")
    VIDEO_ENABLED = 0

# Patch up the slideshow layout nested dictionary
if (SLIDESHOW_ENABLED and "S_LAYOUT" in config.settings.keys()):
    SLIDESHOW_LAYOUT = fixup_layouts(config.settings["S_LAYOUT"])
elif SLIDESHOW_ENABLED:
    warnings.warn(
        "Cannot find any S_LAYOUT screen settings in setup file!  Disabling slideshow screens.")
    SLIDESHOW_ENABLED = 0

# Finally, patch up the status/info screen layout
if (STATUS_ENABLED and "STATUS_LAYOUT" in config.settings.keys()):
    STATUS_LAYOUT = fixup_layouts(config.settings["STATUS_LAYOUT"])
else:
    warnings.warn("Cannot find any STATUS_LAYOUT screen settings in setup file!  Disabling status/info screen.")
    STATUS_ENABLED = 0


# GPIO assignments and display options
# ------------------------------------
#
# Pin for screen's touch interrupt (T_IRQ), using RPi.GPIO
# numbering.  Find a pin that's unused by luma.  The touchscreen chip
# in my display has its own internal pullup resistor, so further below
# no pullup is specified.
#
# I found the following pins to work on the two SBCs.
#
#   Odroid C4:  GPIO19 (physical Pin 35)
#   RPi 3:      GPIO16 (physical Pin 36)
#
# The USE_TOUCH boolean can be set False to disable all attempts
# at interrupt use.
#
USE_TOUCH = config.settings.get("USE_TOUCH", False)
TOUCH_INT = config.settings.get("TOUCH_INT", 0)
TOUCH_PULLUP   = config.settings.get("TOUCH_PULLUP", False)
TOUCH_DEBOUNCE = config.settings.get("TOUCH_DEBOUNCE", 700)  # milliseconds

# Should the touch_callback() ISR attempt to invoke update_display()
# directly?  Having the ISR take too long to execute is problematic on
# the RPi Zero.
TOUCH_CALL_UPDATE = config.settings.get("TOUCH_CALL_UPDATE", False)

# Internal state variables used to manage screen presses
_kodi_connected = False
_kodi_playing   = False
_screen_active  = False

# Touchscreen state
_screen_press = threading.Event()

# status screen waketime, in seconds
_screen_wake = config.settings.get("SCREEN_WAKE_TIME", 25)
_screen_offtime = datetime.now()

# Provide a lock to ensure update_display() is single-threaded.  (This
# is perhaps unnecessary given Python's GIL, but is certainly safe.)
_lock = threading.Lock()

# Additional screen controls.  Note that RPi.GPIO's PWM control, even
# the Odroid variant, uses software (pthreads) to control the signal,
# which can result in flickering.  At present (Oct 2020), I cannot
# recommend it.
#
# I have not yet found a way to take advantage of the Odroid C4's
# hardware PWM simultaneous with using luma.lcd.
#
# The USE_BACKLIGHT boolean controls whether calls are made to
# luma.lcd at all to change backlight state.  Users with OLED displays
# should set it to False.
#
# As of Dec 2020, the framebuffer version of the script has an example
# of using RPi hardware PWM without going through luma.lcd.  That
# method uses a completely different set of variables, ignoring these.
#
USE_BACKLIGHT = config.settings.get("USE_BACKLIGHT", False)
USE_PWM = False
PWM_FREQ = 362       # frequency, presumably in Hz
PWM_LEVEL = 75.0     # float value between 0 and 100

# Are we running using luma.lcd's pygame demo mode?  This variable
# gets modified directly by kodi_panel_demo.py.
DEMO_MODE = False

#
# Finally, create the needed Pillow objects
#
#   These persist for the duration of program execution.  The new
#   Image objects that get created by audio_screen_static() and
#   video_screen_static() get transfered to this image instance.
#
image = Image.new('RGB', (_frame_size), 'black')
draw = ImageDraw.Draw(image)


# ----------------------------------------------------------------------------


# Element and String callback functions
# -------------------------------------
#
# These callbacks provide the "special treatment" of textfields that
# was previously provided via if-elif trees within audio- and
# video-specific functions.  See the additional comment block after
# all of the function definitions.
#
# Each function listed in the ELEMENT_CB dictionary must accept the
# following 6 arguments:
#
#   image        Image object instance for Pillow
#
#   draw         ImageDraw object instance, tied to image
#
#   info         dictionary containing InfoLabels from JSON-RPC response,
#                possibly augmented by calling function.  InfoBoolean
#                results, if any, are also included in this dictionary
#
#   field        dictionary containing layout information, originating
#                from the setup.toml file
#
#   screen_mode  instance of ScreenMode enumerated type, specifying
#                whether screen is STATUS, AUDIO, or VIDEO
#
#   layout_name  string specifying in-use layout name
#
# In addition, each function MUST return a string, even if empty.  The
# string return value is useful for the format_InfoLabels / format_str
# interpolation feature.  The calling function is responsible for
# rendering that returned string.
#
# Since image and draw are passed in, element callback functions are
# free to render or draw anything desired.  If the callback function
# does take it upon itself to modify the passed Image or ImageDraw
# objects directly, then it should return an empty string.
#
# It is also possible to define a simpler set of callback functions
# that ONLY perform string manipulation.  Functions in that lookup
# table only need to accept 3 arguments:
#
#   info         dictionary containing InfoLabels from JSON-RPC
#                response, possibly augmented by calling function.
#                InfoBoolean results, if any, are also included.
#
#   screen_mode  instance of ScreenMode enumerated type, specifying
#                whether screen is STATUS, AUDIO, or VIDEO
#
#   layout_name  string specifying in-use layout name
#
# Such functions must also return a string, even if empty.
#
#
# Finally, note that some care should be taken if any callback
# function wants to make use of format_InfoLabels(), as that function
# also ends up consulting the string callback table.  If one isn't
# careful, a loop could be possible that will end up just crashing
# Python.  In general, it is NOT recommended that callback functions
# directly make use of format_InfoLabels() themselves.
#

# Empty callback function, largely for testing
def element_empty(image, draw, info, field, screen_mode, layout_name):
    return ""

# Empty callback function, largely for testing
def strcb_empty(info, screen_mode, layout_name):
    return ""


# Determine if the duration is short (min:sec) or long (hr:min:sec).
# In combintionation the display_if[not] key, this can permit for
# changing precisely where the duration gets displayed on screen.
def strcb_audio_duration(info, screen_mode, layout_name):
    if 'MusicPlayer.Duration' in info:
        return str(info['MusicPlayer.Duration'].count(":"))
    else:
        return "0"


# Return "1" if media Filenameandpath starts with http:// or
# https://.  We'll take that as indicative of UPnP / DLNA
# playback.
def strcb_upnp_playback(info, screen_mode, layout_name):
    if 'Player.Filenameandpath' in info:
        if (info['Player.Filenameandpath'].startswith("http://") or
            info['Player.Filenameandpath'].startswith("https://")):
            return "1"
        else:
            return "0"
    return "0"

# Perform a table lookup to convert Kodi's codec names into more
# common names.
def strcb_codec(info, screen_mode, layout_name):
    if 'MusicPlayer.Codec' in info:
        if info['MusicPlayer.Codec'] in codec_name:
            return codec_name[info['MusicPlayer.Codec']]
        else:
            return info['MusicPlayer.Codec']
    return ""


# Similar function for AudioCodec lookup when playing video
def strcb_acodec(info, screen_mode, layout_name):
    if 'VideoPlayer.AudioCodec' in info:
        if info['VideoPlayer.AudioCodec'] in codec_name.keys():
            return codec_name[info['VideoPlayer.AudioCodec']]
        else:
            return info['VideoPlayer.AudioCodec']
    return ""


# Construct a string containing both the friendly codec name and, in
# parenthesis, the bit depth and sample rate for the codec.
#
# Note that DLNA/UPnP playback with Kodi seems to cause these
# InfoLabels to be inaccurate.  The bit depth, for instance, gets
# "stuck" at 32, even when playback has moved on to what is known to
# be a normal, 16-bit file.
#
# This is intended to be an audio-only callback.

def strcb_full_codec(info, screen_mode, layout_name):
    if (screen_mode == ScreenMode.AUDIO and
        'MusicPlayer.Codec' in info):

        if info['MusicPlayer.Codec'] in codec_name:
            display_text = codec_name[info['MusicPlayer.Codec']]
        else:
            display_text = info['MusicPlayer.Codec']

        # augment with (bit/sample) information
        display_text += " (" + info['MusicPlayer.BitsPerSample'] + "/" + \
            info['MusicPlayer.SampleRate'] + ")"

        return display_text
    else:
        return ""


# Process an audio file's listed Artist, instead displaying the
# Composer parenthetically if the artist field is empty.
#
# This particular special treatment never worked out as intended.  The
# combination of JRiver Media Center providing DLNA/UPnp playback to
# Kodi doesn't successfully yield any composer info.  I believe that
# Kodi's UPnP field parsing is incomplete.
#
# The "drop_unknown" flag previously checked by this function
# has been replaced with a more-general "exclude" check within
# the draw_fields() function.
#
# ToDo: With the change to using exclude, this callback could be
#       switched over to STRING_CB.
#

def element_audio_artist(image, draw, info, field, screen_mode, layout_name):
    if screen_mode == ScreenMode.AUDIO:
        # The following was an attempt to display Composer if
        # Artist is blank.  The combination of JRiver Media Center
        # and UPnP/DLNA playback via Kodi didn't quite permit this
        # to work, unfortunately.
        display_string = ""

        if info['MusicPlayer.Artist'] != "":
            display_string = info['MusicPlayer.Artist']

        elif info['MusicPlayer.Property(Role.Composer)'] != "":
            display_string = "(" + info['MusicPlayer.Property(Role.Composer)'] + ")"

        return display_string
    return ""



# Draw a thin line
def element_thin_line(image, draw, info, field, screen_mode, layout_name):
    draw.line(
        [field["posx"], field["posy"], field["endx"], field["endy"]],
         fill = field["fill"],
         width = field.get("width", 1)
        )
    return ""


# Draw (audio) album cover.  Invoking this callback, from a layout's
# fields array, is an alternative to using the top-level "thumb"
# entry.
#
# The InfoLabel name that specifies the path to the artwork can be
# specified via the optional "use_path" key.  If no such key is
# provided, then the default of MusicPlayer.Cover is used.
#
# In contrast to a similar function for generic artwork, audio
# artwork retrieval has a special-case to handle AirPlay covers.
# However, this code path does NOT attempt to make use of _last_thumb
# to prevent re-fetching of the AirPlay cover.  If that is desired,
# one is better off using the top-level "thumb" entry within a layout.
#
# This function also assumes that the cover art is square, only
# looking for a "size" key.
#
# Finally, recall that the field array walk in draw_fields() handles
# the display_if or display_ifnot conditionals.
#
def element_audio_cover(image, draw, info, field, screen_mode, layout_name):
    if 'use_path' in field:
        image_path = info.get(field['use_path'], "")
    else:
        image_path = info.get('MusicPlayer.Cover', "")

    if image_path == "": return ""

    # Audio cover art is expected to be square, thus only a single
    # dimension -- size -- is expected.  Permit for a little more
    # flexibility though.
    height = 0
    width  = 0
    if ("size" in field):
        height = field["size"]
        width  = field["size"]
    elif ("width" in field and
          "height" in field):
        height = field["height"]
        width  = field["width"]
    else:
        return ""

    # The following is somewhat redundate with code that
    # exists in audio_screen_static().
    artwork = None
    if _airtunes_re.match(image_path):
        artwork = get_airplay_art(image_path, None,
                                  field["size"], field["size"],
                                  enlarge=field.get("enlarge", False))
    else:
        artwork = get_artwork(image_path,
                              field["size"], field["size"],
                              use_defaults=True,
                              enlarge=field.get("enlarge", False))

    if artwork:
        paste_artwork(image, artwork, field)

    # Return string required for all callbacks
    return ""


# Similar image rendering function as element_audio_cover(), but with
# no provision for AirPlay covers and expecting "height" and "width"
# to be specified rather than a single size.
#
# The image path must be specified via a "use_path" key, falling back
# to using VideoPlayer.Cover otherwise.
#
# Finally, recall that the field array walk in draw_fields() handles
# the display_if or display_ifnot conditionals.
#
def element_generic_artwork(image, draw, info, field, screen_mode, layout_name):
    if 'use_path' in field:
        image_path = info.get(field['use_path'], "")
    else:
        image_path = info.get('VideoPlayer.Cover', "")

    if image_path == "": return

    # The following is somewhat redundate with code that
    # exists in video_screen_static().
    artwork = None
    artwork = get_artwork(image_path,
                          field["width"], field["height"],
                          use_defaults=True,
                          enlarge=field.get("enlarge", False))
    if artwork:
        paste_artwork(image, artwork, field)

    # Return string required for all callbacks
    return ""


# Return string with current kodi_panel version
def strcb_version(info, screen_mode, layout_name):
    return "kodi_panel " + PANEL_VER


# Return a friendlier version of Kodi build information
def strcb_kodi_version(info, screen_mode, layout_name):
    if ("System.BuildVersion" in info and
        "System.BuildDate" in info):
        kodi_version = info["System.BuildVersion"].split()[0]
        build_date   = info["System.BuildDate"]
        return "Kodi version: " + kodi_version + " (" + build_date + ")"
    return ""


# Render current time and, in what should be a smaller font, AM/PM.
# Return an empty string so as not to confuse the caller.
def element_time_hrmin(image, draw, info, field, screen_mode, layout_name):
    if "System.Time" in info:
        time_parts = info['System.Time'].split(" ")
        time_width, time_height = draw.textsize(time_parts[0], field["font"])
        draw.text((field["posx"], field["posy"]),
                  time_parts[0],
                  field["fill"], field["font"])
        draw.text((field["posx"] + time_width + 5, field["posy"]),
                  time_parts[1],
                  field["fill"], field["smfont"])

    return ""


# Small analog clock, copied from luma.example's clock.py
#
# This element can only be used if "System.Time(xx:mm:ss)" is included
# in the retrieved InfoLabels.  The more-typical System.Time InfoLabel
# only provides hours and minutes (along with am/pm).
#
# center position is specified by element's posx and posy.
# radius of clock must also be specifed.
#
def posn(angle, arm_length):
    dx = int(math.cos(math.radians(angle)) * arm_length)
    dy = int(math.sin(math.radians(angle)) * arm_length)
    return (dx, dy)

def element_analog_clock(image, draw, info, field, screen_mode, layout_name):
    if "System.Time(hh:mm:ss)" in info:
        (now_hour, now_min, now_sec) = info['System.Time(hh:mm:ss)'].split(":")

        margin = 4
        cx = field["posx"]
        cy = field["posy"]
        radius = field["radius"]

        # positions for outer circle
        left   = cx - radius
        top    = cy - radius
        right  = cx + radius
        bottom = cy + radius

        # angles for all hands
        hrs_angle = 270 + (30 * (int(now_hour) + (int(now_min) / 60.0)))
        hrs = posn(hrs_angle, radius - margin - 7)

        min_angle = 270 + (6 * int(now_min))
        mins = posn(min_angle, radius - margin - 2)

        sec_angle = 270 + (6 * int(now_sec))
        secs = posn(sec_angle, radius - margin - 2)

        # outer circle
        draw.ellipse((left, top, right, bottom),
                     outline=info.get("outline", "white"))

        # hands
        draw.line((cx, cy, cx + hrs[0], cy + hrs[1]),   fill=info.get("fill", "white"))
        draw.line((cx, cy, cx + mins[0], cy + mins[1]), fill=info.get("fill", "white"))
        draw.line((cx, cy, cx + secs[0], cy + secs[1]), fill=info.get("fills", "red"))

        # center circle
        draw.ellipse((cx - 2, cy - 2, cx + 2, cy + 2),
                     fill=info.get("fill", "white"),
                     outline=info.get("outline", "white"))

    return ""



# Dictionaries of element and string callback functions, with each key
# corresponding to the "name" specified for a field (within a layout's
# array named "fields").
#
# Scripts that are making use of kodi_panel_display can change the
# function assigned to the entries below or add entirely new key/value
# pairs.  Prior to invoking
#
#   kodi_panel_display.main(device)
#
# scripts that wish to install their own callback functions can
# directly manipulate
#
#    kodi_panel_display.ELEMENT_CB   or
#    kodi_panel_display.STRING_CB
#
# as part of their startup.  For instance, if a script has a
# customized codec lookup function, it can make the assignment
#
#   kodi_panel_display.ELEMENT_CB["codec"] = my_element_codec
#
# provided the my_element_codec() definition has been provided first.
# Note that existing keys can be removed from either dictionary using
# a del statement:
#
#   del kodi_panel_display.STRING_CB["codec"]
#
# Deleting an entry is necessary if one wants to switch an existing
# key name to reside in the other lookup table.
#
# -------------------
#
# NOTE:
#
#   It would also be possible to extend this approach to apply to
#   top-level elements within a layout such as "thumb" and "prog".
#   However, the end user can *already* override that functionality by
#
#    1. Not making use of "thumb" or "prog" in any layouts.
#
#    2. Providing equivalent, customized functionality via their own
#       element callback functions, adding to ELEMENT_CB.  (The new
#       functions must take some care if referencing any variables
#       declared in this module's namespace, but such uses are
#       certainly possible.)
#
#    3. Invoking those callbacks by name within the fields
#       array of their layouts.
#
#   So, I believe all of the top-level functionality can be overridden
#   externally, without needing anything else.
#


# Drawing-capable element callback functions

ELEMENT_CB = {
    # Audio screen elements
    'artist'      : element_audio_artist,
    'audio_cover' : element_audio_cover,

    # Status screen elements
    'time_hrmin'   : element_time_hrmin,
    'analog_clock' : element_analog_clock,

    # Any screen
    'thin_line'       : element_thin_line,
    'generic_artwork' : element_generic_artwork,
    }


# String-manipulation callback functions

STRING_CB = {
    # Audio screen fields
    'codec'          : strcb_codec,
    'full_codec'     : strcb_full_codec,
    'audio_duration' : strcb_audio_duration,

    # Video screen fields
    'acodec' : strcb_acodec,

    # Status screen fields
    'version'      : strcb_version,
    'kodi_version' : strcb_kodi_version,

    # Any screen
    'upnp_playback' : strcb_upnp_playback,
    }


# ----------------------------------------------------------------------------

# Text wrapping from public blog post
#
# http://fiveminutes.today/articles/putting-text-on-images-with-python-pil/
#
# by Bach Ton That, with further modifications.  With the 800x480
# example layout, having the album title to the right of the cover art
# works better if one can wrap it across at least two lines.

@lru_cache(maxsize=20)
def truncate_line(line, font, max_width):
    truncating = 0
    new_text = line

    # Form an initial estimate of how many characters will fit,
    # leaving some margin.
    t_width = font.getsize(line)[0]
    if t_width <= max_width:
        return line

    avg_char = len(new_text) / t_width
    num_chars = int(max_width / avg_char) + 4
    new_text = new_text[0:num_chars]

    # Leave room for ellipsis
    avail_width = max_width - font.getsize("\u2026")[0] + 6

    # Now perform naive truncation
    t_width = font.getsize(new_text)[0]
    while (t_width > avail_width):
        truncating = 1
        new_text = new_text[:-1]
        t_width = font.getsize(new_text)[0]

    final_text = new_text
    if truncating:
        final_text += "\u2026"

    return final_text


@lru_cache(maxsize=20)
def text_wrap(text, font, max_width, max_lines=None):
    lines = []

    # If the width of the text is smaller than image width
    # we don't need to split it, just add it to the lines array
    # and return
    if font.getsize(text)[0] <= max_width:
        lines.append(text)
    elif max_lines and max_lines == 1:
        # only a single line available, so just truncate
        lines.append(truncate_line(text, font, max_width))
    else:
        # split the line by spaces to get words
        words = text.split(' ')
        i = 0
        # append every word to a line while its width is shorter than max width
        while i < len(words):
            line = ''
            while i < len(words) and font.getsize(
                    line + words[i])[0] <= max_width:
                line = line + words[i] + " "
                i += 1
            if not line:
                line = words[i]
                i += 1
            # when the line gets longer than the max width do not append the word,
            # add the line to the lines array
            lines.append(line)
            if max_lines and len(lines) >= max_lines - 1:
                break

        if max_lines and len(lines) >= max_lines - 1 and i < len(words):
            lines.append(truncate_line(" ".join(words[i:]), font, max_width))

    return lines


# Render text at the specified location, wrapping lines if possible
# and truncating characters on the final line (with ellipsis placed)
# if the string is too wide to display in its entirety.
def render_text_wrap(pil_draw, xy, text, max_width, max_lines, fill, font):
    line_array = text_wrap(text, font, max_width, max_lines)
    line_height = font.getsize('Ahgy')[1]
    (posx, posy) = xy
    for line in line_array:
        pil_draw.text((posx, posy), line, fill, font)
        posy = posy + line_height
    return


# Draw a horizontal (by default) progress bar at the specified
# location, filling from left to right.  A vertical bar can be drawn
# if specified, filling from bottom to top.
#
# Originally, this function was passed all of the location and
# dimensions as separate arguments.  That was subsequently changed,
# but see the remark below regarding use_long_len.
#
# If drawing a circle at the progress point, some care may be needed
# with regarding to the progress bar's thickness.  The circle is
# centered the half-way point of that thickness.  For fairly narrow
# bars, this looks far better if the tickness is an even number of
# pixels.  Similar caution is needed for the circle's radius.
#
def progress_bar(draw,
                 field_dict,
                 progress,
                 use_long_len = False):

    # Pull out colors, position, and size info from field_dict
    bgcolor = field_dict["color_bg"]
    color   = field_dict["color_fg"]

    x = field_dict["posx"]
    y = field_dict["posy"]
    h = field_dict["height"]

    # Due to development history, the key for the remaining dimension
    # of the progress bar varies, depending upon whether it should be
    # vertical or not and the duration.  The caller is responsible for
    # setting use_long_len appropriately.
    #
    # For vertical progress bars, only "len" is expected.

    w = 0
    if field_dict.get("vertical",False) and "len" in field_dict:
        w = field_dict["len"]
    elif use_long_len and "long_len" in field_dict:
        w = field_dict["long_len"]
    elif "short_len" in field_dict:
        w = field_dict["short_len"]
    else:
        w = field_dict.get("len", 0)

    # If we cannot determine that long dimension, just return
    # without rendering anything.
    if w == 0:
        return

    # Background rectangle
    draw.rectangle((x, y, x + w, y + h), fill=bgcolor)

    if progress <= 0:
        progress = 0.001
    if progress > 1:
        progress = 1

    # Foreground rectangle (progress indictor)
    if "vertical" in field_dict.keys():
        dh = h * progress
        draw.rectangle((x, y + h - dh, x + w, y + h), fill=color)
        if "circle" in field_dict.keys():
            r = int(field_dict["circle"])  # radius
            draw.ellipse(
                (x+(0.5*w)-r, y+h-dh-r, x+(0.5*w)+r, y+h-dh+r),
                fill    = field_dict.get("circle_fill","black"),
                outline = field_dict.get("circle_outline","white")
            )

    else:
        dw = w * progress
        draw.rectangle((x, y, x + dw, y + h), fill=color)
        if "circle" in field_dict.keys():
            r = int(field_dict["circle"])  # radius
            draw.ellipse(
                (x+dw-r, y+(0.5*h)-r, x+dw+r, y+(0.5*h)+r),
                fill    = field_dict.get("circle_fill","black"),
                outline = field_dict.get("circle_outline","white")
            )




# Retrieve AirPlay (audio) cover art.
#
# This function is distinct from the more general get_artwork() since
# Kodi (at least Kodi Leia), always makes use of the same temporary
# file to store the current AirPlay cover.  The file is identified
# via a special:// path that must also, if running remotely from Kodi,
# be enabled as a media source in order for HTTP retrieval to work.
#
# Since the name (and path) are always the same, this function checks
# the modification time of the temporary file to decide whether a
# re-fetching is needed.
#
# Due to that time-check we do NOT make use of lru_cache decoration.
# This function therefore still relies upon the caller passing in
# the previously-fetched AirPlay cover (as prev_image).
#

def get_airplay_art(cover_path, prev_image, thumb_width, thumb_height, enlarge=False):
    global _last_image_time, _image_default
    image_url = None
    image_set = False
    resize_needed = False
    cover = None  # used for retrieved artwork, original size

    if not _local_kodi:
        image_path = cover_path
        if DEBUG_ART: print("Airplay image_path : ", image_path) # debug info

        payload = {
            "jsonrpc": "2.0",
            "method": "Files.GetFileDetails",
            "params": {"file": image_path,
                       "properties": ["lastmodified"]
                       },
            "id": "5b",
        }
        response = requests.post(
            rpc_url,
            data=json.dumps(payload),
            headers=headers).json()
        if DEBUG_ART:
            print("Airplay image details: ", json.dumps(response))  # debug info

        new_image_time = None
        try:
            new_image_time = response['result']['filedetails']['lastmodified']
        except BaseException:
            pass

        if DEBUG_ART:
            print("Airplay new_image_time", new_image_time)  # debug info

        if (not prev_image or
            (new_image_time and new_image_time != _last_image_time)):
            payload = {
                "jsonrpc": "2.0",
                "method": "Files.PrepareDownload",
                "params": {"path": image_path},
                "id": "5c",
            }
            response = requests.post(
                rpc_url,
                data=json.dumps(payload),
                headers=headers).json()
            if DEBUG_ART:
                print("Airplay prepare response: ", json.dumps(response))  # debug info

            try:
                image_url = base_url + "/" + \
                    response['result']['details']['path']
                if DEBUG_ART: print("Airplay image_url : ", image_url) # debug info
            except BaseException:
                pass

            r = requests.get(image_url, stream=True)
            # check that the retrieval was successful before proceeding
            if r.status_code == 200:
                try:
                    r.raw.decode_content = True
                    cover = Image.open(io.BytesIO(r.content))
                    image_set = True
                    resize_needed = True
                    _last_image_time = new_image_time
                    _image_default = False
                except BaseException:
                    cover = Image.open(_default_airplay_thumb)
                    prev_image = cover
                    image_set = True
                    resize_needed = True
                    _image_default = True
        else:
            image_set = True

    # We proceed through this code only when running local to Kodi
    if not image_set:
        if _airtunes_re.match(cover_path):
            airplay_thumb = "/storage/.kodi/temp/" + \
                _airtunes_re.match(cover_path).group(1)
            if os.path.isfile(airplay_thumb):
                _last_image_path = airplay_thumb
                _image_default   = False
                resize_needed    = True
            else:
                _last_image_path = _default_airplay_thumb
                _image_default   = True
                resize_needed    = True

            cover = Image.open(_last_image_path)
            prev_image = cover
            image_set  = True

    # is resizing needed?
    if (image_set and resize_needed):
        if (enlarge and (cover.size[0] < thumb_width or
                         cover.size[1] < thumb_height)):

            # Figure out which dimension is the constraint
            # for maintenance of the aspect ratio
            width_enlarge  = thumb_width / float(cover.size[0])
            height_enlarge = thumb_height / float(cover.size[1])
            ratio = min( width_enlarge, height_enlarge )

            new_width  = int( cover.size[0] * ratio )
            new_height = int( cover.size[1] * ratio )
            cover = cover.resize((new_width, new_height))

        else:
            # reduce while maintaining aspect ratio, which should
            # be precisely what thumbnail accomplishes
            cover.thumbnail((thumb_width, thumb_height))

        prev_image = cover

    if image_set:
        return prev_image
    else:
        return None



# Retrieve cover art or a default thumbnail.  Cover art gets resized
# to the provided thumb_width and thumb_height.  (This now applies
# to default images as well.)
#
# Note that details of retrieval seem to differ depending upon whether
# Kodi is playing from its library, from UPnp/DLNA, or from Airplay.
#
# Originally, this function replied upon a prev_image argument being
# passed in, together with storing the incoming cover_path string to a
# _last_image_path global.  Switching the function to be memoized via
# the lru_cached decorator removed the need for both of those
# practices.
#
# With AirPlay artwork now handled separately, the caching should
# permit for returning the same cover_path image, at a given size,
# without the need for any network activity.
#
# Arguments:
#
#  cover_path    string from Kodi InfoLabel providing path to artwork
#  thumb_width   desired pixel width for artwork
#  thumb_height  desired pixel height for artwork
#  use_defaults  boolean indicating whether algorithm should fall
#                 back to default images if unsuccessful at
#                 retrieving artwork
#  enlarge       boolean indicating if artwork should be enlarged
#                 if smaller than the specified width and height
#
@lru_cache(maxsize=18)
def get_artwork(cover_path, thumb_width, thumb_height, use_defaults=False, enlarge=False):
    image_url = None
    image_set = False
    resize_needed = False

    cover = None  # used for retrieved artwork, original size

    if (cover_path != '' and
        (not cover_path.startswith('DefaultVideoCover')) and
        (not cover_path.startswith('DefaultAlbumCover')) and
        (not _airtunes_re.match(cover_path))):

        image_path = cover_path
        if DEBUG_ART: print("image_path : ", image_path) # debug info

        if (image_path.startswith("http://") or
            image_path.startswith("https://")):
            image_url = image_path
        else:
            payload = {
                "jsonrpc": "2.0",
                "method": "Files.PrepareDownload",
                "params": {"path": image_path},
                "id": 5,
            }
            response = requests.post(
                rpc_url, data=json.dumps(payload), headers=headers).json()
            if DEBUG_ART:
                print("PrepareDownload Response: ", json.dumps(response))  # debug info

            try:
                image_url = base_url + "/" + \
                    response['result']['details']['path']
                if DEBUG_ART: print("image_url : ", image_url) # debug info
            except BaseException:
                pass

        r = requests.get(image_url, stream=True)
        # check that the retrieval was successful before proceeding
        if r.status_code == 200:
            try:
                r.raw.decode_content = True
                cover = Image.open(io.BytesIO(r.content))
                image_set = True
                resize_needed = True
            except BaseException:
                image_set = False

    # use default images if we haven't retrieved anything
    if (not image_set and use_defaults):
        default_path = ""

        if cover_path.startswith('DefaultVideoCover'):
            default_path = _default_video_thumb
        else:
            default_path = _default_audio_thumb

        cover = Image.open(default_path)
        image_set = True
        resize_needed = True

    if (image_set and resize_needed):

        if (enlarge and (cover.size[0] < thumb_width or
                         cover.size[1] < thumb_height)):

            # Figure out which dimension is the constraint
            # for maintenance of the aspect ratio
            width_enlarge  = thumb_width / float(cover.size[0])
            height_enlarge = thumb_height / float(cover.size[1])
            ratio = min( width_enlarge, height_enlarge )

            new_width  = int( cover.size[0] * ratio )
            new_height = int( cover.size[1] * ratio )
            cover = cover.resize((new_width, new_height))

        else:
            # reduce while maintaining aspect ratio, which should
            # be precisely what thumbnail accomplishes
            cover.thumbnail((thumb_width, thumb_height))

    return cover



# Paste retrieve artwork into the Pillow Image being rendered,
# positioning it based upon the based dictionary (from either a
# layout's "thumb" entry or one entry from its fields array) and the
# now-resized artwork.
#
# Some of the expected or possible keys within the dictionary are:
#
#  posx       Horizontal position for artwork's upper-left corner
#  posy       Vertical position for artwork's upper-left corner
#  width      Expected pixel width of artwork
#  height     Expected pixel height of artwork
#  size       Pixel width and height if artwork is square
#
#  center     Boolean indicating art should be centered on-screen,
#               rather than use posx, posy for position.
#
#  enlarge    Boolean indicating art can be enlarged as part
#               of get_artwork() processing.  If this flag
#               is set, then there is point to also specifying
#               center_sm.
#
#  center_sm  Boolean indicating that art should be centered
#               at the position that it would have been located
#               if it was full-size
#
# Note that the caller is responsible for handling any display_if or
# display_ifnot conditional.  Those are NOT examined here.
#
#
# Arguments:
#
#   image       Image object representing screen
#   artwork     Image object for the artwork
#   field_dict  Dictionary from layout
#
def paste_artwork(image, artwork, field_dict):
    if "size" in field_dict:
        height = field_dict["size"]
        width  = field_dict["size"]
    else:
        height = field_dict["height"]
        width  = field_dict["width"]

    if field_dict.get("center", 0):
        image.paste(artwork,
                    (int((_frame_size[0] - artwork.width) / 2),
                     int((_frame_size[1] - artwork.height) / 2)))

    elif (field_dict.get("center_sm", 0) and
          (artwork.width < width or
           artwork.height < height)):
        new_x = field_dict["posx"]
        new_y = field_dict["posy"]
        if artwork.width < width:
            new_x += int((width / 2) -
                         (artwork.width / 2))
        if artwork.height < height:
            new_y += int((height / 2) -
                         (artwork.height / 2))
        image.paste(artwork, (new_x, new_y))
    else:
        image.paste(
            artwork,
            (field_dict["posx"],
             field_dict["posy"]))



# Provide a mechanism for interpolation of format strings containing
# InfoLabel fields denoted with curly braces.  For example, providing
# substution for a string such as
#
#   Freq: {System.CpuFrequency}
#
# The normal python format_map() method balks at the above, since the
# InfoLabel name, System.CpuFrequency, contains a dot or period.  The
# normal string formatter allows one to invoke attributes (or methods)
# for embedded variables.  We instead just want the whole curly-brace
# expression treated as a string for use as a dictionary key.

_InfoLabel_re = re.compile(r'\{(\w*\.?\w*)\}')

def format_InfoLabels(orig_str, kodi_info, screen_mode=None, layout_name=""):
    matches = set(_InfoLabel_re.findall(orig_str))
    new_str = orig_str
    for field in matches:
        if field in kodi_info.keys():
            # lookup substitution using InfoLabels
            new_str = new_str.replace('{' + field + '}', kodi_info[field])
        elif field in STRING_CB.keys():
            # lookup substitution from string-manipulation callbacks
            new_str = new_str.replace('{' + field + '}',
                                      STRING_CB[field](
                                          kodi_info,
                                          screen_mode,
                                          layout_name
                                      ))
        else:
            new_str = new_str.replace('{' + field + '}', '')
    return new_str



# Permit a layout's thumb, prog, or fields elements to specify a basic
# conditional to control their display.
#
# The dictionary keys
#
#   display_if     or
#   display_ifnot
#
# are assumed to provide a two-element list:
#
#  - The first element in should be either an InfoLabel name
#    or the name of a string callback function (i.e., in the STRING_CB
#    table).
#
#  - The second element is a string.  For display_if, the string must
#    equal that which results from "evaluating" the InfoLabel or
#    callback for the element to be displayed.  For display_ifnot, the
#    specified string must NOT equal the return value for the element
#    to be displayed.
#
# At most one of display_if or display_ifnot can be present for an
# element.
#
# Arguments to this function are as follows:
#
#  dictionary for the layout element of interest
#  dictionary of InfoLabels from kodi
#  screen mode, as an Enum
#  layout name, as a string
#
# The return value is a boolean, True if the element should be
# displayed and False if the element should be skipped.
#
def check_display_expr(field_dict, info, screen_mode, layout_name):
    func_name = None
    test_str = None
    check_equal = True

    if ("display_if" not in field_dict and
        "display_ifnot" not in field_dict):
        return True

    if ("display_if" in field_dict and
        type(field_dict["display_if"]) == list):
        func_name = field_dict["display_if"][0]
        test_str  = field_dict["display_if"][1]

    elif ("display_ifnot" in field_dict and
          type(field_dict["display_ifnot"]) == list):
        func_name = field_dict["display_ifnot"][0]
        test_str  = field_dict["display_ifnot"][1]
        check_equal = False

    if (not func_name and not test_str):
        return True

    # Permit func_name to either be an InfoLabel or a string
    # callback function
    if func_name in info:
        result_str = str(info[func_name])
    elif func_name in STRING_CB:
        result_str = STRING_CB[func_name](
            info,              # Kodo InfoLabel response
            screen_mode,       # screen mode, as enum
            layout_name        # layout name, as string
            )
    else:
        # Cannot find func_name, don't display element!
        return False

    if DEBUG_FIELDS:
        print("  display_expr: result of '" + func_name + "' was '" + result_str + "'")

    # Perform case-insensitive comparisons if testing against the
    # strings "true" and "false", so as to try and minimize the pain
    # of TOML versus Python differences.

    if test_str.lower() == "true" or test_str.lower() == "false":
        if check_equal:
            return (result_str.lower() == test_str.lower())
        else:
            return (result_str.lower() != test_str.lower())
    else:
        if check_equal:
            return (result_str == test_str)
        else:
            return (result_str != test_str)


# Render all layout fields, stepping through the fields array from the
# layout dictionary that is passed in.
#
# The final argument determines whether one wants to render all of the
# static fields or just the dynamic ones.  That, together with the
# screen_mode argument, permits this function to be called by
#
#   audio_screen_static() and audio_screen_dynamic()
#   video_screen_static() and video_screen_dynamic()
#
# Full set of arguments is as follows:
#
#  image        Image object for Pillow
#  draw         ImageDraw object, tied to image
#  layout       Layout dictionary to use for screen update
#  info         Dictionary containing Kodi InfoLabel response
#  screen_mode  Enumerated type indicating AUDIO, VIDEO, SLIDE, or STATUS
#  layout_name  Name, as a string, for the in-use layout
#  dynamic      Boolean flag, set for dynamic screen updates
#
#
def draw_fields(image, draw, layout, info,
                screen_mode=None, layout_name="", dynamic=False):

    # Pull out the layout's array of fields
    field_list = layout.get("fields", [])
    for field_dict in field_list:
        display_string = None

        if DEBUG_FIELDS:
            print("Examining field: ", field_dict)

        if "anchor" in field_dict.keys():
            anchor_pos = field_dict["anchor"]
        else:
            anchor_pos = "la"


        # Skip over the fields that aren't desired for this
        # invocation, based on static vs dynamic.
        #
        # Just show everything for a STATUS screen or
        # a SLIDE screen.

        if (screen_mode == ScreenMode.STATUS or
            screen_mode == ScreenMode.SLIDE):
            pass
        else:
            if dynamic:
                if not field_dict.get("dynamic", 0):
                    continue
            else:
                if field_dict.get("dynamic", 0):
                    continue

        # Check for any display conditional expression
        if ("display_if" in field_dict or
            "display_ifnot" in field_dict):
            if (not check_display_expr(field_dict,
                                       info,
                                       screen_mode,
                                       layout_name)):
                # skip this field
                continue

        # Check for any defined callback functions.  If an entry
        # exists in the lookup table, invoke the specified function
        # with all of the arguments discussed in earlier comments.

        if field_dict["name"] in ELEMENT_CB:
            display_string = ELEMENT_CB[field_dict["name"]](
                image,             # Image instance
                draw,              # ImageDraw instance
                info,              # Kodo InfoLabel response
                field_dict,        # layout details for field
                screen_mode,       # screen mode, as enum
                layout_name        # layout name, as string
            )
            # print("Invoked element CB for", field_dict["name"],"; received back '", display_string, "'")

            # still permit prefix and suffix options
            if (display_string != "" and
                ("prefix" in field_dict or "suffix" in field_dict)):
                display_string = (field_dict.get("prefix", "") +
                                  display_string +
                                  field_dict.get("suffix", ""))

        elif field_dict["name"] in STRING_CB:
            display_string = STRING_CB[field_dict["name"]](
                info,              # Kodo InfoLabel response
                screen_mode,       # screen mode, as enum
                layout_name        # layout name, as string
            )
            # print("Invoked string CB for", field_dict["name"],"; received back '", display_string, "'")

            # still permit prefix and suffix options
            if (display_string != "" and
                ("prefix" in field_dict or "suffix" in field_dict)):
                display_string = (field_dict.get("prefix", "") +
                                  display_string +
                                  field_dict.get("suffix", ""))

        else:
            if (# name corresponds to a non-empty InfoLabel -OR-
                (field_dict["name"] in info and info[field_dict["name"]] != "") or
                # entry has a format_str specified for use
                ("format_str" in field_dict)):

                # use format_str or prefix/suffic approach, in that order
                if field_dict.get("format_str", ""):
                    display_string = format_InfoLabels(
                        field_dict["format_str"], info, screen_mode, layout_name)
                elif field_dict["name"] in info:
                    display_string = (field_dict.get("prefix", "") +
                                      info[field_dict["name"]] +
                                      field_dict.get("suffix", ""))


        # if the string to display is empty, move on to the next field,
        # otherwise render it.
        if (not display_string or display_string == ""):
            continue

        # check for any exclusions
        if "exclude" in field_dict:
            if type(field_dict["exclude"]) == str:
                if display_string == field_dict["exclude"]:
                    continue
            elif type(field_dict["exclude"]) == list:
                if display_string in field_dict["exclude"]:
                    continue

        # render any label first
        if "label" in field_dict:
            draw.text((field_dict["lposx"], field_dict["lposy"]),
                      field_dict["label"],
                      fill=field_dict["lfill"], font=field_dict["lfont"])

        if "wrap" in field_dict.keys():
            render_text_wrap(draw,
                             (field_dict["posx"], field_dict["posy"]),
                             display_string,
                             max_width=field_dict["max_width"],
                             max_lines=field_dict["max_lines"],
                             fill=field_dict["fill"],
                             font=field_dict["font"])
        elif "trunc" in field_dict.keys():
            render_text_wrap(draw,
                             (field_dict["posx"], field_dict["posy"]),
                             display_string,
                             max_width=_frame_size[0] -
                             field_dict["posx"],
                             max_lines=1,
                             fill=field_dict["fill"],
                             font=field_dict["font"])
        else:
            draw.text((field_dict["posx"], field_dict["posy"]),
                      display_string,
                      fill=field_dict["fill"],
                      font=field_dict["font"],
                      anchor=anchor_pos)



# Callback hook for status/info selection
#
#   User script can override by assignment, e.g.
#
#     kodi_display_panel.STATUS_SELECT_FUNC = my_status_selection
#
#
#   Here is an example, complete with the namespace qualification one
#   would need when using this code in an external startup script.
#
#     def my_status_select(info):
#         if info['System.ScreenSaverActive']:
#             return kodi_panel_display.IDisplay["screensaver"]
#         else:
#             return kodi_panel_display.IDisplay[config.settings["STATUS_INITIAL"]]
#
#     kodi_panel_display.STATUS_SELECT_FUNC = my_status_select
#
#
STATUS_SELECT_FUNC = None


# Idle status/info screen (often shown upon a screen press)
#
#   First two arguments are Pillow Image and ImageDraw objects.
#   Third argument is a dictionary loaded from Kodi with info fields.
#
# Unlike audio_screen_static() and video_screen_static(), this
# function is NOT expected to create a completely new Image object.
# So, the background fill (if any) is handled in a slightly different
# manner.
#
def status_screen(image, draw, kodi_status):
    global info_dmode

    # Permit Kodi InfoLabels and InfoBooleans to determine a status
    # screen layout, if everything has been suitably defined.
    if (STATUS_LAYOUT_AUTOSELECT and STATUS_SELECT_FUNC):
        info_dmode = STATUS_SELECT_FUNC(kodi_status)
        layout = STATUS_LAYOUT[info_dmode.name]
    else:
        # Historically, one could define just one layout for status,
        # making the dictionary just a single level deep (no name)
        info_dmode = None
        layout = STATUS_LAYOUT

    # Draw any user-specified rectangle or load background
    # image for layout
    if "background" in layout:
        if ("rectangle" in layout["background"] and
            layout["background"]["rectangle"]):
            draw.rectangle(
                [(0, 0), (_frame_size[0], _frame_size[1])],
                fill    = layout["background"].get("fill","black"),
                outline = layout["background"].get("outline","black"),
                width   = layout["background"].get("width",1)
            )

        elif ("image" in layout["background"] and
              os.path.isfile(layout["background"]["image"]) and
              os.access(layout["background"]["image"], os.R_OK)):
            # assume that image is properly sized for the display
            bg_image = Image.open(layout["background"]["image"])
            image.paste(bg_image, (0,0))

        elif ("fill" in layout["background"]):
            draw.rectangle(
                [(0, 0), (_frame_size[0], _frame_size[1])],
                fill    = layout["background"].get("fill","black"),
                outline = "black",
                width   = 1
            )

    # Kodi logo, if desired
    if "thumb" in layout.keys():
        thumb_dict = layout["thumb"]
        kodi_icon = Image.open(_kodi_thumb)

        if (thumb_dict.get("enlarge", False) and
            (kodi_icon.size[0] < thumb_dict["size"] or
             kodi_icon.size[1] < thumb_dict["size"])):
            width_enlarge  = thumb_dict["size"] / float(kodi_icon.size[0])
            height_enlarge = thumb_dict["size"] / float(kodi_icon.size[1])
            ratio = min( width_enlarge, height_enlarge )

            new_width  = int( kodi_icon.size[0] * ratio )
            new_height = int( kodi_icon.size[1] * ratio )
            kodi_icon = kodi_icon.resize((new_width, new_height))

        else:
            kodi_icon.thumbnail((thumb_dict["size"], thumb_dict["size"]))

        image.paste(
            kodi_icon,
            (thumb_dict["posx"],
             thumb_dict["posy"]))

    # go through all layout fields, if any
    if "fields" not in layout.keys():
        return

    draw_fields(image, draw,
                layout, kodi_status,
                ScreenMode.STATUS, "STATUS_LAYOUT")



# Render the static portion of audio screens
#
#  First argument is the layout dictionary to use
#  Second argument is a dictionary loaded from Kodi with relevant InfoLabels
#
def audio_screen_static(layout, info):
    global _last_thumb

    # Create new Image and ImageDraw objects
    if ("background" in layout and
        "fill" in layout["background"] and
        ("rectangle" not in layout["background"] or
         not layout["background"]["rectangle"])):
        image = Image.new('RGB', (_frame_size), layout["background"]["fill"])
    else:
        image = Image.new('RGB', (_frame_size), 'black')

    draw = ImageDraw.Draw(image)

    # Draw any user-specified rectangle or load background
    # image for layout
    if "background" in layout:
        if ("rectangle" in layout["background"] and
            layout["background"]["rectangle"]):
            draw.rectangle(
                [(0, 0), (_frame_size[0], _frame_size[1])],
                fill    = layout["background"].get("fill","black"),
                outline = layout["background"].get("outline","black"),
                width   = layout["background"].get("width",1)
            )

        elif ("image" in layout["background"] and
              os.path.isfile(layout["background"]["image"]) and
              os.access(layout["background"]["image"], os.R_OK)):
            # assume that image is properly sized for the display
            bg_image = Image.open(layout["background"]["image"])
            image.paste(bg_image, (0,0))


    # Mimic the display conditional functionality that is provided for
    # entries in the fields array of a layout, but applied here to
    # cover art display.
    #
    # Unfortunately, since we're not in the middle of a loop, we can't
    # make use of the simple continue statement as draw_fields() does.

    show_thumb = False
    thumb_dict = {}

    if "thumb" in layout.keys():
        show_thumb = True
        thumb_dict = layout["thumb"]

        # If the field has a display conditional (display_cond)
        # defined, let's test that to decide if we should proceed.
        if ("display_if" in thumb_dict or
            "display_ifnot" in thumb_dict):
            show_thumb = check_display_expr(thumb_dict,
                                            info,
                                            ScreenMode.AUDIO,
                                            audio_dmode.name)

    # Audio covers are expected to be square and thus have only a
    # single dimension -- size -- specified in the layout element.
    # Provide some flexibility, though.
    width  = 0
    height = 0

    if ("size" in thumb_dict):
        width  = thumb_dict["size"]
        height = thumb_dict["size"]
    elif ("width" in thumb_dict and
          "height" in thumb_dict):
        width  = thumb_dict["width"]
        height = thumb_dict["height"]
    else:
        show_thumb = False


    # Conditionally retrieve cover image from Kodi, if it exists and
    # needs a refresh.  AirPlay cover art must be handled specially.
    if show_thumb:

        if _airtunes_re.match(info['MusicPlayer.Cover']):
            _last_thumb = get_airplay_art(info['MusicPlayer.Cover'], _last_thumb,
                                          width, height,
                                          enlarge=thumb_dict.get("enlarge", False))
        else:
            _last_thumb = get_artwork(info['MusicPlayer.Cover'],
                                      width, height,
                                      use_defaults=True,
                                      enlarge=thumb_dict.get("enlarge", False))


        if _last_thumb:
            paste_artwork(image, _last_thumb, thumb_dict)
    else:
        _last_thumb = None

    # All static layout fields
    draw_fields(image, draw,
                layout, info,
                ScreenMode.AUDIO, audio_dmode.name,
                dynamic=0)

    # Return new image
    return image


# Render the changing portion of audio screens
#
#  First two arguments are Pillow Image and ImageDraw objects.
#  Third argument is the layout dictionary to use
#  Fourth argument is a dictionary loaded from Kodi with relevant InfoLabels.
#  Fifth argument is a float representing progress through the audio file.
#
def audio_screen_dynamic(image, draw, layout, info, prog):

    # All dynamic layout fields
    draw_fields(image, draw,
                layout, info,
                ScreenMode.AUDIO, audio_dmode.name,
                dynamic=1)

    # Progress bar, if present and should be displayed
    show_prog = False
    prog_dict = {}

    if (prog == -1 or "prog" not in layout.keys()):
        show_prog = False
    else:
        show_prog = True
        prog_dict = layout["prog"]

        # If the field has a display conditional (display_cond)
        # defined, let's test that to decide if we should proceed.
        if ("display_if" in prog_dict or
            "display_ifnot" in prog_dict):
            show_prog = check_display_expr(prog_dict,
                                           info,
                                           ScreenMode.AUDIO,
                                           audio_dmode.name)


    if show_prog:
        progress_bar(
            draw, prog_dict, prog,
            use_long_len = (info['MusicPlayer.Time'].count(":") == 2)
        )



# Audio selection heuristic
#
#  See comments regarding video_selection_default().  We're just
#  mimicking that functionality on the audio side.
#
#  Here we provide no actual heuristic, just the framework to permit
#  for end-user extension.
#
#  Sole argument is a dictionary containing the audio InfoLabels
#  retrieved from Kodi.  Function MUST return the ADisplay
#  enumeration to use for the screen update.
#
def audio_select_default(info):
    return audio_dmode


# Callback hook
#
#   User script can override by assignment, e.g.
#
#     kodi_display_panel.AUDIO_SELECT_FUNC = my_selection_func
#
AUDIO_SELECT_FUNC = audio_select_default


# Audio info screens (shown when music is playing)
#
#  First two arguments are Pillow Image and ImageDraw objects.
#  Third argument is a dictionary loaded from Kodi with info fields.
#
#  The rendering is divided into two phases -- first all of the static
#  elements (on a new image) and then the dynamic fields and progress
#  bar.  The static image gets reused when possible.
#
#  Switching to this approach seems to keep the active update loop to
#
#   - around 20% CPU load for an RPi Zero W and
#   - around 5% CPU load on an RPi 4.
#
#
# NOTES:
#
#  Unfortunately, Kodi Leia doesn't seem to capture the field
#  that JRiver Media Center offers up for its "Composer" tag,
#  namely
#
#      upnp:author role="Composer"
#
#  I've tried several variants with no success.
#
#  Also, BitsPerSample appears to be unreliable, as it can
#  get "stuck" at 32.  The SampleRate behaves better.  None
#  of these problems likely occur when playing back from a
#  Kodi-local library.
#

def audio_screens(image, draw, info):
    global _static_image, _static_video
    global _last_track_num, _last_track_title, _last_track_album, _last_track_time
    global _last_thumb
    global audio_dmode

    # Permit audio content to drive selected layout
    if (AUDIO_LAYOUT_AUTOSELECT and AUDIO_SELECT_FUNC):
        audio_dmode = AUDIO_SELECT_FUNC(info)

    # Retrieve layout details
    layout = AUDIO_LAYOUT[audio_dmode.name]

    # Calculate progress in media
    prog = calc_progress(
        info["MusicPlayer.Time"],
        info["MusicPlayer.Duration"],
        audio_dmode.name
    )

    if (_static_image and (not _static_video) and
        info["MusicPlayer.TrackNumber"] == _last_track_num and
        info["MusicPlayer.Title"] == _last_track_title and
        info["MusicPlayer.Album"] == _last_track_album and
            info["MusicPlayer.Duration"] == _last_track_time):
        pass
    else:
        _last_thumb = None
        _static_image = audio_screen_static(layout, info)
        _static_video = False
        _last_track_num = info["MusicPlayer.TrackNumber"]
        _last_track_title = info["MusicPlayer.Title"]
        _last_track_album = info["MusicPlayer.Album"]
        _last_track_time = info["MusicPlayer.Duration"]

    # use _static_image as the starting point
    image.paste(_static_image, (0, 0))
    audio_screen_dynamic(image, draw, layout, info, prog)



# Render the static portion of video screens
def video_screen_static(layout, info):
    global _last_thumb

    # Create new Image and ImageDraw objects
    if ("background" in layout and
        "fill" in layout["background"] and
        ("rectangle" not in layout["background"] or
         not layout["background"]["rectangle"])):
        image = Image.new('RGB', (_frame_size), layout["background"]["fill"])
    else:
        image = Image.new('RGB', (_frame_size), 'black')

    draw = ImageDraw.Draw(image)

    # Draw any user-specified rectangle or load background
    # image for layout
    if "background" in layout:
        if ("rectangle" in layout["background"] and
            layout["background"]["rectangle"]):
            draw.rectangle(
                [(0, 0), (_frame_size[0], _frame_size[1])],
                fill    = layout["background"].get("fill","black"),
                outline = layout["background"].get("outline","black"),
                width   = layout["background"].get("width",1)
            )

        elif ("image" in layout["background"] and
              os.path.isfile(layout["background"]["image"]) and
              os.access(layout["background"]["image"], os.R_OK)):
            # assume that image is properly sized for the display
            bg_image = Image.open(layout["background"]["image"])
            image.paste(bg_image, (0,0))


    # Mimic the display conditional functionality that is provided for
    # entries in the fields array of a layout, but applied here to
    # cover art display.
    #
    # Unfortunately, since we're not in the middle of a loop, we can't
    # make use of the simple continue statement as draw_fields() does.

    show_thumb = False
    thumb_dict = {}

    if "thumb" in layout.keys():
        show_thumb = True
        thumb_dict = layout["thumb"]

        # If the field has a display conditional (display_cond)
        # defined, let's test that to decide if we should proceed.
        if ("display_if" in thumb_dict or
            "display_ifnot" in thumb_dict):
            show_thumb = check_display_expr(thumb_dict,
                                            info,
                                            ScreenMode.VIDEO,
                                            video_dmode.name)

    # Retrieve cover image from Kodi, if it exists and needs a refresh
    if show_thumb:
        _last_thumb = get_artwork(info['VideoPlayer.Cover'],
                                  thumb_dict["width"], thumb_dict["height"],
                                  use_defaults=True,
                                  enlarge=thumb_dict.get("enlarge", False))
        if _last_thumb:
            paste_artwork(image, _last_thumb, thumb_dict)
    else:
        _last_thumb = None

    # All static layout fields
    draw_fields(image, draw,
                layout, info,
                ScreenMode.VIDEO, video_dmode.name,
                dynamic=0)

    # Return new image
    return image


# Render the changing portion of video screens
#
#  First two arguments are Pillow Image and ImageDraw objects.
#  Third argument is the layout dictionary to use
#  Fourth argument is a dictionary loaded from Kodi with relevant info fields.
#  Fifth argument is a float representing progress through the video file.
#
def video_screen_dynamic(image, draw, layout, info, prog):

    # All dynamic layout fields
    draw_fields(image, draw,
                layout, info,
                ScreenMode.VIDEO, video_dmode.name,
                dynamic=1)

    # Progress bar, if present and should be displayed
    show_prog = False
    prog_dict = {}

    if (prog == -1 or "prog" not in layout.keys()):
        show_prog = False
    else:
        show_prog = True
        prog_dict = layout["prog"]

        # If the field has a display conditional (display_cond)
        # defined, let's test that to decide if we should proceed.
        if ("display_if" in prog_dict or
            "display_ifnot" in prog_dict):
            show_prog = check_display_expr(prog_dict,
                                           info,
                                           ScreenMode.VIDEO,
                                           video_dmode.name)

    if show_prog:
        progress_bar(
            draw, prog_dict, prog,
            use_long_len = (info['VideoPlayer.Time'].count(":") == 2)
        )



# Video selection heuristic
#
#   Default heuristic to determine layout based upon populated
#   InfoLabels, if enabled via settings.  Originally suggested by
#   @noggin and augmented by @nico1080 in CoreELEC Forum discussion.
#
#   Entries within VIDEO_LAYOUT don't have to exist, as selection will
#   just fall-through based on the key checks below.  In other wise,
#   if a given layout name doesn't exist, the heuristic just ends up
#   using the default mode as specified by the setup file's
#   VLAYOUT_INITIAL variable.
#
#   The heuristic is currently as follows:
#
#   Check                                  Selected layout
#   ------------------------------------------------------------
#   1. playing a pvr://recordings file     V_PVR
#   2. playing a pvr://channels file       V_LIVETV
#   3. TVShowTitle label is non-empty      V_TV_SHOW
#   4. OriginalTitle label is non-empty    V_MOVIE
#   otherwise                              default (VLAYOUT_INITIAL)
#   ------------------------------------------------------------
#
#   The video_screens() function invokes this function via a "hook"
#   variable.  Reassignment of that variable permits an end-user's
#   script to completely override the above heurstic.
#
#   The sole argument is a dictionary containing the video InfoLabels
#   retrieved from Kodi.  Function MUST return the VDisplay
#   enumeration to use for the screen update.
#
def video_select_default(info):
    if (info["Player.Filenameandpath"].startswith("pvr://recordings") and
        "V_PVR" in VIDEO_LAYOUT):
        new_mode = VDisplay["V_PVR"]     # PVR TV shows
    elif (info["Player.Filenameandpath"].startswith("pvr://channels") and
          "V_LIVETV" in VIDEO_LAYOUT):
        new_mode = VDisplay["V_LIVETV"]  # live TV
    elif (info["VideoPlayer.TVShowTitle"] != '' and
          "V_TV_SHOW" in VIDEO_LAYOUT):
        new_mode = VDisplay["V_TV_SHOW"] # library TV shows
    elif (info["VideoPlayer.OriginalTitle"] != '' and
          "V_MOVIE" in VIDEO_LAYOUT):
        new_mode = VDisplay["V_MOVIE"]   # movie
    else:
        # use the default mode specified from setup
        new_mode = VDisplay[config.settings["VLAYOUT_INITIAL"]]

    return new_mode


# Callback hook
#
#   User script can override by assignment, e.g.
#
#     kodi_display_panel.VIDEO_SELECT_FUNC = my_selection_func
#
VIDEO_SELECT_FUNC = video_select_default


# Video info screens (shown when a video is playing)
#
#  First two arguments are Pillow Image and ImageDraw objects.
#  Third argument is a dictionary loaded from Kodi with relevant info fields.
#
#  See static/dynamic description given for audio_screens()
#
def video_screens(image, draw, info):
    global _static_image, _static_video
    global _last_video_title, _last_video_episode, _last_video_time
    global video_dmode

    # Permit video content to drive selected layout
    if (VIDEO_LAYOUT_AUTOSELECT and VIDEO_SELECT_FUNC):
        video_dmode = VIDEO_SELECT_FUNC(info)

    # Retrieve layout details
    layout = VIDEO_LAYOUT[video_dmode.name]

    # Calculate progress in media
    prog = calc_progress(
        info["VideoPlayer.Time"],
        info["VideoPlayer.Duration"],
        video_dmode.name
    )

    if (_static_image and _static_video and
        info["VideoPlayer.Title"] == _last_video_title and
        info["VideoPlayer.Episode"] == _last_video_episode and
            info["VideoPlayer.Duration"] == _last_video_time):
        pass
    else:
        _static_image = video_screen_static(layout, info)
        _static_video = True
        _last_video_title = info["VideoPlayer.Title"]
        _last_video_episode = info["VideoPlayer.Episode"]
        _last_video_time = info["VideoPlayer.Duration"]

    # use _static_image as the starting point
    image.paste(_static_image, (0, 0))
    video_screen_dynamic(image, draw, layout, info, prog)




# Callback hook
#
#   User script can override by assignment, e.g.
#
#     kodi_display_panel.SLIDESHOW_SELECT_FUNC = my_selection_func
#
SLIDESHOW_SELECT_FUNC = None


# Slideshow info screens (shown when a photo slideshow is in progress)
#
#  First two arguments are Pillow Image and ImageDraw objects.
#  Third argument is a dictionary loaded from Kodi with relevant info fields.
#
# At present, this function is closest in nature to status_screen(),
# without any distinction between static and dynamic elements.  That
# assumption is reflect with a conditional in the draw_fields()
# function.  That conditional will need to be modified if there is a
# change to this assumption.
#
# Custom backgrounds are handled in the same fashion as in
# status_screen(), since a new Image object isn't expected.
#
def slideshow_screens(image, draw, info):
    global slide_dmode

    # Permit audio content to drive selected layout
    if (SLIDESHOW_LAYOUT_AUTOSELECT and SLIDESHOW_SELECT_FUNC):
        slide_dmode = SLIDESHOW_SELECT_FUNC(info)

    # Retrieve layout details
    layout = SLIDESHOW_LAYOUT[slide_dmode.name]

    # Draw any user-specified rectangle or load background
    # image for layout
    if "background" in layout:
        if ("rectangle" in layout["background"] and
            layout["background"]["rectangle"]):
            draw.rectangle(
                [(0, 0), (_frame_size[0], _frame_size[1])],
                fill    = layout["background"].get("fill","black"),
                outline = layout["background"].get("outline","black"),
                width   = layout["background"].get("width",1)
            )

        elif ("image" in layout["background"] and
              os.path.isfile(layout["background"]["image"]) and
              os.access(layout["background"]["image"], os.R_OK)):
            # assume that image is properly sized for the display
            bg_image = Image.open(layout["background"]["image"])
            image.paste(bg_image, (0,0))

        elif ("fill" in layout["background"]):
            draw.rectangle(
                [(0, 0), (_frame_size[0], _frame_size[1])],
                fill    = layout["background"].get("fill","black"),
                outline = "black",
                width   = 1
            )

    # go through all layout fields, if any
    if "fields" not in layout.keys():
        return

    draw_fields(image, draw,
                layout, info,
                ScreenMode.SLIDE, slide_dmode.name)


# Given current position ([h:]m:s) and duration, calculate
# percentage done as a float for progress bar display.
#
# A -1 return value causes the progress bar NOT to be rendered.
#
# If one wants the progress percentage to be calculated by Kodi, then
# in Kodi Leia it must be fetched separately!  An additional JSON-RPC
# call like the following is necessary:
#
#   payload = {
#       "jsonrpc": "2.0",
#       "method"  : "Player.GetProperties",
#       "params"  : {
#           "playerid": 0,
#           "properties" : ["percentage"],
#       },
#       "id"      : "prog",
#   }
#
# That particular hiccup looks to be fixed in Kodi Matrix.  However,
# since we have time and duration values, we should be able to
# calculate the percentage done ourselves.
#
# The layout_name, as a string, is passed in case a user-override
# function wants to use that to modify calculations.
#
def calc_progress(time_str, duration_str, layout_name):
    if (time_str == "" or duration_str == ""):
        return -1
    if not (1 <= time_str.count(":") <= 2 and
            1 <= duration_str.count(":") <= 2):
        return -1

    cur_secs = sum(
        int(x) * 60 ** i for i,
        x in enumerate(
            reversed(
                time_str.split(':'))))
    total_secs = sum(
        int(x) * 60 ** i for i,
        x in enumerate(
            reversed(
                duration_str.split(':'))))

    # If either cur_secs or total_secs is negative, we fall through
    # and return -1, hiding the progress bar.  We do explicitly cap
    # the maximum progress that is possible at 1.

    if (cur_secs >= 0 and total_secs > 0):
        if (cur_secs >= total_secs):
            return 1
        else:
            return cur_secs / total_secs
    else:
        return -1


# Activate display backlight, making use of luma's PWM capabilities if
# enabled.  Note that scripts using hardware PWM on RPi are likely to
# override this function.
#
def screen_on():
    if (not USE_BACKLIGHT or DEMO_MODE):
        return
    if USE_PWM:
        device.backlight(PWM_LEVEL)
    else:
        device.backlight(True)

# Turn off the display backlight, making use of luma's PWM
# capabilities if enabled.  Note that scripts using hardware PWM on
# RPi are likely to override this function.
#
def screen_off():
    if (not USE_BACKLIGHT or DEMO_MODE):
        return
    if USE_PWM:
        device.backlight(0)
    device.backlight(False)


# Kodi-polling and image rendering function
#
# Determine Kodi state and, if something of interest is playing,
# retrieve all the relevant information and get it drawn.
#
# The argument provides a mechanism for touch_int() to force
# a direct update.
#
def update_display(touched=False):
    global _kodi_playing
    global _last_thumb, _static_image
    global _screen_press, _screen_active, _screen_offtime
    global audio_dmode, video_dmode

    _lock.acquire()

    # Start with a blank slate, if there's no static image
    if (not (_kodi_connected and _static_image)):
        draw.rectangle(
            [(0, 0), (_frame_size[0], _frame_size[1])], 'black', 'black')

    # Check if the _screen_active time has expired, unless we're
    # always showing an idle status screen.
    if not IDLE_STATUS_ENABLED:
        if (_screen_active and datetime.now() >= _screen_offtime):
            _screen_active = False
            if not _kodi_playing:
                screen_off()


    # Ask Kodi whether anything is playing...
    #
    #   I was originally under the impression that JSON-RPC calls can
    #   only invoke one method per call.  Later, when implementing
    #   support for InfoBoolean retrieval, I learned about batch
    #   JSON-RPC.  That mechanism is used below to retrieve InfoLabels
    #   and InfoBooleans together.
    #
    #   Nevertheless, at this point in the flow we do not yet know
    #   Kodi's state.  Unless we wish to make a "blind" call and
    #   ask for *every* InfoLabel and every InfoBoolean of possible
    #   interest, we must make 2 distinct network calls.
    #
    #   Over wifi on an RPi3 on my home network, each call seems to
    #   take ~0.025 seconds.
    #
    payload = {
        "jsonrpc": "2.0",
        "method": "Player.GetActivePlayers",
        "id": 3,
    }
    response = requests.post(
        rpc_url,
        data=json.dumps(payload),
        headers=headers).json()

    if ('result' not in response.keys() or
        len(response['result']) == 0 or
        (response['result'][0]['type'] == 'picture' and not SLIDESHOW_ENABLED) or
        (response['result'][0]['type'] == 'video' and not VIDEO_ENABLED) or
        (response['result'][0]['type'] == 'audio' and not AUDIO_ENABLED)):

        # Nothing is playing or something for which no display screen
        # is available.
        _kodi_playing = False

        # If there /was/ a static image, let's blank the screen for
        # the idle status screen.  This code may change once we permit
        # for customized backgrounds, but this should do for the
        # moment.
        if (_static_image and IDLE_STATUS_ENABLED):
            draw.rectangle(
                [(0, 0), (_frame_size[0], _frame_size[1])], 'black', 'black')

        # Check for screen press before proceeding.  A press when idle
        # generates the status screen.
        _last_image_time = None
        _last_thumb = None
        _static_image = None

        if _screen_press.is_set() or touched:
            _screen_press.clear()
            _screen_active = True
            _screen_offtime = datetime.now() + timedelta(seconds=_screen_wake)

        if ((_screen_active or IDLE_STATUS_ENABLED) and
            STATUS_ENABLED):

            # Idle status screen
            if len(response['result']) == 0:
                summary = "Idle"
            elif response['result'][0]['type'] == 'video':
                summary = "Video playing"
            elif response['result'][0]['type'] == 'picture':
                summary = "Photo viewing"
            elif response['result'][0]['type'] == 'audio':
                summary = "Audio playing"

            payload = [{ "jsonrpc": "2.0",
                         "method": "XBMC.GetInfoLabels",
                         "params": {"labels": STATUS_LABELS},
                         "id": "4st" }]
            if len(STATUS_BOOLEANS):
                payload += [{ "jsonrpc": "2.0",
                              "method": "XBMC.GetInfoBooleans",
                              "params": {"booleans": STATUS_BOOLEANS},
                              "id": "4sti" }]

            status_resp = requests.post(
                rpc_url,
                data=json.dumps(payload),
                headers=headers).json()

            # Add the summary string above to the response dictionary.
            # The try/except is in case Kodi communication gets
            # disrupted while showing the status screen!
            try:
                status_dict = status_resp[0]['result']
                if len(STATUS_BOOLEANS):
                    status_dict.update(status_resp[1]['result'])

                status_dict['summary'] = summary
            except:
                pass

            status_screen(image, draw, status_dict)
            screen_on()
        else:
            screen_off()

    elif (response['result'][0]['type'] == 'video' and VIDEO_ENABLED):
        # Video is playing
        _kodi_playing = True

        # Change display modes upon any screen press, forcing a
        # re-fetch of any artwork.  Clear other state that may also be
        # mode-specific.
        if _screen_press.is_set() or touched:
            _screen_press.clear()
            if not VIDEO_LAYOUT_AUTOSELECT:
                video_dmode = video_dmode.next()
                print(datetime.now(), "video display mode now", video_dmode.name)
                _last_image_time = None
                _last_thumb = None
                _static_image = None
                truncate_line.cache_clear()
                text_wrap.cache_clear()

        # Retrieve InfoLabels and InfoBooleans in a single RPC call
        payload = [{ "jsonrpc": "2.0",
                     "method": "XBMC.GetInfoLabels",
                     "params": {"labels": VIDEO_LABELS},
                     "id": "4v" }]
        if len(VIDEO_BOOLEANS):
            payload += [{ "jsonrpc": "2.0",
                          "method": "XBMC.GetInfoBooleans",
                          "params": {"booleans": VIDEO_BOOLEANS},
                          "id": "4vi" }]

        response = requests.post(
            rpc_url,
            data=json.dumps(payload),
            headers=headers).json()
        # print("Response: ", json.dumps(response))
        try:
            video_info = response[0]['result']
            if len(VIDEO_BOOLEANS):
                video_info.update(response[1]['result'])

            # There seems to be a hiccup in DLNA/UPnP playback in which a
            # change (or stopping playback) causes a moment when
            # nothing is actually playing, according to the Info Labels.
            if ((video_info["VideoPlayer.Time"] == "00:00" or
                 video_info["VideoPlayer.Time"] == "00:00:00") and
                video_info["VideoPlayer.Duration"] == "" and
                video_info["VideoPlayer.Cover"] == ""):
                pass
            else:
                video_screens(image, draw, video_info)
                screen_on()
        except BaseException:
            raise

    elif (response['result'][0]['type'] == 'audio' and AUDIO_ENABLED):
        # Audio is playing!
        _kodi_playing = True

        # Change display modes upon any screen press, forcing a
        # re-fetch of any artwork.  Clear other state that may also be
        # mode-specific.
        if _screen_press.is_set() or touched:
            _screen_press.clear()
            if not AUDIO_LAYOUT_AUTOSELECT:
                audio_dmode = audio_dmode.next()
                print(datetime.now(), "audio display mode now", audio_dmode.name)
                _last_image_time = None
                _last_thumb = None
                _static_image = None
                truncate_line.cache_clear()
                text_wrap.cache_clear()

        # Retrieve InfoLabels and InfoBooleans in a single RPC call
        payload = [{ "jsonrpc": "2.0",
                     "method": "XBMC.GetInfoLabels",
                     "params": {"labels": AUDIO_LABELS},
                     "id": "4a" }]
        if len(AUDIO_BOOLEANS):
            payload += [{ "jsonrpc": "2.0",
                          "method": "XBMC.GetInfoBooleans",
                          "params": {"booleans": AUDIO_BOOLEANS},
                          "id": "4ai" }]

        response = requests.post(
            rpc_url,
            data=json.dumps(payload),
            headers=headers).json()
        # print("Response: ", json.dumps(response))
        try:
            track_info = response[0]['result']
            if len(AUDIO_BOOLEANS):
                track_info.update(response[1]['result'])

            if ((# There seems to be a hiccup in DLNA/UPnP playback in
                # which a track change (or stopping playback) causes a
                # moment when nothing is actually playing, according to
                # the Info Labels.
                (track_info["MusicPlayer.Time"] == "00:00" or
                 track_info["MusicPlayer.Time"] == "00:00:00") and
                track_info["MusicPlayer.Duration"] == "" and
                track_info["MusicPlayer.Cover"] == "") or
                (# AirPlay starts out with only semi-accurate information
                track_info["Player.Filenameandpath"].startswith("pipe://") and
                (track_info["MusicPlayer.Title"] == "AirPlay" or
                 track_info["MusicPlayer.Title"] == ""))):
                pass
            else:
                audio_screens(image, draw, track_info)
                screen_on()
        except BaseException:
            raise

    elif (response['result'][0]['type'] == 'picture' and SLIDESHOW_ENABLED):
        # Photo slideshow is in-progress!
        _kodi_playing = True

        # Change display modes upon any screen press, forcing a
        # re-fetch of any artwork.  Clear other state that may also be
        # mode-specific.
        if _screen_press.is_set() or touched:
            _screen_press.clear()
            if not SLIDESHOW_LAYOUT_AUTOSELECT:
                slide_dmode = slide_dmode.next()
                print(datetime.now(), "slideshow display mode now", slide_dmode.name)
                _last_image_time = None
                _last_thumb = None
                _static_image = None
                truncate_line.cache_clear()
                text_wrap.cache_clear()

        # Retrieve InfoLabels and InfoBooleans in a single RPC call
        payload = [{ "jsonrpc": "2.0",
                     "method": "XBMC.GetInfoLabels",
                     "params": {"labels": SLIDESHOW_LABELS},
                     "id": "4s" }]
        if len(SLIDESHOW_BOOLEANS):
            payload += [{ "jsonrpc": "2.0",
                          "method": "XBMC.GetInfoBooleans",
                          "params": {"booleans": SLIDESHOW_BOOLEANS},
                          "id": "4si" }]

        response = requests.post(
            rpc_url,
            data=json.dumps(payload),
            headers=headers).json()
        # print("Response: ", json.dumps(response))
        try:
            slide_info = response[0]['result']
            if len(SLIDESHOW_BOOLEANS):
                slide_info.update(response[1]['result'])

            slideshow_screens(image, draw, slide_info)
            screen_on()

        except BaseException:
            raise

    # Output to OLED/LCD display or framebuffer
    device.display(image)
    _lock.release()


# Interrupt callback target from RPi.GPIO for T_IRQ
#
#   Interesting threads on the RPi Forums:
#
#   Characterizing GPIO input pins (Jan 2016)
#   https://www.raspberrypi.org/forums/viewtopic.php?f=29&t=133740
#
#   GPIO callbacks occurring twice (Apr 2016)
#   https://www.raspberrypi.org/forums/viewtopic.php?t=143478
#
def touch_callback(channel):
    global _screen_press, _kodi_connected
    print(datetime.now(), "Touchscreen pressed")
    if _kodi_connected:
        if TOUCH_CALL_UPDATE:
            update_display(touched=True)
        else:
            if _kodi_connected:
                _screen_press.set()
    return


# Principle entry point for kodi_panel
#
# Set up touch interrupt, establish (and maintain) communication with
# Kodi, then loop forever invoking update_display().
#
def main(device_handle):
    global device
    global _kodi_connected, _kodi_playing
    global _screen_press
    _kodi_connected = False
    _kodi_playing = False

    device = device_handle

    print(datetime.now(), "Starting")
    # turn down verbosity from http connections
    logging.basicConfig()
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    # setup T_IRQ as a GPIO interrupt, if enabled
    if (USE_TOUCH and not DEMO_MODE):
        print(datetime.now(), "Setting up touchscreen interrupt")
        GPIO.setmode(GPIO.BCM)
        if (TOUCH_PULLUP):
            GPIO.setup(TOUCH_INT, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        else:
            GPIO.setup(TOUCH_INT, GPIO.IN)
        GPIO.add_event_detect(TOUCH_INT, edge=GPIO.FALLING,
                              callback=touch_callback, bouncetime=TOUCH_DEBOUNCE)

    # main communication loop
    while True:
        screen_on()
        draw.rectangle(
            [(0, 0), (_frame_size[0], _frame_size[1])], 'black', 'black')
        draw.text((5, 5), "Waiting to connect with Kodi...",
                  fill='white', font=_fonts["font_main"])
        device.display(image)

        while True:
            # ensure Kodi is up and accessible
            payload = {
                "jsonrpc": "2.0",
                "method": "JSONRPC.Ping",
                "id": 2,
            }

            try:
                print(datetime.now(), "Trying ping...")
                response = requests.post(
                    rpc_url, data=json.dumps(payload), headers=headers,
                    timeout=5).json()
                if response['result'] != 'pong':
                    print(datetime.now(), "Kodi not available via HTTP-transported JSON-RPC.  Waiting...")
                    time.sleep(2)
                else:
                    break
            except (ConnectionRefusedError,
                    requests.exceptions.ConnectionError):
                if _lock.locked():
                    _lock.release()
                time.sleep(5)
                continue
            except BaseException:
                print(datetime.now(), "Unexpected error: ", sys.exc_info()[0])
                track = traceback.format_exc()
                print(track)
                time.sleep(5)
                continue

        print(datetime.now(), "Connected with Kodi.  Entering update_display() loop.")
        screen_off()

        # Loop until Kodi goes away
        _kodi_connected = True
        _screen_press.clear()
        while True:
            start_time = time.time()
            if DEMO_MODE:
                keys = device._pygame.key.get_pressed()
                if keys[device._pygame.K_SPACE]:
                    _screen_press.set()
                    print(datetime.now(), "Touchscreen pressed (emulated)")

            if _screen_press.is_set():
                print(datetime.now(), "Top-of-loop, screen was pressed")

            try:
                update_display()
            except (ConnectionRefusedError,
                    requests.exceptions.ConnectionError):
                print(datetime.now(), "Communication disrupted!")
                _kodi_connected = False
                _kodi_playing = False
                _screen_press.clear()
                if _lock.locked():  _lock.release()
                break
            except (SystemExit, KeyboardInterrupt):
                shutdown()
            except:
                print(datetime.now(), "Unexpected error: ", sys.exc_info()[0])
                track = traceback.format_exc()
                print(track)
                # Releasing the lock isn't necessary if we're exiting,
                # but it is useful to have in place should this
                # exception handling be modified.  Forgetting about
                # the lock can too easily just lead to a hang.
                if _lock.locked():  _lock.release()
                sys.exit(1)

            # If connecting to Kodi over an actual network connection,
            # update times can vary.  Rather than sleeping for a fixed
            # duration, we might as well measure how long the update
            # takes and then sleep whatever remains of that second.

            elapsed = time.time() - start_time
            if elapsed < 0.985:
                _screen_press.wait(0.985 - elapsed)
            else:
                _screen_press.wait(1.0)


def shutdown():
    if (USE_TOUCH and not DEMO_MODE):
        print(datetime.now(), "Removing touchscreen interrupt")
        GPIO.remove_event_detect(TOUCH_INT)
        GPIO.cleanup()
    print(datetime.now(), "Stopping")
    exit(0)
