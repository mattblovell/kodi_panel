#
# MIT License
#
# Copyright (c) 2020  Matthew Lovell
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

PANEL_VER = "v1.00"

# Audio/Video codec lookup
codec_name = {
    "ac3"      : "DD",
    "eac3"     : "DD",
    "dtshd_ma" : "DTS-MA",
    "dca"      : "DTS",
    "truehd"   : "DD-HD",
    "wmapro"   : "WMA",
    "mp3float" : "MP3",
    "flac"     : "FLAC",
    "alac"     : "ALAC",
    "vorbis"   : "OggV",
    "aac"      : "AAC",
    "pcm_s16be": "PCM",
    "mp2"      : "MP2",
    "pcm_u8"   : "PCM",
    "BXA"      : "AirPlay",    # used with AirPlay
    "dsd_lsbf_planar": "DSD",
}

# ----------------------------------------------------------------------------

#
# Start processing settings...
#
base_url = config.settings["BASE_URL"]
rpc_url  = base_url + "/jsonrpc"
headers  = {'content-type': 'application/json'}

_local_kodi = (base_url.startswith("http://localhost:") or
               base_url.startswith("https://localhost:"))

# Image handling
frame_size      = (config.settings["DISPLAY_WIDTH"], config.settings["DISPLAY_HEIGHT"])
_last_image_path = None
_last_thumb      = None
_last_image_time = None   # used with airtunes / airplay coverart

# Thumbnail defaults (these don't get resized)
kodi_thumb      = config.settings["KODI_THUMB"]
default_thumb   = config.settings["DEFAULT_AUDIO"]
default_airplay = config.settings["DEFAULT_AIRPLAY"]

# RegEx for recognizing AirPlay images (compiled once)
_airtunes_re = re.compile(r'^special:\/\/temp\/(airtunes_album_thumb\.(png|jpg))')

# Load all user-specified fonts
fonts = {}
for user_font in config.settings["fonts"]:
    try:
        if "encoding" in user_font.keys():
            fonts[user_font["name"]] = ImageFont.truetype(
                user_font["path"], user_font["size"], encoding=user_font["encoding"]
            )
        else:
            fonts[user_font["name"]] = ImageFont.truetype(
                user_font["path"], user_font["size"]
            )
    except OSError:
        print("Unable to load font ", user_font["name"], " with path '", user_font["path"], "'", sep='')
        sys.exit("Exiting")


# Color lookup table
colors = config.settings["COLORS"]

# Which display modes are enabled for use?
AUDIO_ENABLED = config.settings.get("ENABLE_AUDIO_SCREENS",0)
VIDEO_ENABLED = config.settings.get("ENABLE_VIDEO_SCREENS",0)


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
        warnings.warn("Cannot find settings for ALAYOUT_NAMES and/or ALAYOUT_INITIAL!")
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
    else:
        warnings.warn("Cannot find settings for VLAYOUT_NAMES and/or VLAYOUT_INITIAL!")
        print("Disabling video screens (VIDEO_ENABLED=0)")
        AUDIO_ENABLED = 0
        

# Screen layouts
# --------------------
#
# Fixup fonts and colors, so that further table lookups are not
# necessary at run-time.
#

def fixup_layouts(nested_dict):
    newdict = copy.deepcopy(nested_dict)
    for key, value in nested_dict.items():
        if type(value) is dict:
            newdict[key] = fixup_layouts(value)
        elif type(value) is list:
            newdict[key] = fixup_array(value)
        else:
            if ((key.startswith("color") or key == "lcolor" or
                 key == "fill" or key == "lfill") and
                value.startswith("color_")):
                # Lookup color
                newdict[key] = colors[value]
            elif (key == "font" or key == "lfont" or
                  key == "smfont"):
                # Lookup font
                newdict[key] = fonts[value]
    return newdict

def fixup_array(array):
    newarray = []
    for item in array:
        if type(item) is dict:
            newarray.append(fixup_layouts(item))
        else:
            newarray.append(item)
    return newarray

# Used by audio_screens() for all info screens
if (AUDIO_ENABLED and "A_LAYOUT" in config.settings.keys()):
    AUDIO_LAYOUT = fixup_layouts(config.settings["A_LAYOUT"])
else:
    warnings.warn("Cannot find any A_LAYOUT screen settings!  Disabling audio screens.")
    AUDIO_ENABLED = 0

# Used by video_screens() for all info screens
if (VIDEO_ENABLED and "V_LAYOUT" in config.settings.keys()):
    VIDEO_LAYOUT = fixup_layouts(config.settings["V_LAYOUT"])
