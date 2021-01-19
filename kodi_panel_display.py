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
import time
import logging
import requests
import json
import io
import re
import os
import threading
import warnings

# kodi_panel settings
import config

PANEL_VER = "v1.22dev"

#
# Audio/Video codec lookup table
#
#   Should any collision in codec names occur, this table may have to
#   be split for distinct audio and video codecs.  Until then, though,
#   we can use it for both.
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

# Status screen information
STATUS_LABELS = [
    "System.Uptime",
    "System.CPUTemperature",
    "System.CpuFrequency",
    "System.Date",
    "System.Time",
    "System.BuildVersion",
    "System.BuildDate",
    "System.FreeSpace",
]

# Audio screen information
AUDIO_LABELS = [
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
_last_image_path = None
_last_thumb = None
_last_image_time = None   # used with airtunes / airplay coverart

# Re-use static portion of a screen.  The various _last_* variables
# below are checked to determine when the static portion can be
# reused.
_static_image = None
_static_video = False  # set True by video_screens(), False by audio_screens()

_last_track_num = None
_last_track_title = None
_last_track_album = None
_last_track_time = None
_last_video_title = None
_last_video_time = None
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


#
# Which display screens are enabled for use?
#
AUDIO_ENABLED = config.settings.get("ENABLE_AUDIO_SCREENS", False)
VIDEO_ENABLED = config.settings.get("ENABLE_VIDEO_SCREENS", False)


# Audio screen enumeration
# ------------------------
# The next() function serves to switch modes in response to screen
# touches.  The list is intended to grow, as other ideas for layouts
# are proposed.
#

class ADisplay(Enum):
    def next(self):
        cls = self.__class__
        members = list(cls)
        index = members.index(self) + 1
        if index >= len(members):
            index = 0
        return members[index]


# Populate enum based upon settings file
if AUDIO_ENABLED:
    if ("ALAYOUT_NAMES" in config.settings.keys() and
            "ALAYOUT_INITIAL" in config.settings.keys()):
        for index, value in enumerate(config.settings["ALAYOUT_NAMES"]):
            extend_enum(ADisplay, value, index)

        # At startup, use the default layout mode specified in settings
        audio_dmode = ADisplay[config.settings["ALAYOUT_INITIAL"]]
    else:
        warnings.warn(
            "Cannot find settings for ALAYOUT_NAMES and/or ALAYOUT_INITIAL!")
        print("Disabling audio screens (AUDIO_ENABLED=0)")
        AUDIO_ENABLED = 0


# Video screen enumeration
# ------------------------
# Same functionality as ADisplay above.
#

class VDisplay(Enum):
    def next(self):
        cls = self.__class__
        members = list(cls)
        index = members.index(self) + 1
        if index >= len(members):
            index = 0
        return members[index]


if VIDEO_ENABLED:
    if ("VLAYOUT_NAMES" in config.settings.keys() and
            "VLAYOUT_INITIAL" in config.settings.keys()):
        # Populate enum based upon settings file
        for index, value in enumerate(config.settings["VLAYOUT_NAMES"]):
            extend_enum(VDisplay, value, index)

        # At startup, use the default layout mode specified in settings
        video_dmode = VDisplay[config.settings["VLAYOUT_INITIAL"]]

        # Should video layout be auto-determined as part of video_screens()
        # execution, based upon InfoLabel settings?
        #
        # This is different behavior than using the touch-interrupt to
        # just cycle through the list of video modes, but seems warranted
        # based on the differences that exist for Movies, TV, and PVR.
        VIDEO_LAYOUT_AUTOSELECT = config.settings.get(
            "VLAYOUT_AUTOSELECT", False)

    else:
        warnings.warn(
            "Cannot find settings for VLAYOUT_NAMES and/or VLAYOUT_INITIAL!")
        print("Disabling video screens (VIDEO_ENABLED=0)")
        VIDEO_ENABLED = 0


# Screen Mode
# -----------
#        
# Define an enumerated type (well, it's still Python, so a class)
# representing whether the screen being drawn is for audio playback,
# video playback, or is just a status screen.

class ScreenMode(Enum):
    STATUS = 0   # kodi_panel status screen
    AUDIO  = 1   # audio playback is active
    VIDEO  = 2   # video playback is active
        

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
                 key == "fill" or key == "lfill") and
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


# Used by audio_screens() for all info screens
if (AUDIO_ENABLED and "A_LAYOUT" in config.settings.keys()):
    AUDIO_LAYOUT = fixup_layouts(config.settings["A_LAYOUT"])
elif AUDIO_ENABLED:
    warnings.warn(
        "Cannot find any A_LAYOUT screen settings!  Disabling audio screens.")
    AUDIO_ENABLED = 0

