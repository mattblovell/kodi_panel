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

from luma.core.interface.serial import spi
from luma.core.render import canvas
from luma.lcd.device import ili9341

import sys
import RPi.GPIO as GPIO

from PIL import Image
from PIL import ImageDraw
from PIL import ImageFont

from datetime import datetime, timedelta
from enum import Enum
import time
import logging
import requests
import json
import io
import re
import os
import threading

# ----------------------------------------------------------------------------
PANEL_VER = "v0.80"

base_url = "http://localhost:8080"  # use localhost if running on same box as Kodi
rpc_url  = base_url + "/jsonrpc"
headers  = {'content-type': 'application/json'}

# Image handling
frame_size      = (320, 240)
last_image_path = None
last_thumb      = None

# Thumbnail defaults (these don't get resized)
kodi_thumb      = "./images/kodi_thumb.jpg"
default_thumb   = "./images/music_icon.png"
default_airplay = "./images/airplay_thumb.png"

# RegEx for recognizing AirPlay images (compiled once)
special_re = re.compile(r'^special:\/\/temp\/(airtunes_album_thumb\.(png|jpg))')

# Track info fonts
font_main = ImageFont.truetype("fonts/FreeSans.ttf", 22, encoding='unic')
font_bold = ImageFont.truetype("fonts/FreeSansBold.ttf", 22, encoding='unic')
font_sm   = ImageFont.truetype("fonts/FreeSans.ttf", 18, encoding='unic')
font_tiny = ImageFont.truetype("fonts/FreeSans.ttf", 11, encoding='unic')

# 7-Segment Font for time and track number
font7S    = ImageFont.truetype("fonts/DSEG14Classic-Regular.ttf", 32)
font7S_sm = ImageFont.truetype("fonts/DSEG14Classic-Regular.ttf", 11)

# Colors
color7S       = 'SpringGreen'   # 7-Segment color
color_progbg  = 'dimgrey'       # progress bar background
color_progfg  = color7S         # progress bar foreground
color_artist  = 'yellow'        # artist name

# Pillow objects
image  = Image.new('RGB', (frame_size), 'black')
draw   = ImageDraw.Draw(image)

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


# Audio screen enumeration
#
# The next() function serves to switch modes in response to screen
# touches.  The list is intended to grow, as other ideas for layouts
# are proposed.
class ADisplay(Enum):
    DEFAULT    = 0   # small artwork, elapsed time, track info
    FULLSCREEN = 1   # fullscreen cover artwork
    FULL_PROG  = 2   # fullscreen art with vertical progress bar

    def next(self):
        cls = self.__class__
        members = list(cls)
        index = members.index(self) + 1
        if index >= len(members):
            index = 0
        return members[index]

# At startup, just use the default layout for audio info.  This
# setting, if serialized and stored someplace, could be made
# persistent across script invocations if desired.
audio_dmode = ADisplay.DEFAULT


# Audio screen layouts, used by audio_screens()
AUDIO_LAYOUT = \
{ ADisplay.DEFAULT :
  {
    # Artwork position and size
    "thumb" : { "pos": (5, 5), "size": 140 },

    # Progress bar.  Two versions are possible, short and long,
    # depending upon the MusicPlayer.Time string.
    "prog"  : { "pos": (150, 7),
                "short_len": 104,  "long_len": 164,
                "height": 8 },

    # All other text fields, including any labels
    #
    # Removing fields can be accomplished just by commenting out the
    # corresponding entry in this array.  If a new field is desired,
    # then the JSON-RPC call made in update_display() likely needs to
    # be augmented first.
    #
    # Special treatment exists for 'codec' and 'artist'.
    #
    "fields" :
    [
        { "name": "MusicPlayer.Time",          "pos": (148, 20), "font": font7S, "fill":color7S },

        { "name":  "MusicPlayer.TrackNumber",  "pos": (148, 73),  "font": font7S,     "fill": color7S,
          "label": "Track",                   "lpos": (148, 60), "lfont": font_tiny, "lfill": "white" },

        { "name": "MusicPlayer.Duration", "pos": (230, 60), "font": font_tiny, "fill": "white" },
        { "name": "codec",                "pos": (230, 74), "font": font_tiny, "fill": "white" },
        { "name": "MusicPlayer.Genre",    "pos": (230, 88), "font": font_tiny, "fill": "white", "trunc":1 },
        { "name": "MusicPlayer.Year",     "pos": (230,102), "font": font_tiny, "fill": "white" },

        { "name": "MusicPlayer.Title",    "pos": (5, 152),  "font": font_main, "fill": "white",      "trunc":1 },
        { "name": "MusicPlayer.Album",    "pos": (5, 180),  "font": font_sm,   "fill": "white",      "trunc":1 },
        { "name": "artist",               "pos": (5, 205),  "font": font_sm,   "fill": color_artist, "trunc":1 },
    ]
  },

  ADisplay.FULLSCREEN :
  {
    # artwork size, position is determined by centering
    "thumb"   : { "center": 1, "size": frame_size[1]-5 },
  },

  ADisplay.FULL_PROG :
  {
    # artwork size, position is determined by centering
    "thumb" : { "center": 1, "size": frame_size[1]-5 },

    # vertical progress bar
    "prog" : { "pos": (frame_size[0]-12, 1),
               "len": 10,
               "height": frame_size[1]-4,
               "vertical": 1
    },
  },

}