else:
    warnings.warn("Cannot find any A_LAYOUT screen settings!  Disabling video screens.")    
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
USE_TOUCH      = config.settings["USE_TOUCH"]  # Set False to disable interrupt use
TOUCH_INT      = config.settings["TOUCH_INT"]

# Internal state variables used to manage screen presses
kodi_active    = False
screen_press   = False
screen_active  = False
screen_wake    = 25    # status screen waketime, in seconds
screen_offtime = datetime.now()

# Provide a lock to ensure update_display() is single-threaded.  (This
# is perhaps unnecessary given Python's GIL, but is certainly safe.)
lock = threading.Lock()

# Additional screen controls.  Note that RPi.GPIO's PWM control, even
# the Odroid variant, uses software (pthreads) to control the signal,
# which can result in flickering.  At present (Oct 2020), I cannot
# recommend it.
#
# I have not yet found a way to take advantage of the C4's hardware
# PWM simultaneous with using luma.lcd.
#
# The USE_BACKLIGHT boolean controls whether calls are made to
# luma.lcd at all to change backlight state.  Users with OLED displays
# should set it to False.
#
USE_BACKLIGHT = config.settings["USE_BACKLIGHT"]
USE_PWM       = False
PWM_FREQ      = 362      # frequency, presumably in Hz
PWM_LEVEL     = 75.0     # float value between 0 and 100

# Are we running using luma.lcd's pygame demo mode?
DEMO_MODE = False


# ----------------------------------------------------------------------------

# Finally, create the needed Pillow objects
image  = Image.new('RGB', (frame_size), 'black')
draw   = ImageDraw.Draw(image)


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
        new_result = {
            "str"        : line,
            "result"     : line,
            "truncating" : 0,
            "font"       : font
        }
        return line

    avg_char = len(new_text) / t_width
    num_chars = int( max_width / avg_char ) + 4
    new_text = new_text[0:num_chars]

    # Leave room for ellipsis
    avail_width = max_width - font.getsize("\u2026")[0] + 6

    # Now perform naive truncation.
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
            while i < len(words) and font.getsize(line + words[i])[0] <= max_width:
                line = line + words[i] + " "
                i += 1
            if not line:
                line = words[i]
                i += 1
            # when the line gets longer than the max width do not append the word,
            # add the line to the lines array
            lines.append(line)
            if max_lines and len(lines) >= max_lines-1:
                break

        if max_lines and len(lines) >= max_lines-1 and i < len(words):
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
def progress_bar(pil_draw, bgcolor, color, x, y, w, h, progress, vertical=False):
    pil_draw.rectangle((x,y, x+w, y+h),fill=bgcolor)

    if progress <= 0:
        progress = 0.01
    if progress >1:
        progress = 1

    if vertical:
        dh = h*progress
        pil_draw.rectangle((x,y+h-dh,x+w,y+h),fill=color)
    else:
        dw = w*progress
        pil_draw.rectangle((x,y, x+dw, y+h),fill=color)