# Used by video_screens() for all info screens
if (VIDEO_ENABLED and "V_LAYOUT" in config.settings.keys()):
    VIDEO_LAYOUT = fixup_layouts(config.settings["V_LAYOUT"])
elif VIDEO_ENABLED:
    warnings.warn(
        "Cannot find any V_LAYOUT screen settings!  Disabling video screens.")
    VIDEO_ENABLED = 0

# Layout control for status screen, used by status_screen()
if ("STATUS_LAYOUT" in config.settings.keys()):
    STATUS_LAYOUT = fixup_layouts(config.settings["STATUS_LAYOUT"])
else:
    warnings.warn("Cannot find any STATUS_LAYOUT screen settings!  Exiting.")
    sys.exit(1)


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
TOUCH_PULLUP = config.settings.get("TOUCH_PULLUP", False)
TOUCH_DEBOUNCE = config.settings.get("TOUCH_DEBOUNCE", 700)  # milliseconds

# Should the touch_callback() ISR attempt to invoke update_display()
# directly?  Having the ISR take too long to execute is problematic on
# the RPi Zero.
TOUCH_CALL_UPDATE = config.settings.get("TOUCH_CALL_UPDATE", False)

# Internal state variables used to manage screen presses
_kodi_connected = False
_kodi_playing = False
_screen_press = False
_screen_active = False

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
image = Image.new('RGB', (_frame_size), 'black')
draw = ImageDraw.Draw(image)


# ----------------------------------------------------------------------------


# Element callback functions
# --------------------------
#
# These callbacks take the place of the earlier "special treatment" of
# textfields.
#
# Each function listed in the ELEMENT_CB dictionary must accept the
# following 6 arguments:
#
#   image        Image object instance for Pillow
#
#   draw         ImageDraw object instance, tied to image
#
#   info         dictionary containing InfoLabels from JSON-RPC response,
#                possibly augmented by calling function
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
# interpolation feature.
#
# For purely text display, the calling function is responsible for
# rendering the returned string.  This callback ONLY needs to perform
# the desired string manipulation.  If the callback function does take
# it upon itself to modify the passed Image or ImageDraw objects
# directly, then it should return an empty string.
#
# After the function definitions, see remarks ahead of the callback
# dictionary.


# Empty callback function, largely for testing    
def element_empty(image, draw, info, field, screen_mode, layout_name):
    return ""


# Perform a table lookup to convert Kodi's codec names into more
# common names.

def element_codec(image, draw, info, field, screen_mode, layout_name):
    if 'MusicPlayer.Codec' in info:
        if info['MusicPlayer.Codec'] in codec_name:
            return codec_name[info['MusicPlayer.Codec']]
        else:
            return info['MusicPlayer.Codec']
    else:
        return ""


# Similar function for AudioCodec lookup when playing video

def element_acodec(image, draw, info, field, screen_mode, layout_name):
    if 'VideoPlayer.AudioCodec' in info:
        if info['VideoPlayer.AudioCodec'] in codec_name.keys():
            return codec_name[info['VideoPlayer.AudioCodec']]
        else:
            return info['VideoPlayer.AudioCodec']        
    else:
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

def element_full_codec(image, draw, info, field, screen_mode, layout_name):
    if (screen_mode == ScreenMode.AUDIO and
        'MusicPlayer.Codec' in info):

        if info['MusicPlayer.Codec'] in codec_name:
            display_text = codec_name[info['MusicPlayer.Codec']]
        else:
            display_text = info['MusicPlayer.Codec']

        # augment with (bit/sample) information
        display_text += " (" + info['MusicPlayer.BitsPerSample'] + "/" + \
            info['MusicPlayer.SampleRate'] + ")"
            
    else:
        return ""


# Process an audio file's listed Artist, instead displaying the
# Composer parenthetically if the artist field is empty.
#
# This particular special treatment never worked out as intended.  The
# combination of JRiver Media Center providing DLNA/UPnp playback to
# Kodi doesn't successfully yield any composer info.  I believe that
# Kodi's UPnP field parsing is incomplete.

def element_audio_artist(image, draw, info, field, screen_mode, layout_name):
    if screen_mode == ScreenMode.AUDIO:
        if field.get("format_str", ""):
            display_string = format_InfoLabels(field["format_str"], info)
        else:
            # The following was an attempt to display Composer if
            # Artist is blank.  The combination of JRiver Media Center
            # and UPnP/DLNA playback via Kodi didn't quite permit this
            # to work, unfortunately.
            
            if info['MusicPlayer.Artist'] != "":
                display_string = (field.get("prefix", "") + info['MusicPlayer.Artist'] +
                                  field.get("suffix", ""))
            elif info['MusicPlayer.Property(Role.Composer)'] != "":
                display_string = (field.get("prefix", "") +
                                  "(" + info['MusicPlayer.Property(Role.Composer)'] + ")" +
                                  field.get("suffix", ""))
                
            if (display_string == "Unknown" and field.get("drop_unknown", 0)):
                display_string = ""

            return display_string
    else:
        return ""