# Layout control for status screen, used by status_screen()
STATUS_LAYOUT = \
{
    # Kodi logo
    "thumb" : { "pos": (5, 5), "size": 128 },

    # all other text fields
    #
    # special treatment exists for several field names
    "fields" :
    [
        { "name": "version",    "pos": (145,  8), "font": font_main, "fill": color_artist },
        { "name": "summary",    "pos": (145, 35), "font": font_sm,   "fill": "white" },
        { "name": "time_hrmin", "pos": (145, 73), "font": font7S,    "fill": color7S,  "smfont": font7S_sm },

        { "name": "System.Date",           "pos": (  5,150), "font": font_sm,   "fill": "white" },
        { "name": "System.Uptime",         "pos": (  5,175), "font": font_sm,   "fill": "white" },
        { "name": "System.CPUTemperature", "pos": (  5,200), "font": font_sm,   "fill": "white" },
    ]
}


# ----------------------------------------------------------------------------

# GPIO assignment for screen's touch interrupt (T_IRQ), using RPi.GPIO
# numbering.  Find a pin that's unused by luma.  The touchscreen chip
# in my display has its own internal pullup resistor, so below no
# pullup is specified.
USE_TOUCH      = True   # Set False to disable interrupt use
TOUCH_INT      = 19

# Internal state variables used to manage screen presses
kodi_active    = False
screen_press   = False
screen_active      = False
screen_wake    = 15    # status screen waketime, in seconds
screen_offtime = datetime.now()

# Provide a lock to ensure update_display() is single-threaded.  (This
# is perhaps unnecessary given Python's GIL, but is certainly safe.)
lock = threading.Lock()

# Additional screen controls.  Note that RPi.GPIO's PWM control, even
# the Odroid variant (?), uses software to control the signal, which
# can result in flickering.
#
# I have not yet found a way to take advantage of the C4's hardware
# PWM simultaneous with using luma.lcd.
USE_BACKLIGHT = True
USE_PWM       = False
PWM_FREQ      = 362      # frequency, presumably in Hz
PWM_LEVEL     = 75.0     # float value between 0 and 100


# Finally, a handle to the ILI9341-driven SPI panel via luma.lcd.
#
# The backlight signal (with inline resistor NEEDED) is connected to
# GPIO18, physical pin 12.  Recall that the GPIOx number is using
# RPi.GPIO's scheme!
#
# Below is how I've connected the ILI9341, which is *close* to the
# recommended wiring in luma.lcd's online documentation.  Again,
# recall the distinction between RPi.GPIO pin naming and physical pin
# numbers.
#
# As you can provide RPi.GPIO numbers as arguments to the spi()
# constructor, you do have some flexibility.
#
#
#   LCD pin     |  RPi.GPIO name   |  Odroid C4 pin #
#   ------------|------------------|-----------------
#   VCC         |  3V3             |  1 or 17
#   GND         |  GND             |  9 or 25 or 39
#   CS          |  GPIO8           |  24
#   RST / RESET |  GPIO25          |  22
#   DC          |  GPIO24          |  18
#   MOSI        |  GPIO10 (MOSI)   |  19
#   SCLK / CLK  |  GPIO11 (SCLK)   |  23
#   LED         |  GPIO18          |  12 (a.k.a. PWM_E)
#   ------------|------------------|-----------------
#
# Originally, the constructor for ili9341 also included a
# framebuffer="full_frame" argument.  That proved unnecessary
# once non-zero reset hold and release times were specified
# for the device.
#
serial = spi(port=0, device=0, gpio_DC=24, gpio_RST=25,
             reset_hold_time=0.2, reset_release_time=0.2)

if USE_PWM:
    device = ili9341(serial, active_low=False, width=320, height=240,
                     bus_speed_hz=32000000,
                     gpio_LIGHT=18,
                     pwm_frequency=PWM_FREQ
    )