# Retrieve cover art or a default thumbnail.  Cover art gets resized
# to the provided thumb_size, but any default images are used as-is.
#
# Note that details of retrieval seem to differ depending upon whether
# Kodi is playing from its library, from UPnp/DLNA, or from Airplay.
#
# The global _last_image_path is intended to let any given image file
# be fetched and resized just *once*.  Subsequent calls just reuse the
# same data, provided that the caller preserves and passes in
# prev_image.
#
# The info argument must be the result of an XBMC.GetInfoLabels
# JSON-RPC call to Kodi.
def get_artwork(cover_path, prev_image, thumb_width, thumb_height):
    global _last_image_path
    global _last_image_time
    image_set     = False
    resize_needed = False

    cover = None   # retrieved artwork, original size
    thumb = None   # resized artwork

    if (cover_path != '' and
        cover_path != 'DefaultAlbumCover.png' and
        not _airtunes_re.match(cover_path)):

        image_path = cover_path
        #print("image_path : ", image_path) # debug info

        if (image_path == _last_image_path and prev_image):
            # Fall through and just return prev_image
            image_set = True
        else:
            _last_image_path = image_path
            if image_path.startswith("http://"):
                image_url = image_path
            else:
                payload = {
                    "jsonrpc": "2.0",
                    "method"  : "Files.PrepareDownload",
                    "params"  : {"path": image_path},
                    "id"      : 5,
                }
                response = requests.post(rpc_url, data=json.dumps(payload), headers=headers).json()
                #print("Response: ", json.dumps(response))  # debug info

                if ('details' in response['result'].keys() and
                    'path' in response['result']['details'].keys()) :
                    image_url = base_url + "/" + response['result']['details']['path']
                    #print("image_url : ", image_url) # debug info

            r = requests.get(image_url, stream = True)
            # check that the retrieval was successful before proceeding
            if r.status_code == 200:
                try:
                    r.raw.decode_content = True
                    cover = Image.open(io.BytesIO(r.content))
                    image_set     = True
                    resize_needed = True
                except:
                    cover = Image.open(default_thumb)
                    prev_image = cover
                    image_set     = True
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
        #print("image_path : ", image_path) # debug info
        payload = {
            "jsonrpc": "2.0",
            "method"  : "Files.GetFileDetails",
            "params"  : {"file": image_path,
                         "properties" : ["lastmodified"]
                         },
            "id"      : "5b",
        }
        response = requests.post(rpc_url, data=json.dumps(payload), headers=headers).json()
        #print("Airplay image details: ", json.dumps(response))  # debug info
        new_image_time = None
        try:
            new_image_time = response['result']['filedetails']['lastmodified']
        except:
            pass
        # print("new_image_time", new_image_time)  # debug info
        if (new_image_time and new_image_time != _last_image_time):
            payload = {
                "jsonrpc": "2.0",
                "method"  : "Files.PrepareDownload",
                "params"  : {"path": image_path},
                "id"      : "5c",
            }
            response = requests.post(rpc_url, data=json.dumps(payload), headers=headers).json()
            #print("Response: ", json.dumps(response))  # debug info

            if ('details' in response['result'].keys() and
                'path' in response['result']['details'].keys()) :
                image_url = base_url + "/" + response['result']['details']['path']
                #print("image_url : ", image_url) # debug info

            r = requests.get(image_url, stream = True)
            # check that the retrieval was successful before proceeding
            if r.status_code == 200:
                try:
                    r.raw.decode_content = True
                    cover = Image.open(io.BytesIO(r.content))
                    image_set       = True
                    resize_needed   = True
                    _last_image_time = new_image_time
                except:
                    cover = Image.open(default_thumb)
                    prev_image = cover
                    image_set     = True
                    resize_needed = True
        else:
            image_set = True


    # Finally, if we still don't have anything, check if we are local
    # to Kodi and Airplay artwork can just be opened.  Otherwise, use
    # default images.
    if not image_set:
        resize_needed = True
        if _airtunes_re.match(cover_path):
            airplay_thumb = "/storage/.kodi/temp/" + _airtunes_re.match(cover_path).group(1)
            if os.path.isfile(airplay_thumb):
                _last_image_path = airplay_thumb
                resize_needed   = True
            else:
                _last_image_path = default_airplay
        else:
            # default image when no artwork is available
            _last_image_path = default_thumb

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


# Idle status screen (shown upon a screen press)
#
# First argument is a Pillow ImageDraw object.
# Second argument is a dictionary loaded from Kodi system status fields.
# This argument is the string to use for current state of the system
#
def status_screen(draw, kodi_status, summary_string):
    layout = STATUS_LAYOUT

    str_prefix = {
        "System.Date"           : "",
        "System.Uptime"         : "Up: ",
        "System.CPUTemperature" : "CPU: ",
        "System.CpuFrequency"   : "Freq: ",
    }

    # Kodi logo, if desired
    if "thumb" in layout.keys():
        kodi_icon = Image.open(kodi_thumb)
        kodi_icon.thumbnail((layout["thumb"]["size"], layout["thumb"]["size"]))
        image.paste(kodi_icon, (layout["thumb"]["posx"], layout["thumb"]["posy"] ))

    # go through all text fields, if any
    if "fields" not in layout.keys():
        return

    txt_field = layout["fields"]

    for index in range(len(txt_field)):
        if txt_field[index]["name"] == "version":
            draw.text((txt_field[index]["posx"],txt_field[index]["posy"]),
                      "kodi_panel " + PANEL_VER,
                      txt_field[index]["fill"], txt_field[index]["font"])

        elif txt_field[index]["name"] == "summary":
            draw.text((txt_field[index]["posx"],txt_field[index]["posy"]),
                      summary_string,
                      txt_field[index]["fill"], txt_field[index]["font"])

        elif txt_field[index]["name"] == "kodi_version":
            kodi_version = kodi_status["System.BuildVersion"].split()[0]
            build_date   = kodi_status["System.BuildDate"]
            draw.text((txt_field[index]["posx"],txt_field[index]["posy"]),
                      "Kodi version: " + kodi_version + " (" + build_date + ")",
                      txt_field[index]["fill"], txt_field[index]["font"])

        elif txt_field[index]["name"] == "time_hrmin":
            # time, in 7-segment font by default
            time_parts = kodi_status['System.Time'].split(" ")
            time_width, time_height = draw.textsize(time_parts[0], txt_field[index]["font"])
            draw.text((txt_field[index]["posx"],txt_field[index]["posy"]),
                      time_parts[0],
                      txt_field[index]["fill"], txt_field[index]["font"])
            draw.text((txt_field[index]["posx"] + time_width + 5, txt_field[index]["posy"]),
                      time_parts[1],
                      txt_field[index]["fill"], txt_field[index]["smfont"])

        else:
            display_string = kodi_status[txt_field[index]["name"]]
            if txt_field[index]["name"] in str_prefix.keys():
                display_string = str_prefix[txt_field[index]["name"]] + display_string

            draw.text((txt_field[index]["posx"],txt_field[index]["posy"]),
                      display_string,
                      txt_field[index]["fill"], txt_field[index]["font"])