# Return string with current kodi_panel version    
def element_version(image, draw, info, field, screen_mode, layout_name):
    return "kodi_panel " + PANEL_VER


# Return a friendlier version of Kodi build information
def element_kodi_version(image, draw, info, field, screen_mode, layout_name):
    if ("System.BuildVersion" in info and
        "System.BuildDate" in info):
        kodi_version = info["System.BuildVersion"].split()[0]
        build_date   = info["System.BuildDate"]
        return "Kodi version: " + kodi_version + " (" + build_date + ")"
    else:
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
        

# Dictionary of element callback functions, with each key
# corresponding to either the "name" specified for a textfield (within
# a layout's array of such textfields).
#
# FIXME: Extend to top-level elements (thumb, prog) within a layout??
#
# Scripts that are making use of kodi_panel_display can change the
# function assigned to the entries below and add entirely new
# key/value pairs.
    
ELEMENT_CB = {
    'codec'      : element_codec,
    'acodec'     : element_acodec,
    'full_codec' : element_full_codec,
    'artist'     : element_audio_artist,

    # Status screen fields
    'version'      : element_version,
    'kodi_version' : element_kodi_version,
    'time_hrmin'   : element_time_hrmin,
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
    line_height = font.getsize('Ahg')[1]
    (posx, posy) = xy
    for line in line_array:
        pil_draw.text((posx, posy), line, fill, font)
        posy = posy + line_height
    return


# Draw a horizontal (by default) progress bar at the specified
# location, filling from left to right.  A vertical bar can be drawn
# if specified, filling from bottom to top.
def progress_bar(pil_draw, bgcolor, color, x, y,
                 w, h, progress, vertical=False):
    pil_draw.rectangle((x, y, x + w, y + h), fill=bgcolor)

    if progress <= 0:
        progress = 0.01
    if progress > 1:
        progress = 1

    if vertical:
        dh = h * progress
        pil_draw.rectangle((x, y + h - dh, x + w, y + h), fill=color)
    else:
        dw = w * progress
        pil_draw.rectangle((x, y, x + dw, y + h), fill=color)


# Retrieve cover art or a default thumbnail.  Cover art gets resized
# to the provided thumb_width and thumb_height.  (This now applies
# to default images as well.)
#
# Note that details of retrieval seem to differ depending upon whether
# Kodi is playing from its library, from UPnp/DLNA, or from Airplay.
#
# The global _last_image_path is intended to let any given image file
# be fetched and resized just *once*.  Subsequent calls just reuse the
# same data, provided that the caller preserves and passes in
# prev_image.
#
def get_artwork(cover_path, prev_image, thumb_width, thumb_height, video=0):
    global _last_image_path, _last_image_time
    image_url = None
    image_set = False
    resize_needed = False

    cover = None   # retrieved artwork, original size

    if (cover_path != '' and
        cover_path != 'DefaultVideoCover.png' and
        cover_path != 'DefaultAlbumCover.png' and
            not _airtunes_re.match(cover_path)):

        image_path = cover_path
        # print("image_path : ", image_path) # debug info

        if (image_path == _last_image_path and prev_image):
            # Fall through and just return prev_image
            image_set = True
        else:
            _last_image_path = image_path
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
                # print("Response: ", json.dumps(response))  # debug info

                try:
                    image_url = base_url + "/" + \
                        response['result']['details']['path']
                    # print("image_url : ", image_url) # debug info
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
                    cover = Image.open(_default_audio_thumb)
                    prev_image = cover
                    image_set = True
                    resize_needed = True

    # Airplay artwork
    #
    # If artwork is NOT local, then we'll have to retrieve it over the
    # network. Airplay coverart is always stored to the same file.
    # So, we start by getting the last modification time to figure out
    # if we need to retrieve it.
    #
    if (not image_set and
        _airtunes_re.match(cover_path) and
            not _local_kodi):

        image_path = cover_path
        # print("image_path : ", image_path) # debug info
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
        # print("Airplay image details: ", json.dumps(response))  # debug info
        new_image_time = None
        try:
            new_image_time = response['result']['filedetails']['lastmodified']
        except BaseException:
            pass
        # print("new_image_time", new_image_time)  # debug info
        if (new_image_time and new_image_time != _last_image_time):
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
            # print("Response: ", json.dumps(response))  # debug info

            try:
                image_url = base_url + "/" + \
                    response['result']['details']['path']
                # print("image_url : ", image_url) # debug info
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
                except BaseException:
                    cover = Image.open(_default_audio_thumb)
                    prev_image = cover
                    image_set = True
                    resize_needed = True
        else:
            image_set = True

    # Finally, if we still don't have anything, check if we are local
    # to Kodi and Airplay artwork can just be opened.  Otherwise, use
    # default images.
    if not image_set:
        resize_needed = True
        if _airtunes_re.match(cover_path):
            airplay_thumb = "/storage/.kodi/temp/" + \
                _airtunes_re.match(cover_path).group(1)
            if os.path.isfile(airplay_thumb):
                _last_image_path = airplay_thumb
                resize_needed = True
            else:
                _last_image_path = _default_airplay_thumb
        else:
            # use default image when no artwork is available
            if video:
                _last_image_path = _default_video_thumb
            else:
                _last_image_path = _default_audio_thumb

        cover = Image.open(_last_image_path)
        prev_image = cover
        image_set = True

    # is resizing needed?
    if (image_set and resize_needed):
        # resize while maintaining aspect ratio, which should
        # be precisely what thumbnail accomplishes
        cover.thumbnail((thumb_width, thumb_height))
        prev_image = cover

    if image_set:
        return prev_image
    else:
        return None


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

_InfoLabel_re = re.compile(r'\{(\w*\.\w*)\}')

def format_InfoLabels(orig_str, kodi_dict):
    matches = set(_InfoLabel_re.findall(orig_str))
    new_str = orig_str
    for field in matches:
        if field in kodi_dict.keys():
            new_str = new_str.replace('{' + field + '}', kodi_dict[field])
        else:
            new_str = new_str.replace('{' + field + '}', '')
    return new_str



# Render all text fields, stepping through the fields array from
# the layout dictionary that is passed in.
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
#  layout_name  Name, as a string, for the in-use layout
#  screen_mode  Enumerated type indicating AUDIO, VIDEO, or STATUS
#  dynamic      Boolean flag, set for dynamic screen updates
#  
#
def text_fields(image, draw, layout, info, layout_name, screen_mode, dynamic=False):

    # Text fields (all except for MusicPlayer.Time)
    txt_fields = layout.get("fields", [])
    for field_info in txt_fields:
        display_string = None
        
        # Skip over the fields that aren't desired for this
        # invocation, based on static vs dynamic
        if dynamic:
            if not field_info.get("dynamic", 0):
                continue
        else:
            if field_info.get("dynamic", 0):
                continue

        # Check for any defined callback functions.  If an entry
        # exists in the lookup table, invoke the specified function
        # with all of the arguments discussed in earlier comments.

        if field_info["name"] in ELEMENT_CB:
            display_string = ELEMENT_CB[field_info["name"]](
                image,             # Image instance
                draw,              # ImageDraw instance
                info,              # Kodo InfoLabel response
                field_info,        # layout details for field
                screen_mode,       # screen mode, as enum
                audio_dmode.name   # layout name, as string
            )
            # print("Invoked CB for ", field_info["name"],"; received back '", display_string, "'")
            
        else:
            if (field_info["name"] in info.keys() and
                info[field_info["name"]] != ""):

                # Use format_str or prefix/suffic approach, in that order
                if field_info.get("format_str", ""):
                    display_string = format_InfoLabels(
                        field_info["format_str"], info)
                else:
                    display_string = (field_info.get("prefix", "") +
                                      info[field_info["name"]] +
                                      field_info.get("suffix", ""))
                

        # if the string to display is empty, move on to the next field,
        # otherwise render it.
        if (not display_string or display_string == ""):
            continue

        # render any label first
        if "label" in field_info:
            draw.text((field_info["lposx"], field_info["lposy"]),
                      field_info["label"],
                      fill=field_info["lfill"], font=field_info["lfont"])

        if "wrap" in field_info.keys():
            render_text_wrap(draw,
                             (field_info["posx"], field_info["posy"]),
                             display_string,
                             max_width=field_info["max_width"],
                             max_lines=field_info["max_lines"],
                             fill=field_info["fill"],
                             font=field_info["font"])
        elif "trunc" in field_info.keys():
            render_text_wrap(draw,
                             (field_info["posx"], field_info["posy"]),
                             display_string,
                             max_width=_frame_size[0] -
                             field_info["posx"],
                             max_lines=1,
                             fill=field_info["fill"],
                             font=field_info["font"])
        else:
            draw.text((field_info["posx"], field_info["posy"]),
                      display_string,
                      fill=field_info["fill"],
                      font=field_info["font"])




# Idle status screen (shown upon a screen press)
#
# First argument is a Pillow ImageDraw object.
# Second argument is a dictionary loaded from Kodi system status fields.
# This argument is the string to use for current state of the system
#
def status_screen(image, draw, kodi_status, summary_string):
    layout = STATUS_LAYOUT

    # Kodi logo, if desired
    if "thumb" in layout.keys():
        kodi_icon = Image.open(_kodi_thumb)
        kodi_icon.thumbnail((layout["thumb"]["size"], layout["thumb"]["size"]))
        image.paste(
            kodi_icon,
            (layout["thumb"]["posx"],
             layout["thumb"]["posy"]))

    # go through all text fields, if any
    if "fields" not in layout.keys():
        return

    text_fields(image, draw,
                layout, kodi_status,
                "STATUS_LAYOUT", ScreenMode.STATUS)


            
# Render the static portion of audio screens
#
#  First argument is the layout dictionary to use
#  Second argument is a dictionary loaded from Kodi with relevant InfoLabels
#
def audio_screen_static(layout, info):
    global _last_thumb, _last_image_path

    # Create a new image
    image = Image.new('RGB', (_frame_size), 'black')
    draw = ImageDraw.Draw(image)

    # retrieve cover image from Kodi, if it exists and needs a refresh
    if "thumb" in layout.keys():
        _last_thumb = get_artwork(info['MusicPlayer.Cover'], _last_thumb,
                                  layout["thumb"]["size"], layout["thumb"]["size"])
        if _last_thumb:
            if layout["thumb"].get("center", 0):
                image.paste(_last_thumb,
                            (int((_frame_size[0] - _last_thumb.width) / 2),
                             int((_frame_size[1] - _last_thumb.height) / 2)))
            elif (layout["thumb"].get("center_sm", 0) and
                  (_last_thumb.width < layout["thumb"]["size"] or
                   _last_thumb.height < layout["thumb"]["size"])):
                new_x = layout["thumb"]["posx"]
                new_y = layout["thumb"]["posy"]
                if _last_thumb.width < layout["thumb"]["size"]:
                    new_x += int((layout["thumb"]["size"] /
                                  2) - (_last_thumb.width / 2))
                if _last_thumb.height < layout["thumb"]["size"]:
                    new_y += int((layout["thumb"]["size"] /
                                  2) - (_last_thumb.height / 2))
                image.paste(_last_thumb, (new_x, new_y))
            else:
                image.paste(
                    _last_thumb,
                    (layout["thumb"]["posx"],
                     layout["thumb"]["posy"]))
    else:
        _last_thumb = None

    # All static text fields
    text_fields(image, draw,
                layout, info,
                audio_dmode.name, ScreenMode.AUDIO,
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

    # All dynamic text fields
    text_fields(image, draw,
                layout, info,
                audio_dmode.name, ScreenMode.AUDIO,
                dynamic=1)    

    # Progress bar, if present
    if (prog != -1 and "prog" in layout.keys()):
        if "vertical" in layout["prog"].keys():
            progress_bar(draw, layout["prog"]["color_bg"], layout["prog"]["color_fg"],
                         layout["prog"]["posx"], layout["prog"]["posy"],
                         layout["prog"]["len"],
                         layout["prog"]["height"],
                         prog, vertical=True)
        elif info['MusicPlayer.Time'].count(":") == 2:
            # longer bar for longer displayed time
            progress_bar(draw, layout["prog"]["color_bg"], layout["prog"]["color_fg"],
                         layout["prog"]["posx"], layout["prog"]["posy"],
                         layout["prog"]["long_len"], layout["prog"]["height"],
                         prog)
        else:
            progress_bar(draw, layout["prog"]["color_bg"], layout["prog"]["color_fg"],
                         layout["prog"]["posx"], layout["prog"]["posy"],
                         layout["prog"]["short_len"], layout["prog"]["height"],
                         prog)


# Audio info screens (shown when music is playing)
#
#  First two arguments are Pillow Image and ImageDraw objects.  Third
#  argument is a dictionary loaded from Kodi with relevant info
#  fields.  Fourth argument is a float representing progress through
#  the track.
#
#  The rendering is divided into two phases -- first all of the static
#  elements (on a new image) and then the dynamic text fields and
#  progress bar.  The static image gets reused when possible.
#
#  Switching to this approach seems to keep the active update loop to
#
#   - around 20% CPU load for an RPi Zero W and
#   - around 5% CPU load on an RPi 4.
#
def audio_screens(image, draw, info, prog):
    global _static_image, _static_video
    global _last_track_num, _last_track_title, _last_track_album, _last_track_time

    # Determine what audio layout should be used
    layout = AUDIO_LAYOUT[audio_dmode.name]

    if (_static_image and (not _static_video) and
        info["MusicPlayer.TrackNumber"] == _last_track_num and
        info["MusicPlayer.Title"] == _last_track_title and
        info["MusicPlayer.Album"] == _last_track_album and
            info["MusicPlayer.Duration"] == _last_track_time):
        pass
    else:
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
    global _last_thumb, _last_image_path

    # Create a new image
    image = Image.new('RGB', (_frame_size), 'black')
    draw = ImageDraw.Draw(image)

    # Retrieve cover image from Kodi, if it exists and needs a refresh
    if "thumb" in layout.keys():
        _last_thumb = get_artwork(info['VideoPlayer.Cover'], _last_thumb,
                                  layout["thumb"]["width"], layout["thumb"]["height"],
                                  video=1)
        if _last_thumb:
            if layout["thumb"].get("center", 0):
                image.paste(_last_thumb,
                            (int((_frame_size[0] - _last_thumb.width) / 2),
                             int((_frame_size[1] - _last_thumb.height) / 2)))
            elif (layout["thumb"].get("center_sm", 0) and
                  (_last_thumb.width < layout["thumb"]["width"] or
                   _last_thumb.height < layout["thumb"]["height"])):
                new_x = layout["thumb"]["posx"]
                new_y = layout["thumb"]["posy"]
                if _last_thumb.width < layout["thumb"]["width"]:
                    new_x += int((layout["thumb"]["width"] / 2) -
                                 (_last_thumb.width / 2))
                if _last_thumb.height < layout["thumb"]["height"]:
                    new_y += int((layout["thumb"]["height"] / 2) -
                                 (_last_thumb.height / 2))
                image.paste(_last_thumb, (new_x, new_y))
            else:
                image.paste(
                    _last_thumb,
                    (layout["thumb"]["posx"],
                     layout["thumb"]["posy"]))
    else:
        _last_thumb = None

    # All static text fields
    text_fields(image, draw,
                layout, info,
                video_dmode.name, ScreenMode.VIDEO,
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

    # All Dynamic text fields
    text_fields(image, draw,
                layout, info,
                video_dmode.name, ScreenMode.VIDEO,
                dynamic=1)

    # Progress bar, if present
    if (prog != -1 and "prog" in layout.keys()):
        if "vertical" in layout["prog"].keys():
            progress_bar(draw, layout["prog"]["color_bg"], layout["prog"]["color_fg"],
                         layout["prog"]["posx"], layout["prog"]["posy"],
                         layout["prog"]["len"],
                         layout["prog"]["height"],
                         prog, vertical=True)
        elif info['VideoPlayer.Time'].count(":") == 2:
            # longer bar for longer displayed time
            progress_bar(draw, layout["prog"]["color_bg"], layout["prog"]["color_fg"],
                         layout["prog"]["posx"], layout["prog"]["posy"],
                         layout["prog"]["long_len"], layout["prog"]["height"],
                         prog)
        else:
            progress_bar(draw, layout["prog"]["color_bg"], layout["prog"]["color_fg"],
                         layout["prog"]["posx"], layout["prog"]["posy"],
                         layout["prog"]["short_len"], layout["prog"]["height"],
                         prog)


# Video info screens (shown when a video is playing)
#
#  First two arguments are Pillow Image and ImageDraw objects.
#  Third argument is a dictionary loaded from Kodi with relevant info fields.
#  Fourth argument is a float representing progress through the video.
#
#  See static/dynamic description given for audio_screens()
#
def video_screens(image, draw, info, prog):
    global _static_image, _static_video
    global _last_video_title, _last_video_episode, _last_video_time
    global video_dmode

    # Heuristic to determine layout based upon populated InfoLabels,
    # if enabled via settings.  Originally suggested by @noggin and
    # augmented by @nico1080 in CoreELEC Forum discussion.
    #
    # Entries within VIDEO_LAYOUT don't have to exist, as selection
    # will just fall-through based on the key checks below.
    #
    # The heuristic is currently as follows:
    #
    #   Check                                    Use layout
    #   -------------------------------------------------------
    #   1. playing a pvr://recordings file       V_PVR
    #   2. playing a pvr://channels file         V_LIVETV
    #   3. TVShowTitle label is non-empty        V_TV_SHOW
    #   4. OriginalTitle label is non-empty      V_MOVIE
    #   -------------------------------------------------------
    #

    if VIDEO_LAYOUT_AUTOSELECT:
        if (info["Player.Filenameandpath"].startswith("pvr://recordings") and
                "V_PVR" in VIDEO_LAYOUT):
            video_dmode = VDisplay["V_PVR"]     # PVR TV shows
        elif (info["Player.Filenameandpath"].startswith("pvr://channels") and
              "V_LIVETV" in VIDEO_LAYOUT):
            video_dmode = VDisplay["V_LIVETV"]  # live TV
        elif (info["VideoPlayer.TVShowTitle"] != '' and
              "V_TV_SHOW" in VIDEO_LAYOUT):
            video_dmode = VDisplay["V_TV_SHOW"] # library TV shows
        elif (info["VideoPlayer.OriginalTitle"] != '' and
              "V_MOVIE" in VIDEO_LAYOUT):
            video_dmode = VDisplay["V_MOVIE"]   # movie
        else:
            pass  # leave as-is, just use default selection

    # Look up video layout details
    layout = VIDEO_LAYOUT[video_dmode.name]
        
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


# Given current position ([h:]m:s) and duration, calculate
# percentage done as a float for progress bar display.
#
# A -1 return value causes the progress bar NOT to be rendered.
#
def calc_progress(time_str, duration_str):
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
    global _last_image_path, _last_thumb, _static_image
    global _screen_press, _screen_active, _screen_offtime
    global audio_dmode, video_dmode

    _lock.acquire()

    # Start with a blank slate, if there's no static image
    if (not (_kodi_connected and _static_image)):
        draw.rectangle(
            [(0, 0), (_frame_size[0], _frame_size[1])], 'black', 'black')

    # Check if the _screen_active time has expired
    if (_screen_active and datetime.now() >= _screen_offtime):
        _screen_active = False
        if not _kodi_playing:
            screen_off()

    # Ask Kodi whether anything is playing...
    #
    #   JSON-RPC calls can only invoke one method per call.  Unless
    #   we wish to make a "blind" InfoLabels call asking for all
    #   interesting MusicPlayer and VideoPlayer fields, we must
    #   make 2 distinct network calls.
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
        response['result'][0]['type'] == 'picture' or
        (response['result'][0]['type'] == 'video' and not VIDEO_ENABLED) or
            (response['result'][0]['type'] == 'audio' and not AUDIO_ENABLED)):
        # Nothing is playing or something for which no display screen
        # is available.
        _kodi_playing = False

        # Check for screen press before proceeding.  A press when idle
        # generates the status screen.
        _last_image_path = None
        _last_image_time = None
        _last_thumb = None
        _static_image = None

        if _screen_press or touched:
            _screen_press = False
            _screen_active = True
            _screen_offtime = datetime.now() + timedelta(seconds=_screen_wake)

        if _screen_active:
            # Idle status screen
            if len(response['result']) == 0:
                summary = "Idle"
            elif response['result'][0]['type'] == 'video':
                summary = "Video playing"
            elif response['result'][0]['type'] == 'picture':
                summary = "Photo viewing"

            payload = {
                "jsonrpc": "2.0",
                "method": "XBMC.GetInfoLabels",
                "params": {"labels": STATUS_LABELS},
                "id": "4s",
            }
            status_resp = requests.post(
                rpc_url,
                data=json.dumps(payload),
                headers=headers).json()

            # add the summary string above to the response dictionary
            status_resp['result']['summary'] = summary
            
            status_screen(image, draw, status_resp['result'], summary)
            screen_on()
        else:
            screen_off()

    elif (response['result'][0]['type'] == 'video' and VIDEO_ENABLED):
        # Video is playing
        _kodi_playing = True

        # Change display modes upon any screen press, forcing a
        # re-fetch of any artwork.  Clear other state that may also be
        # mode-specific.
        if _screen_press or touched:
            _screen_press = False
            if not VIDEO_LAYOUT_AUTOSELECT:
                video_dmode = video_dmode.next()
                print(
                    datetime.now(),
                    "video display mode now",
                    video_dmode.name)
                _last_image_path = None
                _last_image_time = None
                _last_thumb = None
                _static_image = None
                truncate_line.cache_clear()
                text_wrap.cache_clear()

        # Retrieve video InfoLabels in a single JSON-RPC call
        payload = {
            "jsonrpc": "2.0",
            "method": "XBMC.GetInfoLabels",
            "params": {"labels": VIDEO_LABELS},
            "id": "4v",
        }
        response = requests.post(
            rpc_url,
            data=json.dumps(payload),
            headers=headers).json()
        # print("Response: ", json.dumps(response))
        try:
            video_info = response['result']

            # See remarks in audio_screens() regarding calc_progress()
            prog = calc_progress(
                video_info["VideoPlayer.Time"],
                video_info["VideoPlayer.Duration"])

            # There seems to be a hiccup in DLNA/UPnP playback in which a
            # change (or stopping playback) causes a moment when
            # nothing is actually playing, according to the Info Labels.
            if ((video_info["VideoPlayer.Time"] == "00:00" or
                 video_info["VideoPlayer.Time"] == "00:00:00") and
                video_info["VideoPlayer.Duration"] == "" and
                video_info["VideoPlayer.Cover"] == ""):
                pass
            else:
                video_screens(image, draw, video_info, prog)
                screen_on()
        except BaseException:
            raise

    elif (response['result'][0]['type'] == 'audio' and AUDIO_ENABLED):
        # Audio is playing!
        _kodi_playing = True

        # Change display modes upon any screen press, forcing a
        # re-fetch of any artwork.  Clear other state that may also be
        # mode-specific.
        if _screen_press or touched:
            _screen_press = False
            audio_dmode = audio_dmode.next()
            print(datetime.now(), "audio display mode now", audio_dmode.name)
            _last_image_path = None
            _last_image_time = None
            _last_thumb = None
            _static_image = None
            truncate_line.cache_clear()
            text_wrap.cache_clear()

        # Retrieve all music InfoLabels in a single JSON-RPC call.
        #
        #   Unfortunately, Kodi Leia doesn't seem to capture the field
        #   that JRiver Media Center offers up for its "Composer" tag,
        #   namely
        #
        #      upnp:author role="Composer"
        #
        #   I've tried several variants with no success.
        #
        #   Also, BitsPerSample appears to be unreliable, as it can
        #   get "stuck" at 32.  The SampleRate behaves better.  None
        #   of these problems likely occur when playing back from a
        #   Kodi-local library.
        #
        payload = {
            "jsonrpc": "2.0",
            "method": "XBMC.GetInfoLabels",
            "params": {"labels": AUDIO_LABELS},
            "id": "4a",
        }
        response = requests.post(
            rpc_url,
            data=json.dumps(payload),
            headers=headers).json()
        # print("Response: ", json.dumps(response))
        try:
            track_info = response['result']

            # Progress information in Kodi Leia must be fetch separately, via a
            # JSON-RPC call like the following:
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
            # This looks to be fixed in Kodi Matrix.  However, since we
            # already have the current time and duration, let's just
            # calculate the current position as a percentage.

            prog = calc_progress(
                track_info["MusicPlayer.Time"],
                track_info["MusicPlayer.Duration"])

            # There seems to be a hiccup in DLNA/UPnP playback in
            # which a track change (or stopping playback) causes a
            # moment when nothing is actually playing, according to
            # the Info Labels.
            if ((track_info["MusicPlayer.Time"] == "00:00" or
                 track_info["MusicPlayer.Time"] == "00:00:00") and
                track_info["MusicPlayer.Duration"] == "" and
                    track_info["MusicPlayer.Cover"] == ""):
                pass
            else:
                audio_screens(image, draw, track_info, prog)
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
    # print(datetime.now(), "Touchscreen pressed")
    if _kodi_connected:
        if TOUCH_CALL_UPDATE:
            update_display(touched=True)
        else:
            _screen_press = _kodi_connected
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
                response = requests.post(
                    rpc_url, data=json.dumps(payload), headers=headers).json()
                if response['result'] != 'pong':
                    print(
                        datetime.now(),
                        "Kodi not available via HTTP-transported JSON-RPC.  Waiting...")
                    time.sleep(5)
                else:
                    break
            except BaseException:
                time.sleep(5)
                pass

        print(
            datetime.now(),
            "Connected with Kodi.  Entering update_display() loop.")
        screen_off()

        # Loop until Kodi goes away
        _kodi_connected = True
        _screen_press = False
        while True:
            try:
                start_time = time.time()
                if DEMO_MODE:
                    keys = device._pygame.key.get_pressed()
                    if keys[device._pygame.K_SPACE]:
                        _screen_press = True
                        print(datetime.now(), "Touchscreen pressed (emulated)")
                update_display()
            except (ConnectionRefusedError,
                    requests.exceptions.ConnectionError):
                print(datetime.now(), "Communication disrupted.")
                _kodi_connected = False
                _kodi_playing = False
                break
            except (SystemExit):
                shutdown()
            except BaseException:
                print("Unexpected error: ", sys.exc_info()[0])
                raise

            # If connecting to Kodi over an actual network connection,
            # update times can vary.  Rather than sleeping for a fixed
            # duration, we might as well measure how long the update
            # takes and then sleep whatever remains of that second.

            elapsed = time.time() - start_time
            if elapsed < 0.999:
                time.sleep(0.999 - elapsed)
            else:
                time.sleep(1.0)


def shutdown():
    if (USE_TOUCH and not DEMO_MODE):
        print(datetime.now(), "Removing touchscreen interrupt")
        GPIO.remove_event_detect(TOUCH_INT)
        GPIO.cleanup()
    print(datetime.now(), "Stopping")
    exit(0)