else:
    device = ili9341(serial, active_low=False, width=320, height=240,
                     bus_speed_hz=32000000,
                     gpio_LIGHT=18
    )

# ----------------------------------------------------------------------------

# Maintain a short list of the most recently-truncated strings,
# for use by truncate_text()
last_trunc = []


# Render text at the specified location, truncating characters and
# placing a final ellipsis if the string is too wide to display in its
# entirety.
#
# In its present form, this function essentially only checks for
# extensions past the right-hand side of the screen.  That could
# be remedied, if needed, by passing in a maximum permitted width
# and using it.
def truncate_text(pil_draw, xy, text, fill, font):
    global last_trunc
    truncating = 0

    # Assume an upper bound on how many characters are even
    # possible to display
    new_text = text[0:59];

    # Check if we've already truncated this string
    for index in range(len(last_trunc)):
        if (new_text == last_trunc[index]["str"] and
            font == last_trunc[index]["font"]):
            new_text = last_trunc[index]["short_str"]
            if last_trunc[index]["truncating"]:
                new_text += "\u2026"
            pil_draw.text(xy, new_text, fill, font)
            return

    # Otherwise, try an initial rendering
    t_width, t_height = pil_draw.textsize(new_text, font)

    # Form an initial estimate for how many characters will fit
    avg_char = len(new_text) / t_width
    avail_width = frame_size[0] - 10
    num_chars = int( (avail_width + 20) / avg_char )
    new_text = new_text[0:num_chars]

    # Now perform naive truncation.  A binary search would
    # be faster, if further speed is needed
    t_width, t_height = pil_draw.textsize(new_text, font)
    while (xy[0] + t_width) > avail_width:
        truncating = 1
        new_text = new_text[:-1]
        t_width, t_height = pil_draw.textsize(new_text, font)

    disp_text = new_text
    if truncating:
        disp_text += "\u2026"
    pil_draw.text(xy, disp_text, fill, font)

    # Store results for later consultation
    new_result = {
        "str"        : text[0:59],
        "short_str"  : disp_text,
        "truncating" : truncating,
        "font"       : font
        }
    last_trunc.insert(0, new_result)
    last_trunc = last_trunc[:9]



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
# The global last_image_path is intended to let any given image file
# be fetched and resized just *once*.  Subsequent calls just reuse the
# same data, provided that the caller preserves and passes in
# prev_image.
#
# The info argument must be the result of an XBMC.GetInfoLabels
# JSON-RPC call to Kodi.
def get_artwork(info, prev_image, thumb_size):
    global last_image_path
    image_set     = False
    resize_needed = False

    cover = None   # retrieved artwork, original size
    thumb = None   # resized artwork

    if (info['MusicPlayer.Cover'] != '' and
        info['MusicPlayer.Cover'] != 'DefaultAlbumCover.png' and
        not special_re.match(info['MusicPlayer.Cover'])):

        image_path = info['MusicPlayer.Cover']
        #print("image_path : ", image_path) # debug info

        if (image_path == last_image_path and prev_image):
            # Fall through and just return prev_image
            image_set = True
        else:
            last_image_path = image_path
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
                    resize_needed = False

    # finally, if we still don't have anything, check if is Airplay active
    if not image_set:
        resize_needed = False
        if special_re.match(info['MusicPlayer.Cover']):
            airplay_thumb = "/storage/.kodi/temp/" + special_re.match(info['MusicPlayer.Cover']).group(1)
            if os.path.isfile(airplay_thumb):
                last_image_path = airplay_thumb
                resize_needed   = True
            else:
                last_image_path = default_airplay
        else:
            # default image when no artwork is available
            last_image_path = default_thumb

        cover = Image.open(last_image_path)
        prev_image = cover
        image_set = True

    # is resizing needed?
    if (image_set and resize_needed):
        # resize while maintaining aspect ratio, if possible
        orig_w, orig_h = cover.size[0], cover.size[1]
        shrink    = (float(thumb_size)/orig_h)
        new_width = int(float(orig_h)*float(shrink))
        # just crop if the image turns out to be really wide
        if new_width > thumb_size:
            thumb = cover.resize((new_width, thumb_size), Image.ANTIALIAS).crop((0,0,140,thumb_size))
        else:
            thumb = cover.resize((new_width, thumb_size), Image.ANTIALIAS)
        prev_image = thumb

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
    }

    # Kodi logo, if desired
    if "thumb" in layout.keys():
        kodi_icon = Image.open(kodi_thumb)
        kodi_icon.thumbnail((layout["thumb"]["size"], layout["thumb"]["size"]))
        image.paste(kodi_icon, layout["thumb"]["pos"])

    # go through all text fields, if any
    if "fields" not in layout.keys():
        return

    txt_field = layout["fields"]

    for index in range(len(txt_field)):
        if txt_field[index]["name"] == "version":
            draw.text(txt_field[index]["pos"], "kodi_panel " + PANEL_VER,
                      txt_field[index]["fill"], txt_field[index]["font"])

        elif txt_field[index]["name"] == "summary":
            draw.text(txt_field[index]["pos"], summary_string,
                      txt_field[index]["fill"], txt_field[index]["font"])

        elif txt_field[index]["name"] == "time_hrmin":
            # time, in 7-segment font by default
            time_parts = kodi_status['System.Time'].split(" ")
            time_width, time_height = draw.textsize(time_parts[0], font7S)
            draw.text(txt_field[index]["pos"], time_parts[0],
                      txt_field[index]["fill"], txt_field[index]["font"])
            draw.text((txt_field[index]["pos"][0] + time_width + 5, txt_field[index]["pos"][1]),
                      time_parts[1],
                      txt_field[index]["fill"], txt_field[index]["smfont"])

        else:
            display_string = kodi_status[txt_field[index]["name"]]
            if txt_field[index]["name"] in str_prefix.keys():
                display_string = str_prefix[txt_field[index]["name"]] + display_string

            draw.text(txt_field[index]["pos"], display_string,
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
    global last_thumb
    global last_image_path

    # Get layout details for this mode
    layout = AUDIO_LAYOUT[audio_dmode]

    # retrieve cover image from Kodi, if it exists and needs a refresh
    if "thumb" in layout.keys():
        last_thumb = get_artwork(info, last_thumb, layout["thumb"]["size"])
        if last_thumb:
            if "center" in layout["thumb"].keys():
                image.paste(last_thumb,
                            (int((frame_size[0]-last_thumb.width)/2),
                             int((frame_size[1]-last_thumb.height)/2)))
            else:
                image.paste(last_thumb, layout["thumb"]["pos"])
    else:
        last_thumb = None

    # progress bar
    if (prog != -1 and "prog" in layout.keys()):
        if "vertical" in layout["prog"].keys():
            progress_bar(draw, color_progbg, color_progfg,
                         layout["prog"]["pos"][0], layout["prog"]["pos"][1],
                         layout["prog"]["len"],
                         layout["prog"]["height"],
                         prog, vertical=True)
        elif info['MusicPlayer.Time'].count(":") == 2:
            # longer bar for longer displayed time
            progress_bar(draw, color_progbg, color_progfg,
                         layout["prog"]["pos"][0], layout["prog"]["pos"][1],
                         layout["prog"]["long_len"], layout["prog"]["height"],
                         prog)
        else:
            progress_bar(draw, color_progbg, color_progfg,
                         layout["prog"]["pos"][0], layout["prog"]["pos"][1],
                         layout["prog"]["short_len"], layout["prog"]["height"],
                         prog)

    # text fields, if there are any
    if "fields" not in layout.keys():
        return

    txt_field = layout["fields"]
    for index in range(len(txt_field)):

        # special treatment for codec, which gets a lookup
        if txt_field[index]["name"] == "codec":
            if info['MusicPlayer.Codec'] in codec_name.keys():
                draw.text(txt_field[index]["pos"],
                          codec_name[info['MusicPlayer.Codec']],
                          fill=txt_field[index]["fill"],
                          font=txt_field[index]["font"])

        # special treatment for MusicPlayer.Artist
        elif txt_field[index]["name"] == "artist":
            if info['MusicPlayer.Artist'] != "":
                truncate_text(draw, txt_field[index]["pos"],
                              info['MusicPlayer.Artist'],
                              fill=txt_field[index]["fill"],
                              font=txt_field[index]["font"])
            elif info['MusicPlayer.Property(Role.Composer)'] != "":
                truncate_text(draw, txt_field[index]["pos"],
                              "(" + info['MusicPlayer.Property(Role.Composer)'] + ")",
                              fill=txt_field[index]["fill"],
                              font=txt_field[index]["font"])

        # all other fields
        else:
            if (txt_field[index]["name"] in info.keys() and
                info[txt_field[index]["name"]] != ""):
                # ender any label first
                if "label" in txt_field[index]:
                    draw.text(txt_field[index]["lpos"], txt_field[index]["label"],
                              fill=txt_field[index]["lfill"], font=txt_field[index]["lfont"])
                # now render the field itself
                if "trunc" in txt_field[index].keys():
                    truncate_text(draw, txt_field[index]["pos"],
                                  info[txt_field[index]["name"]],
                                  fill=txt_field[index]["fill"],
                                  font=txt_field[index]["font"])
                else:
                    draw.text(txt_field[index]["pos"],
                              info[txt_field[index]["name"]],
                              fill=txt_field[index]["fill"],
                              font=txt_field[index]["font"])



def screen_on():
    if not USE_BACKLIGHT:
        return
    if USE_PWM:
        device.backlight(PWM_LEVEL)
    else:
        device.backlight(True)

def screen_off():
    if not USE_BACKLIGHT:
        return;
    if USE_PWM:
        device.backlight(0)
    device.backlight(False)


# Kodi-polling and image rendering function
#
# Determine Kodi state and, if something of interest is playing,
# retrieve all the relevant information and get it drawn.
def update_display():
    global last_image_path
    global last_thumb
    global screen_press
    global screen_active
    global screen_offtime
    global audio_dmode

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
        response['result'][0]['type'] != 'audio'):
        # Nothing is playing or non-audio is playing, but check for screen
        # press before proceeding
        last_image_path = None
        last_thumb = None

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
                                        "System.Date",
                                        "System.Time",
                ]},
                "id"      : 10,
            }
            status_resp = requests.post(rpc_url, data=json.dumps(payload), headers=headers).json()
            status_screen(draw, status_resp['result'], summary)
        else:
            screen_off()

    else:
        # Audio is playing!
        screen_on()

        # Change display modes upon any screen press, forcing
        # a re-fetch of any artwork
        if screen_press:
            screen_press = False
            audio_dmode = audio_dmode.next()
            print(datetime.now(), "audio display mode now", audio_dmode.name)
            last_image_path = None
            last_thumb = None

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
                                    "MusicPlayer.Year",
                                    "MusicPlayer.Genre",
                                    "MusicPlayer.Cover",
            ]},
            "id"      : 4,
        }
        response = requests.post(rpc_url, data=json.dumps(payload), headers=headers).json()
        #print("Response: ", json.dumps(response))
        track_info = response['result']

        # Progress information in Kodi Leia must be fetched separately.  This
        # looks to be fixed in Kodi Matrix.
        payload = {
            "jsonrpc": "2.0",
            "method"  : "Player.GetProperties",
            "params"  : {
                "playerid": 0,
                "properties" : ["percentage"],
            },
            "id"      : "prog",
        }
        prog_response = requests.post(rpc_url, data=json.dumps(payload), headers=headers).json()
        if ('result' in prog_response.keys() and 'percentage' in prog_response['result'].keys()):
            prog = float(prog_response['result']['percentage']) / 100.0
        else:
            prog = -1

        # Audio info
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