# Audio info screens (shown when music is playing).  With the
# introduction of the AUDIO_LAYOUT data structure, all 3 modes are
# handled here in this function.
#
# First two arguments are Pillow Image and ImageDraw objects.
# Third argument is a dictionary loaded from Kodi with relevant track fields.
# Fourth argument is a float representing progress through the track.
#
def audio_screens(image, draw, info, prog):
    global audio_dmode
    global _last_thumb
    global _last_image_path

    # Get layout details for this mode
    layout = AUDIO_LAYOUT[audio_dmode.name]

    # retrieve cover image from Kodi, if it exists and needs a refresh
    if "thumb" in layout.keys():
        _last_thumb = get_artwork(info['MusicPlayer.Cover'], _last_thumb,
                                  layout["thumb"]["size"], layout["thumb"]["size"])
        if _last_thumb:
            if layout["thumb"].get("center",0):
                image.paste(_last_thumb,
                            (int((frame_size[0]-_last_thumb.width)/2),
                             int((frame_size[1]-_last_thumb.height)/2)))
            elif (layout["thumb"].get("center_sm", 0) and
                  (_last_thumb.width < layout["thumb"]["size"] or
                   _last_thumb.height < layout["thumb"]["size"])):
                new_x = layout["thumb"]["posx"]
                new_y = layout["thumb"]["posy"]
                if _last_thumb.width < layout["thumb"]["size"]:
                    new_x += int((layout["thumb"]["size"]/2) - (_last_thumb.width/2))
                if _last_thumb.height < layout["thumb"]["size"]:
                    new_y += int((layout["thumb"]["size"]/2) - (_last_thumb.height/2))
                image.paste(_last_thumb, (new_x, new_y))
            else:
                image.paste(_last_thumb, (layout["thumb"]["posx"], layout["thumb"]["posy"]))
    else:
        _last_thumb = None

    # progress bar
    if (prog != -1 and "prog" in layout.keys()):
        if "vertical" in layout["prog"].keys():
            progress_bar(draw, colors["color_progbg"], colors["color_progfg"],
                         layout["prog"]["posx"], layout["prog"]["posy"],
                         layout["prog"]["len"],
                         layout["prog"]["height"],
                         prog, vertical=True)
        elif info['MusicPlayer.Time'].count(":") == 2:
            # longer bar for longer displayed time
            progress_bar(draw, colors["color_progbg"], colors["color_progfg"],
                         layout["prog"]["posx"], layout["prog"]["posy"],
                         layout["prog"]["long_len"], layout["prog"]["height"],
                         prog)
        else:
            progress_bar(draw, colors["color_progbg"], colors["color_progfg"],
                         layout["prog"]["posx"], layout["prog"]["posy"],
                         layout["prog"]["short_len"], layout["prog"]["height"],
                         prog)

    # text fields, if there are any
    if "fields" not in layout.keys():
        return

    txt_field = layout["fields"]
    for index in range(len(txt_field)):

        # special treatment for "codec", which gets a lookup
        if txt_field[index]["name"] == "codec":
            if info['MusicPlayer.Codec'] in codec_name.keys():
                # render any label first
                if "label" in txt_field[index]:
                    draw.text((txt_field[index]["lposx"], txt_field[index]["lposy"]),
                              txt_field[index]["label"],
                              fill=txt_field[index]["lfill"], font=txt_field[index]["lfont"])
                draw.text((txt_field[index]["posx"], txt_field[index]["posy"]),
                          codec_name[info['MusicPlayer.Codec']],
                          fill=txt_field[index]["fill"],
                          font=txt_field[index]["font"])

        # special treatment for "full_codec"
        elif txt_field[index]["name"] == "full_codec":
            if info['MusicPlayer.Codec'] in codec_name.keys():
                display_text =  codec_name[info['MusicPlayer.Codec']]
                display_text += " (" + info['MusicPlayer.BitsPerSample'] + "/" + \
                    info['MusicPlayer.SampleRate'] + ")"
                
                # render any label first
                if "label" in txt_field[index]:
                    draw.text((txt_field[index]["lposx"], txt_field[index]["lposy"]),
                              txt_field[index]["label"],
                              fill=txt_field[index]["lfill"], font=txt_field[index]["lfont"])
                draw.text((txt_field[index]["posx"], txt_field[index]["posy"]),
                          display_text,
                          fill=txt_field[index]["fill"],
                          font=txt_field[index]["font"])                

        # special treatment for "artist"
        elif txt_field[index]["name"] == "artist":
            display_string = None
            if info['MusicPlayer.Artist'] != "":
                display_string = info['MusicPlayer.Artist']
            elif info['MusicPlayer.Property(Role.Composer)'] != "":
                display_string =  "(" + info['MusicPlayer.Property(Role.Composer)'] + ")"

            if (display_string == "Unknown" and
                txt_field[index].get("drop_unknown",0)):
                continue

            if display_string:
                if "wrap" in txt_field[index].keys():
                    render_text_wrap(draw,
                                     (txt_field[index]["posx"], txt_field[index]["posy"]),
                                     display_string,
                                     max_width=txt_field[index]["max_width"],
                                     max_lines=txt_field[index]["max_lines"],
                                     fill=txt_field[index]["fill"],
                                     font=txt_field[index]["font"])
                elif "trunc" in txt_field[index].keys():
                    render_text_wrap(draw,
                                     (txt_field[index]["posx"], txt_field[index]["posy"]),
                                     display_string,
                                     max_width=frame_size[0] - txt_field[index]["posx"],
                                     max_lines=1,
                                     fill=txt_field[index]["fill"],
                                     font=txt_field[index]["font"])
                else:
                    draw.text((txt_field[index]["posx"], txt_field[index]["posy"]),
                              display_string,
                              fill=txt_field[index]["fill"],
                              font=txt_field[index]["font"])

        # all other text fields
        else:
            if (txt_field[index]["name"] in info.keys() and
                info[txt_field[index]["name"]] != ""):
                # render any label first
                if "label" in txt_field[index]:
                    draw.text((txt_field[index]["lposx"], txt_field[index]["lposy"]),
                              txt_field[index]["label"],
                              fill=txt_field[index]["lfill"], font=txt_field[index]["lfont"])
                # now render the field itself
                if "wrap" in txt_field[index].keys():
                    render_text_wrap(draw,
                                     (txt_field[index]["posx"], txt_field[index]["posy"]),
                                     info[txt_field[index]["name"]],
                                     max_width=txt_field[index]["max_width"],
                                     max_lines=txt_field[index]["max_lines"],
                                     fill=txt_field[index]["fill"],
                                     font=txt_field[index]["font"])
                elif "trunc" in txt_field[index].keys():
                    render_text_wrap(draw,
                                     (txt_field[index]["posx"], txt_field[index]["posy"]),
                                     info[txt_field[index]["name"]],
                                     max_width=frame_size[0] - txt_field[index]["posx"],
                                     max_lines=1,
                                     fill=txt_field[index]["fill"],
                                     font=txt_field[index]["font"])
                else:
                    draw.text((txt_field[index]["posx"], txt_field[index]["posy"]),
                              info[txt_field[index]["name"]],
                              fill=txt_field[index]["fill"],
                              font=txt_field[index]["font"])



# Video info screens (shown when a video is playing).
#
# First two arguments are Pillow Image and ImageDraw objects.
# Third argument is a dictionary loaded from Kodi with relevant track fields.
# Fourth argument is a float representing progress through the track.
#
def video_screens(image, draw, info, prog):
    global video_dmode
    global _last_thumb
    global _last_image_path

    # Get layout details for this mode
    layout = VIDEO_LAYOUT[video_dmode.name]

    # retrieve cover image from Kodi, if it exists and needs a refresh
    if "thumb" in layout.keys():
        _last_thumb = get_artwork(info['VideoPlayer.Cover'], _last_thumb,
                                  layout["thumb"]["width"], layout["thumb"]["height"])
        if _last_thumb:
            if layout["thumb"].get("center",0):
                image.paste(_last_thumb,
                            (int((frame_size[0]-_last_thumb.width)/2),
                             int((frame_size[1]-_last_thumb.height)/2)))
            elif (layout["thumb"].get("center_sm", 0) and
                  (_last_thumb.width < layout["thumb"]["width"] or
                   _last_thumb.height < layout["thumb"]["height"])):
                new_x = layout["thumb"]["posx"]
                new_y = layout["thumb"]["posy"]
                if _last_thumb.width < layout["thumb"]["width"]:
                    new_x += int((layout["thumb"]["width"]/2) - (_last_thumb.width/2))
                if _last_thumb.height < layout["thumb"]["height"]:
                    new_y += int((layout["thumb"]["height"]/2) - (_last_thumb.height/2))
                image.paste(_last_thumb, (new_x, new_y))
            else:
                image.paste(_last_thumb, (layout["thumb"]["posx"], layout["thumb"]["posy"]))
    else:
        _last_thumb = None

    # progress bar
    if (prog != -1 and "prog" in layout.keys()):
        if "vertical" in layout["prog"].keys():
            progress_bar(draw, colors["color_progbg"], colors["color_progfg"],
                         layout["prog"]["posx"], layout["prog"]["posy"],
                         layout["prog"]["len"],
                         layout["prog"]["height"],
                         prog, vertical=True)
        elif info['VideoPlayer.Time'].count(":") == 2:
            # longer bar for longer displayed time
            progress_bar(draw, colors["color_progbg"], colors["color_progfg"],
                         layout["prog"]["posx"], layout["prog"]["posy"],
                         layout["prog"]["long_len"], layout["prog"]["height"],
                         prog)
        else:
            progress_bar(draw, colors["color_progbg"], colors["color_progfg"],
                         layout["prog"]["posx"], layout["prog"]["posy"],
                         layout["prog"]["short_len"], layout["prog"]["height"],
                         prog)

    # text fields, if there are any
    if "fields" not in layout.keys():
        return

    txt_field = layout["fields"]
    for index in range(len(txt_field)):

        # special treatment for audio codec, which gets a lookup
        if txt_field[index]["name"] == "acodec":
            if info['VideoPlayer.Codec'] in codec_name.keys():
                # render any label first
                if "label" in txt_field[index]:
                    draw.text((txt_field[index]["lposx"], txt_field[index]["lposy"]),
                              txt_field[index]["label"],
                              fill=txt_field[index]["lfill"], font=txt_field[index]["lfont"])
                draw.text((txt_field[index]["posx"], txt_field[index]["posy"]),
                          codec_name[info['VideoPlayer.Codec']],
                          fill=txt_field[index]["fill"],
                          font=txt_field[index]["font"])

        # all other text fields
        else:
            if (txt_field[index]["name"] in info.keys() and
                info[txt_field[index]["name"]] != ""):
                # render any label first
                if "label" in txt_field[index]:
                    draw.text((txt_field[index]["lposx"], txt_field[index]["lposy"]),
                              txt_field[index]["label"],
                              fill=txt_field[index]["lfill"], font=txt_field[index]["lfont"])
                # now render the field itself
                if "wrap" in txt_field[index].keys():
                    render_text_wrap(draw,
                                     (txt_field[index]["posx"], txt_field[index]["posy"]),
                                     info[txt_field[index]["name"]],
                                     max_width=txt_field[index]["max_width"],
                                     max_lines=txt_field[index]["max_lines"],
                                     fill=txt_field[index]["fill"],
                                     font=txt_field[index]["font"])
                elif "trunc" in txt_field[index].keys():
                    render_text_wrap(draw,
                                     (txt_field[index]["posx"], txt_field[index]["posy"]),
                                     info[txt_field[index]["name"]],
                                     max_width=frame_size[0] - txt_field[index]["posx"],
                                     max_lines=1,
                                     fill=txt_field[index]["fill"],
                                     font=txt_field[index]["font"])
                else:
                    draw.text((txt_field[index]["posx"], txt_field[index]["posy"]),
                              info[txt_field[index]["name"]],
                              fill=txt_field[index]["fill"],
                              font=txt_field[index]["font"])