def main():
    global kodi_active
    global screen_press
    kodi_active = False

    print(datetime.now(), "Starting")
    # turn down verbosity from http connections
    logging.basicConfig()
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    # setup T_IRQ as a GPIO interrupt, if enabled
    if USE_TOUCH:
        print(datetime.now(), "Setting up touchscreen interrupt")
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(TOUCH_INT, GPIO.IN)
        GPIO.add_event_detect(TOUCH_INT, GPIO.FALLING,
                              callback=touch_callback, bouncetime=950)

    # main communication loop
    while True:
        screen_on()
        draw.rectangle([(0,0), (frame_size[0],frame_size[1])], 'black', 'black')
        draw.text(( 5, 5), "Waiting to connect with Kodi...",  fill='white', font=font_main)
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
                update_display()
            except (ConnectionRefusedError,
                    requests.exceptions.ConnectionError):
                print(datetime.now(), "Communication disrupted.")
                kodi_active = False
                break

            # This delay seems sufficient to have a (usually) smooth
            # progress bar and elapsed time update.  The goal is to
            # wake up once a second, but this is effectively running
            # open-loop.  An occassional hiccup is somewhat
            # unavoidable.
            #
            # An alternative would be to maintain our own elapsed time
            # counter.  Keeping that counter accurate, though, would
            # then require notifications regarding pauses, seeks, or
            # faster-than 1x playback.  This is a potential reason to
            # explore using WebSocket as the JSON-RPC transport
            # mechanism.
            time.sleep(0.91)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        if USE_TOUCH:
            print(datetime.now(), "Removing touchscreen interrupt")
            GPIO.remove_event_detect(TOUCH_INT)
        GPIO.cleanup()
        print(datetime.now(), "Stopping")
        exit(0)