# Given current position ([h:]m:s) and duration, calculate
# percentage done as a float for progress bar display.
def calc_progress(time_str, duration_str):
    if (time_str == "" or duration_str == ""):
        return -1
    if not (1 <= time_str.count(":") <= 2 and
            1 <= duration_str.count(":") <= 2):
        return -1

    cur_secs   = sum(int(x) * 60 ** i for i, x in enumerate(reversed(time_str.split(':'))))
    total_secs = sum(int(x) * 60 ** i for i, x in enumerate(reversed(duration_str.split(':'))))
    if (total_secs > 0 and
        cur_secs <= total_secs):
        return cur_secs/total_secs
    else:
        return -1


def screen_on():
    if (not USE_BACKLIGHT or DEMO_MODE):
        return
    if USE_PWM:
        device.backlight(PWM_LEVEL)
    else:
        device.backlight(True)

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
def update_display():
    global _last_image_path
    global _last_thumb
    global screen_press
    global screen_active
    global screen_offtime
    global audio_dmode
    global video_dmode

    lock.acquire()

    # Start with a blank slate
    draw.rectangle([(0,0), (frame_size[0],frame_size[1])], 'black', 'black')

    # Check if the screen_active time has expired
    if (screen_active and datetime.now() >= screen_offtime):
        screen_active = False
        screen_off()

    # Ask Kodi whether anything is playing...
    payload = {
        "jsonrpc": "2.0",
        "method"  : "Player.GetActivePlayers",
        "id"      : 3,
    }
    response = requests.post(rpc_url, data=json.dumps(payload), headers=headers).json()

    if (len(response['result']) == 0 or
        response['result'][0]['type'] == 'picture' or
        (response['result'][0]['type'] == 'video' and not VIDEO_ENABLED) or
        (response['result'][0]['type'] == 'audio' and not AUDIO_ENABLED)):
        # Nothing is playing or something for which no display screen
        # is available.

        # Check for screen press before proceeding.  A press when idle
        # generates the status screen.
        _last_image_path = None
        _last_image_time = None
        _last_thumb = None

        if screen_press:
            screen_press = False
            screen_on()
            screen_active = True
            screen_offtime = datetime.now() + timedelta(seconds=screen_wake)

        if screen_active:
            # Idle status screen
            if len(response['result']) == 0:
                summary = "Idle"
            elif response['result'][0]['type'] == 'video':
                summary = "Video playing"
            elif response['result'][0]['type'] == 'picture':
                summary = "Photo viewing"

            payload = {
                "jsonrpc": "2.0",
                "method"  : "XBMC.GetInfoLabels",
                "params"  : {"labels": ["System.Uptime",
                                        "System.CPUTemperature",
                                        "System.CpuFrequency",
                                        "System.Date",
                                        "System.Time",
                                        "System.BuildVersion",
                                        "System.BuildDate",
                                        "System.FreeSpace"
                ]},
                "id"      : 10,
            }
            status_resp = requests.post(rpc_url, data=json.dumps(payload), headers=headers).json()
            status_screen(draw, status_resp['result'], summary)
        else:
            screen_off()

    elif (response['result'][0]['type'] == 'video' and VIDEO_ENABLED):
        # Video is playing
        screen_on()

        # Change display modes upon any screen press, forcing a
        # re-fetch of any artwork.  Clear other state that may also be
        # mode-specific.
        if screen_press:
            screen_press = False
            video_dmode = video_dmode.next()
            print(datetime.now(), "video display mode now", video_dmode.name)
            _last_image_path = None
            _last_image_time = None
            _last_thumb = None
            truncate_line.cache_clear()
            text_wrap.cache_clear()

        # Retrieve (almost) all desired info in a single JSON-RPC call
        payload = {
            "jsonrpc": "2.0",
            "method"  : "XBMC.GetInfoLabels",
            "params"  : {"labels": ["VideoPlayer.Title",
                                    "VideoPlayer.TVShowTitle",
                                    "VideoPlayer.Season",
                                    "VideoPlayer.Episode",
                                    "VideoPlayer.Duration",
                                    "VideoPlayer.Time",
                                    "VideoPlayer.Genre",
                                    "VideoPlayer.Year",
                                    "VideoPlayer.VideoCodec",
                                    "VideoPlayer.AudioCodec",
                                    "VideoPlayer.Rating",
                                    "VideoPlayer.Cover",
            ]},
            "id"      : 4,
        }
        response = requests.post(rpc_url, data=json.dumps(payload), headers=headers).json()
        #print("Response: ", json.dumps(response))
        video_info = response['result']

        # See remarks in audio_screens() regarding calc_progress()
        prog = calc_progress(video_info["VideoPlayer.Time"], video_info["VideoPlayer.Duration"])

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

    elif (response['result'][0]['type'] == 'audio' and AUDIO_ENABLED):
        # Audio is playing!
        screen_on()

        # Change display modes upon any screen press, forcing a
        # re-fetch of any artwork.  Clear other state that may also be
        # mode-specific.
        if screen_press:
            screen_press = False
            audio_dmode = audio_dmode.next()
            print(datetime.now(), "audio display mode now", audio_dmode.name)
            _last_image_path = None
            _last_image_time = None
            _last_thumb = None
            truncate_line.cache_clear()
            text_wrap.cache_clear()

        # Retrieve (almost) all desired info in a single JSON-RPC call
        payload = {
            "jsonrpc": "2.0",
            "method"  : "XBMC.GetInfoLabels",
            "params"  : {"labels": ["MusicPlayer.Title",
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
            ]},
            "id"      : 4,
        }
        response = requests.post(rpc_url, data=json.dumps(payload), headers=headers).json()
        #print("Response: ", json.dumps(response))
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

        prog = calc_progress(track_info["MusicPlayer.Time"], track_info["MusicPlayer.Duration"])

        # There seems to be a hiccup in DLNA/UPnP playback in which a
        # change (or stopping playback) causes a moment when
        # nothing is actually playing, according to the Info Labels.
        if ((track_info["MusicPlayer.Time"] == "00:00" or
             track_info["MusicPlayer.Time"] == "00:00:00") and
            track_info["MusicPlayer.Duration"] == "" and
            track_info["MusicPlayer.Cover"] == ""):
            pass
        else:
            audio_screens(image, draw, track_info, prog)

    # Output to OLED/LCD display
    device.display(image)
    lock.release()


# Interrupt callback target from RPi.GPIO for T_IRQ
def touch_callback(channel):
    global screen_press
    global kodi_active
    screen_press = kodi_active
    #print(datetime.now(), "Touchscreen pressed")
    if kodi_active:
        try:
            update_display()
            screen_press = False
        except:
            pass


def main(device_handle):
    global device
    global kodi_active
    global screen_press
    kodi_active = False

    device = device_handle

    print(datetime.now(), "Starting")
    # turn down verbosity from http connections
    logging.basicConfig()
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    # setup T_IRQ as a GPIO interrupt, if enabled
    if (USE_TOUCH and not DEMO_MODE):
        print(datetime.now(), "Setting up touchscreen interrupt")
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(TOUCH_INT, GPIO.IN)
        GPIO.add_event_detect(TOUCH_INT, GPIO.FALLING,
                              callback=touch_callback, bouncetime=950)

    # main communication loop
    while True:
        screen_on()
        draw.rectangle([(0,0), (frame_size[0],frame_size[1])], 'black', 'black')
        draw.text(( 5, 5), "Waiting to connect with Kodi...",  fill='white', font=fonts["font_main"])
        device.display(image)

        while True:
            # ensure Kodi is up and accessible
            payload = {
                "jsonrpc": "2.0",
                "method"  : "JSONRPC.Ping",
                "id"      : 2,
            }

            try:
                response = requests.post(rpc_url, data=json.dumps(payload), headers=headers).json()
                if response['result'] != 'pong':
                    print(datetime.now(), "Kodi not available via HTTP-transported JSON-RPC.  Waiting...")
                    time.sleep(5)
                else:
                    break
            except:
                time.sleep(5)
                pass

        print(datetime.now(), "Connected with Kodi.  Entering update_display() loop.")
        screen_off()

        # Loop until Kodi goes away
        kodi_active = True
        screen_press = False
        while True:
            try:
                start_time = time.time()
                if DEMO_MODE:
                    keys = device._pygame.key.get_pressed()
                    if keys[device._pygame.K_SPACE]:
                        screen_press = True
                        print(datetime.now(), "Touchscreen pressed (emulated)")
                update_display()
            except (ConnectionRefusedError,
                    requests.exceptions.ConnectionError):
                print(datetime.now(), "Communication disrupted.")
                kodi_active = False
                break

            # If connecting to Kodi over an actual network connection,
            # update times can vary.  Rather than sleeping for a fixed
            # duration, we might as well measure how long the update
            # took and then sleep whatever remains of that second.

            elapsed = time.time() - start_time
            if elapsed < 1:
                time.sleep(1 - elapsed)
            else:
                time.sleep(0.4)


def shutdown():
    if (USE_TOUCH and not DEMO_MODE):
        print(datetime.now(), "Removing touchscreen interrupt")
        GPIO.remove_event_detect(TOUCH_INT)
        GPIO.cleanup()
    print(datetime.now(), "Stopping")
    exit(0)
